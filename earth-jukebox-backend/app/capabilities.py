"""WMTS GetCapabilities'ten katman bilgisi ve GERCEK tarih listesi.

Sayfadaki "Get WMTS Capabilities" / "Display WMTS Layer Attributes" ornekleri:
her <Layer> icin kimlik, TileMatrixSet, format, renk haritasi linki (Metadata
role=.../colormap/1.3), yatay lejant (LegendURL role=.../horizontal) ve
<Dimension><Value> icindeki zaman araliklari okunur.

Zaman araligi bicimi (ISO 8601):  "2000-02-24/2026-11-14/P1D"  ya da  "2014-10-22/2014-12-21/P5D"
Ornek: OSCAR akintilari 2024-07-17'de bitiyor, NDVI sadece 2025-02-12'den var.
Bu yuzden istenen tarih SABIT KURALLA degil, bu listeye gore yakalanir (snap).
"""
import asyncio
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import gibs_api

NS = {
    "w": "http://www.opengis.net/wmts/1.0",
    "ows": "http://www.opengis.net/ows/1.1",
}
XLINK = "{http://www.w3.org/1999/xlink}"
ROLE_COLORMAP = "http://earthdata.nasa.gov/gibs/metadata-type/colormap/1.3"
ROLE_LEGEND_H = "http://earthdata.nasa.gov/gibs/legend-type/horizontal"

_PERIOD_RE = re.compile(r"^P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)D)?(?:T.*)?$")


