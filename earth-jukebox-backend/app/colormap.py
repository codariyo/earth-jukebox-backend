"""GIBS renk haritasi (colormap) ile pikselleri GERCEK veri degerlerine cevirir.

GIBS Python ornekleri sayfasindaki yontem (ornek 27 ve 28):
  1. Katmanin renk haritasi XML'ini indir:
       https://gibs.earthdata.nasa.gov/colormaps/v1.3/<KatmanAdi>.xml
  2. Her <ColorMapEntry> bir RGB rengini bir deger araligina baglar:
       <ColorMapEntry rgb="255,150,50" transparent="false" value="[280.0,290.0)" .../>
  3. Goruntudeki her pikselin RGB'sini bu tabloda ara. Tabloda yoksa "veri yok".
Bu, "mavi dusuk, kirmizi yuksek" tahmininden cok daha dogrudur: sonuc gercek
birimle gelir (ornegin Kelvin).

Sayfanin uyarisi: JPEG sikistirmasi renkleri bozar, mutlaka PNG kullan.
Biz zaten PNG istiyoruz.
"""
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import CACHE_DIR

COLORMAP_URL = "https://gibs.earthdata.nasa.gov/colormaps/v1.3/{layer}.xml"
NEAREST_TOLERANCE = 12  # renk tabloda birebir yoksa en yakin rengi bu mesafeye kadar kabul et

_VALUE_RE = re.compile(r"^[\[\(]\s*([^,\]\)]+?)\s*(?:,\s*([^\]\)]+?)\s*)?[\]\)]$")
_memory: dict[str, "Colormap | None"] = {}


@dataclass
class Colormap:
    layer: str
    title: str
    units: str
    keys: np.ndarray  # siralanmis paketlenmis RGB (r<<16 | g<<8 | b)
    mids: np.ndarray  # her rengin temsil ettigi deger (aralik ortasi)
    rgbs: np.ndarray  # (N, 3) en yakin renk aramasi icin
    bin_width: float | None  # tipik aralik genisligi = olcum hassasiyeti

    @property
    def vmin(self) -> float:
        return float(self.mids.min())

    @property
    def vmax(self) -> float:
        return float(self.mids.max())

    def to_real(self, v01: float) -> float:
        """0-1 araligindaki degeri gercek birime cevirir."""
        return self.vmin + v01 * (self.vmax - self.vmin)


def _num(tok: str) -> float:
    t = tok.strip().upper().replace("+", "")
    if t in ("INF", "INFINITY"):
        return math.inf
    if t in ("-INF", "-INFINITY"):
        return -math.inf
    return float(tok)


def parse_value(text: str) -> tuple[float, float] | None:
    """'[280.0,290.0)' -> (280, 290);  '[5]' -> (5, 5);  '[-INF,200)' -> (-inf, 200)."""
    m = _VALUE_RE.match(text.strip())
    if not m:
        try:
            v = float(text)
            return (v, v)
        except ValueError:
            return None
    a = _num(m.group(1))
    b = _num(m.group(2)) if m.group(2) is not None else a
    return (a, b)


def parse_colormap(xml_text: str, layer: str) -> Colormap | None:
    root = ET.fromstring(xml_text)
    rgbs, mids, widths = [], [], []
    title, units = "", ""

    for cmap in root.iter("ColorMap"):
        for entry in cmap.iter("ColorMapEntry"):
            # Veri-yok ve seffaf girisler deger tasimaz
            if entry.get("nodata", "false").lower() == "true":
                continue
            if entry.get("transparent", "false").lower() == "true":
                continue
            value = entry.get("value")
            if not value:
                continue  # siniflandirma haritasi (sayisal deger yok)
            rng = parse_value(value)
            rgb = entry.get("rgb")
            if rng is None or not rgb:
                continue
            a, b = rng
            if math.isinf(a) and math.isinf(b):
                continue
            mid = b if math.isinf(a) else a if math.isinf(b) else (a + b) / 2
            if not (math.isinf(a) or math.isinf(b)) and b > a:
                widths.append(b - a)
            rgbs.append(tuple(int(x) for x in rgb.split(",")[:3]))
            mids.append(mid)
            if not title:
                title = cmap.get("title", "")
            if not units:
                units = cmap.get("units", "") or ""

    if len(rgbs) < 2:
        return None

    rgb_arr = np.array(rgbs, dtype=np.int64)
    packed = (rgb_arr[:, 0] << 16) | (rgb_arr[:, 1] << 8) | rgb_arr[:, 2]
    order = np.argsort(packed)
    return Colormap(
        layer=layer,
        title=title,
        units=units,
        keys=packed[order],
        mids=np.array(mids, dtype=np.float64)[order],
        rgbs=rgb_arr[order],
        bin_width=float(np.median(widths)) if widths else None,
    )


async def get_colormap(client, layer: str) -> Colormap | None:
    """Renk haritasini indirir (diske ve bellege onbellekler). Yoksa None."""
    if layer in _memory:
        return _memory[layer]

    cache_file = Path(CACHE_DIR) / "colormaps" / f"{layer}.xml"
    text = None
    if cache_file.exists():
        text = cache_file.read_text(encoding="utf-8")
    else:
        try:
            resp = await client.get(COLORMAP_URL.format(layer=layer))
            if resp.status_code == 200 and "<ColorMap" in resp.text:
                text = resp.text
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(text, encoding="utf-8")
        except Exception:
            text = None

    cmap = None
    if text:
        try:
            cmap = parse_colormap(text, layer)
        except ET.ParseError:
            cmap = None
    _memory[layer] = cmap
    return cmap


def values_from_colormap(rgba: np.ndarray, cmap: Colormap) -> tuple[np.ndarray, np.ndarray]:
    """Her piksel icin (0-1 arasi mutlak deger, gecerli mi) dondurur.

    0-1 araligi renk haritasinin TAMAMINA gore hesaplanir, goruntuye gore degil.
    Bu yuzden farkli tarihler ayni cetvelle olculur ve karsilastirilabilir kalir.
    """
    r = rgba[..., 0].astype(np.int64)
    g = rgba[..., 1].astype(np.int64)
    b = rgba[..., 2].astype(np.int64)
    packed = (r << 16) | (g << 8) | b
    opaque = rgba[..., 3] > 0

    uniq, inverse = np.unique(packed, return_inverse=True)
    uniq_vals = np.full(uniq.shape, np.nan)

    idx = np.searchsorted(cmap.keys, uniq)
    idx_c = np.clip(idx, 0, len(cmap.keys) - 1)
    exact = cmap.keys[idx_c] == uniq
    uniq_vals[exact] = cmap.mids[idx_c[exact]]

    # Birebir eslesmeyen renkler (kenar yumusatmasi vb.) icin en yakin renk
    for i in np.where(~exact)[0]:
        u = uniq[i]
        col = np.array([(u >> 16) & 255, (u >> 8) & 255, u & 255])
        d = np.sqrt(((cmap.rgbs - col) ** 2).sum(axis=1))
        j = int(np.argmin(d))
        if d[j] <= NEAREST_TOLERANCE:
            uniq_vals[i] = cmap.mids[j]

    real = uniq_vals[inverse].reshape(packed.shape)
    valid = opaque & ~np.isnan(real)
    span = max(cmap.vmax - cmap.vmin, 1e-9)
    values01 = np.where(valid, (real - cmap.vmin) / span, 0.0)
    return np.clip(values01, 0.0, 1.0), valid


def display(value: float, units: str) -> tuple[float, str]:
    """Kelvin'i Celsius'a cevirir; diger birimleri oldugu gibi birakir."""
    if units.strip().upper() in ("K", "KELVIN"):
        return value - 273.15, "°C"
    return value, units


def display_diff(diff: float, units: str) -> tuple[float, str]:
    """Fark icin: 1 K fark = 1 °C fark (kayma yok)."""
    if units.strip().upper() in ("K", "KELVIN"):
        return diff, "°C"
    return diff, units