@dataclass
class TimeRange:
    start: date
    end: date
    unit: str  # "D" | "M" | "Y"
    step: int

    def latest_on_or_before(self, d: date) -> date | None:
        if d < self.start:
            return None
        d = min(d, self.end)
        if self.unit == "D":
            n = (d - self.start).days // self.step
            return self.start + timedelta(days=n * self.step)
        months = (d.year - self.start.year) * 12 + (d.month - self.start.month)
        if d.day < self.start.day:
            months -= 1
        step_m = self.step * (12 if self.unit == "Y" else 1)
        months = (months // step_m) * step_m
        return _add_months(self.start, months)

    def earliest_on_or_after(self, d: date) -> date | None:
        if d > self.end:
            return None
        if d <= self.start:
            return self.start
        cand = self.latest_on_or_before(d)
        if cand == d:
            return d
        if self.unit == "D":
            nxt = cand + timedelta(days=self.step)
        else:
            nxt = _add_months(cand, self.step * (12 if self.unit == "Y" else 1))
        return nxt if nxt <= self.end else None


@dataclass
class LayerInfo:
    identifier: str
    title: str = ""
    tile_matrix_sets: list[str] = field(default_factory=list)
    formats: list[str] = field(default_factory=list)
    colormap_url: str | None = None
    legend_url: str | None = None  # PNG (WMTS SVG verir, ayni adla PNG de var)
    tile_template: str | None = None
    time_ranges: list[TimeRange] = field(default_factory=list)  # bos = zamansiz katman

    @property
    def has_time(self) -> bool:
        return bool(self.time_ranges)

    @property
    def first_date(self) -> date | None:
        return min((r.start for r in self.time_ranges), default=None)

    @property
    def last_date(self) -> date | None:
        return max((r.end for r in self.time_ranges), default=None)

    @property
    def tile_ext(self) -> str:
        if self.tile_template:
            return self.tile_template.rsplit(".", 1)[-1]
        return "jpg" if any("jpeg" in f for f in self.formats) else "png"

    def snap(self, requested: date) -> date | None:
        """Istenen tarihe en yakin GECERLI tarih.

        Once istenen gune kadar olan son veri (veri geriye dogru aranir),
        yoksa (tarih katmanin baslangicindan once) ilk veri.
        """
        if not self.time_ranges:
            return None
        before = [d for r in self.time_ranges if (d := r.latest_on_or_before(requested))]
        if before:
            return max(before)
        after = [d for r in self.time_ranges if (d := r.earliest_on_or_after(requested))]
        return min(after) if after else self.first_date

    def describe_coverage(self) -> str:
        if not self.time_ranges:
            return "zamansız"
        counts: dict[tuple[str, int], int] = {}
        for r in self.time_ranges:
            counts[(r.unit, r.step)] = counts.get((r.unit, r.step), 0) + 1
        unit, step = max(counts, key=counts.get)
        word = {"D": "günlük", "M": "aylık", "Y": "yıllık"}[unit]
        freq = word if step == 1 else f"{step} {word}"
        return f"{self.first_date} → {self.last_date} ({freq})"


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    day = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


def parse_period(p: str) -> tuple[str, int]:
    m = _PERIOD_RE.match(p.strip())
    if not m or not any(m.groups()[:3]):
        return ("D", 1)  # PT30M gibi gun-ici periyotlar: tarih bazinda gunluk say
    y, mo, d = (int(x) if x else 0 for x in m.groups()[:3])
    if y:
        return ("Y", y)
    if mo:
        return ("M", mo)
    return ("D", d or 1)


def parse_time_value(text: str) -> list[TimeRange]:
    out = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        bits = part.split("/")
        try:
            start = date.fromisoformat(bits[0][:10])
            end = date.fromisoformat(bits[1][:10]) if len(bits) > 1 else start
        except ValueError:
            continue
        unit, step = parse_period(bits[2]) if len(bits) > 2 else ("D", 1)
        out.append(TimeRange(start, end, unit, step))
    return out


def parse_wmts_capabilities(xml_text: str) -> dict[str, LayerInfo]:
    root = ET.fromstring(xml_text)
    layers: dict[str, LayerInfo] = {}
    for layer in root.iter(f"{{{NS['w']}}}Layer"):
        ident = layer.find("ows:Identifier", NS)
        if ident is None or not ident.text:
            continue
        title = layer.find("ows:Title", NS)
        info = LayerInfo(identifier=ident.text, title=title.text if title is not None else "")
        info.tile_matrix_sets = [t.text for t in layer.findall("w:TileMatrixSetLink/w:TileMatrixSet", NS) if t.text]
        info.formats = [f.text for f in layer.findall("w:Format", NS) if f.text]
        for md in layer.findall("ows:Metadata", NS):
            if md.get(f"{XLINK}role") == ROLE_COLORMAP:
                info.colormap_url = md.get(f"{XLINK}href")
        for lg in layer.findall("w:Style/w:LegendURL", NS):
            if lg.get(f"{XLINK}role") == ROLE_LEGEND_H and lg.get(f"{XLINK}href"):
                href = lg.get(f"{XLINK}href")
                info.legend_url = href[:-4] + ".png" if href.endswith(".svg") else href
        for ru in layer.findall("w:ResourceURL", NS):
            tpl = ru.get("template", "")
            if "{Time}" in tpl and "{TileCol}" in tpl:
                info.tile_template = tpl
        for dim in layer.findall("w:Dimension", NS):
            ident_d = dim.find("ows:Identifier", NS)
            if ident_d is not None and (ident_d.text or "").lower() == "time":
                for v in dim.findall("w:Value", NS):
                    if v.text:
                        info.time_ranges.extend(parse_time_value(v.text))
        layers[info.identifier] = info
    return layers


# ---------- calisma anindaki onbellek ----------
_layers: dict[str, LayerInfo] | None = None
_lock: asyncio.Lock | None = None
_lock_loop = None


def _get_lock() -> asyncio.Lock:
    global _lock, _lock_loop
    loop = asyncio.get_running_loop()
    if _lock is None or _lock_loop is not loop:
        _lock = asyncio.Lock()
        _lock_loop = loop
    return _lock


async def load_layers() -> dict[str, LayerInfo]:
    """WMTS capabilities'i bir kez indirir/ayristirir (diskte 12 saat taze kalir)."""
    global _layers
    if _layers is not None:
        return _layers
    async with _get_lock():
        if _layers is None:
            xml_text = await gibs_api.wmts_capabilities_xml()
            _layers = await asyncio.to_thread(parse_wmts_capabilities, xml_text)
    return _layers


async def get_layer(identifier: str) -> LayerInfo | None:
    """Katman bilgisi; capabilities indirilemezse None (cagiran yedek kurala doner)."""
    try:
        layers = await load_layers()
    except gibs_api.GibsError:
        return None
    return layers.get(identifier)


def reset_cache() -> None:
    global _layers
    _layers = None
