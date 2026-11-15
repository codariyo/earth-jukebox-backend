"""Harita servisleri: GIBS'ten veri ceker, gorsele cevirir. API katmani sadece bunu cagirir.

Tek tarih     -> single_map()     PNG: harita + kiyi cizgisi + baslik + GIBS lejanti
Tarih araligi -> range_gif()      GIF: araliktaki degisim, kare kare (sayfadaki animasyon ornegi)
Karsilastirma -> compare_png()    PNG: once | sonra | fark haritasi (renk haritasiyla gercek birim)
"""
import asyncio
from datetime import date, timedelta

import numpy as np
from PIL import Image, ImageDraw

from . import capabilities, gibs_api, render
from .colormap import Colormap, display_diff, parse_colormap
from .config import (
    BASEMAP_LAYER,
    COASTLINE_LAYER,
    MAIN_THEMES,
    MAX_FRAMES,
    THEMES,
    WORLD_BBOX,
)
from .sonify import extract

PROJECTION_NAMES = {
    4326: "Coğrafi (enlem-boylam)",
    3857: "Web Mercator",
    3413: "Kuzey Kutbu stereografik",
    3031: "Güney Kutbu stereografik",
}


class MapRequestError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ---------- yardimcilar ----------
def get_theme(theme_id: str) -> dict:
    if theme_id not in THEMES:
        raise MapRequestError(f"'{theme_id}' diye bir tema yok. Seçenekler: {', '.join(THEMES)}", 404)
    return THEMES[theme_id]


def image_size(bbox, width: int) -> tuple[int, int]:
    ratio = (bbox[3] - bbox[1]) / (bbox[2] - bbox[0])
    return width, max(64, round(width * ratio))


def fallback_snap(theme: dict, d: date) -> date | None:
    """Capabilities indirilemezse config'deki kurallarla tarih uydurma (yedek)."""
    cadence = theme.get("cadence", "daily")
    if cadence == "static":
        return None
    d = max(d, date.fromisoformat(theme["since"]))
    if theme.get("until"):
        d = min(d, date.fromisoformat(theme["until"]))
    if cadence == "monthly":
        return d.replace(day=1)
    if cadence == "8day":
        start = (d.timetuple().tm_yday - 1) // 8 * 8
        return date(d.year, 1, 1) + timedelta(days=start)
    return d


async def snap_date(theme: dict, d: date):
    """(kullanilacak tarih | None=zamansiz, LayerInfo | None)"""
    info = await capabilities.get_layer(theme["layer"])
    if info is None:
        return fallback_snap(theme, d), None
    return (info.snap(d) if info.has_time else None), info


def coverage_text(theme: dict, info) -> str:
    if info is not None:
        return info.describe_coverage()
    until = theme.get("until") or "bugün"
    return f"{theme.get('since', '?')} → {until} (yedek bilgi)"


def date_note(requested: date, used: date | None) -> str:
    if used is None or used == requested:
        return ""
    return f"{requested} için veri yok; en yakın veri tarihi {used} gösteriliyor."


async def fetch_layer(theme: dict, bbox, w: int, h: int, day: date | None) -> bytes:
    return await gibs_api.wms_getmap([theme["layer"]], bbox, w, h, day.isoformat() if day else None)


async def coastline(bbox, w: int, h: int) -> Image.Image | None:
    try:
        return render.open_rgba(await gibs_api.wms_getmap([COASTLINE_LAYER], bbox, w, h))
    except gibs_api.GibsError:
        return None  # kiyi cizgisi suslemedir, yoksa harita yine gelir


async def legend(info) -> Image.Image | None:
    if info is None or not info.legend_url:
        return None
    try:
        return render.open_rgba(await gibs_api.legend_png(info.legend_url))
    except gibs_api.GibsError:
        return None


async def colormap_for(theme: dict, info) -> Colormap | None:
    """Sayfadaki 'Numerical Analysis of GIBS ColorMap': renk -> gercek deger tablosu.

    URL capabilities'ten gelir (katman adiyla ayni olmayabilir: NDVI -> MODIS_NDVI.xml).
    """
    if theme.get("feature") != "colormap" or info is None or not info.colormap_url:
        return None
    try:
        text = await gibs_api.fetch_text(info.colormap_url, "NASA GIBS renk haritasi")
        return parse_colormap(text, theme["layer"])
    except Exception:
        return None


async def _nothing():
    return None


def _decorate(img_rgba: Image.Image, coast: Image.Image | None) -> Image.Image:
    return render.flatten(render.overlay(img_rgba, coast))


# ---------- tek tarih ----------
async def single_map(theme_id: str, bbox, width: int, day: date,
                     with_legend: bool = True, with_coast: bool = True) -> Image.Image:
    theme = get_theme(theme_id)
    used, info = await snap_date(theme, day)
    w, h = image_size(bbox, width)
    png, coast, leg = await asyncio.gather(
        fetch_layer(theme, bbox, w, h, used),
        coastline(bbox, w, h) if with_coast else _nothing(),
        legend(info) if with_legend else _nothing(),
    )
    img = _decorate(render.open_rgba(png), coast)
    img = render.with_header(
        img, theme["title"], f"{theme['layer']} · {coverage_text(theme, info)}",
        right=used.isoformat() if used else "zamansız",
    )
    return render.with_footer(img, leg, date_note(day, used))


async def single_map_png(*args, **kwargs) -> bytes:
    return render.png_bytes(await single_map(*args, **kwargs))


# ---------- tarih araligi: animasyon ----------
def frame_dates(start: date, end: date, n: int) -> list[date]:
    """Aralikta n tarih.

    Aralik 2 yildan uzunsa her kare AYNI MEVSIMDEN alinir (baslangicin ay-gunu,
    farkli yillar). Boylece yaz-kis farki degil, yillar arasi degisim gorulur.
    """
    if end < start:
        raise MapRequestError("Bitiş tarihi başlangıçtan önce olamaz.")
    n = max(2, min(MAX_FRAMES, n))
    span = (end - start).days
    if span >= 730:
        years = list(range(start.year, end.year + 1))
        picks = sorted({years[round(i * (len(years) - 1) / (n - 1))] for i in range(n)})
        out = []
        for y in picks:
            try:
                d = start.replace(year=y)
            except ValueError:  # 29 Subat
                d = start.replace(year=y, day=28)
            out.append(min(d, end))
    else:
        out = [start + timedelta(days=round(i * span / (n - 1))) for i in range(n)]
    seen, uniq = set(), []
    for d in out:
        if d not in seen:
            seen.add(d)
            uniq.append(d)
    return uniq


async def range_gif(theme_id: str, bbox, width: int, start: date, end: date, frames: int,
                    with_coast: bool = True) -> bytes:
    theme = get_theme(theme_id)
    wanted = frame_dates(start, end, frames)
    snapped = await asyncio.gather(*(snap_date(theme, d) for d in wanted))
    info = snapped[0][1]
    used = []
    for d, _ in snapped:
        if d is None:
            raise MapRequestError(f"{theme['title']} zamansız bir katman; aralık animasyonu yapılamaz.")
        if d not in used:
            used.append(d)

    w, h = image_size(bbox, width)
    results = await asyncio.gather(
        *(fetch_layer(theme, bbox, w, h, d) for d in used), return_exceptions=True
    )
    coast, leg = await asyncio.gather(
        coastline(bbox, w, h) if with_coast else _nothing(), legend(info)
    )
    note = f"İstenen aralık {start} → {end}; veri olan {len(used)} tarih gösteriliyor."
    if len(used) < len(wanted):
        note += " (Bazı tarihler aynı veriye denk geldi.)"

    out = []
    for i, (d, res) in enumerate(zip(used, results)):
        if isinstance(res, Exception):
            body = render.message_panel((w, h), "Bu tarih için görüntü alınamadı", str(res))
        else:
            body = _decorate(render.open_rgba(res), coast)
        frame = render.with_header(
            body, theme["title"], f"{theme['layer']} · kare {i + 1}/{len(used)} · {start} → {end}",
            right=d.isoformat(),
        )
        frame = render.with_footer(frame, leg, note)
        out.append(render.progress_bar(frame, i, len(used)))
    return render.gif_bytes(out)


# ---------- tarih araligi: once / sonra / fark ----------
async def compare_png(theme_id: str, bbox, width: int, start: date, end: date,
                      with_coast: bool = True) -> bytes:
    theme = get_theme(theme_id)
    if end < start:
        raise MapRequestError("Bitiş tarihi başlangıçtan önce olamaz.")
    (used_a, info), (used_b, _) = await asyncio.gather(snap_date(theme, start), snap_date(theme, end))
    if used_a is None:
        raise MapRequestError(f"{theme['title']} zamansız bir katman; karşılaştırma yapılamaz.")

    w, h = image_size(bbox, width)
    png_a, png_b, coast, cmap, leg = await asyncio.gather(
        fetch_layer(theme, bbox, w, h, used_a),
        fetch_layer(theme, bbox, w, h, used_b),
        coastline(bbox, w, h) if with_coast else _nothing(),
        colormap_for(theme, info),
        legend(info),
    )
    img_a, img_b = render.open_rgba(png_a), render.open_rgba(png_b)
    va, valid_a, source = extract(img_a, theme, cmap)
    vb, valid_b, _ = extract(img_b, theme, cmap)
    diff_img, scale, mean, frac = render.diff_rgba(va, valid_a, vb, valid_b)

    if cmap is not None and source == "renk_haritasi":
        span = cmap.vmax - cmap.vmin
        scale_r, unit = display_diff(scale * span, cmap.units)
        mean_r, _ = display_diff(mean * span, cmap.units)
        labels = (f"−{scale_r:.3g} {unit}", "0 (değişim yok)", f"+{scale_r:.3g} {unit}")
        summary = f"Ortalama fark: {mean_r:+.2f} {unit}"
        source_txt = "değerler GIBS renk haritasından (gerçek birim)"
    else:
        labels = (f"−{scale:.2f}", "0 (değişim yok)", f"+{scale:.2f}")
        summary = f"Ortalama fark: {mean:+.3f} (göreli, 0–1 ölçeği)"
        source_txt = "değerler renk tonu/parlaklıktan (göreli)"

    a = render.with_header(_decorate(img_a, coast), "Önce", right=used_a.isoformat())
    b = render.with_header(_decorate(img_b, coast), "Sonra", right=used_b.isoformat())
    d = render.with_header(_decorate(diff_img, coast), "Fark (sonra − önce)")
    combined = render.side_by_side([a, b, d])

    notes = [summary, f"ortak veri alanı %{frac * 100:.0f}",
             f"kırmızı = daha {theme['high_word']}, mavi = daha {theme['low_word']}"]
    if used_a == used_b:
        notes.insert(0, "İki tarih de aynı veriye denk geldi (katmanın kapsamı dışında kaldı)")
    elif frac == 0:
        notes.insert(0, "İki tarihte ortak veri olan piksel yok")
    for req, use in ((start, used_a), (end, used_b)):
        if use != req:
            notes.append(f"{req} → {use}")

    combined = render.with_header(
        combined, f"{theme['title']} — {used_a} ile {used_b} arasındaki değişim",
        f"{theme['layer']} · {source_txt} · {coverage_text(theme, info)}",
    )
    colorbar = render.diff_colorbar(combined.width, *labels)
    return render.png_bytes(render.with_footer(combined, [colorbar, leg], " · ".join(notes)))


# ---------- genel bakis: 6 harita tek gorselde ----------
async def overview_png(bbox, cell_width: int, day: date, theme_ids: list[str] | None = None) -> bytes:
    ids = theme_ids or MAIN_THEMES
    results = await asyncio.gather(
        *(single_map(t, bbox, cell_width, day) for t in ids), return_exceptions=True
    )
    w, h = image_size(bbox, cell_width)
    panels = []
    for t, res in zip(ids, results):
        if isinstance(res, Exception):
            title = THEMES.get(t, {}).get("title", t)
            res = render.message_panel((w, h + 60), f"{title}: alınamadı", str(res))
        panels.append(res)
    img = render.grid(panels, cols=3 if len(panels) > 4 else 2)
    return render.png_bytes(render.with_header(img, "Earth Jukebox — NASA GIBS genel bakış", f"İstenen tarih: {day}"))


# ---------- projeksiyon ----------
async def projection_png(theme_id: str, epsg: int, day: date, size: int) -> bytes:
    theme = get_theme(theme_id)
    if epsg not in gibs_api.PROJECTION_EXTENTS:
        raise MapRequestError(f"Desteklenen projeksiyonlar: {', '.join(map(str, gibs_api.PROJECTION_EXTENTS))}")
    used, info = await snap_date(theme, day)
    w, h = (size * 2, size) if epsg == 4326 else (size, size)
    png = await gibs_api.wms_getmap(
        [theme["layer"]], gibs_api.PROJECTION_EXTENTS[epsg], w, h,
        used.isoformat() if used else None, epsg=epsg,
    )
    img = render.with_header(
        render.flatten(render.open_rgba(png)), f"{theme['title']} — EPSG:{epsg}",
        f"{PROJECTION_NAMES[epsg]} · {theme['layer']}", right=used.isoformat() if used else "zamansız",
    )
    return render.png_bytes(render.with_footer(img, None, date_note(day, used)))


# ---------- WMTS karo ----------
async def tile(theme_id: str, z: int, row: int, col: int, day: date) -> tuple[bytes, str]:
    theme = get_theme(theme_id)
    used, info = await snap_date(theme, day)
    if info is None or not info.tile_matrix_sets:
        raise MapRequestError("Bu katmanın WMTS bilgisi alınamadı (capabilities).", 502)
    ext = info.tile_ext
    data = await gibs_api.wmts_tile(
        theme["layer"], used.isoformat() if used else None, info.tile_matrix_sets[0], z, row, col, ext
    )
    return data, "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"


# ---------- lejant ----------
async def legend_png(theme_id: str) -> bytes:
    theme = get_theme(theme_id)
    info = await capabilities.get_layer(theme["layer"])
    leg = await legend(info)
    if leg is None:
        raise MapRequestError(f"{theme['title']} için GIBS lejantı yok (gerçek renkli görüntü olabilir).", 404)
    canvas = render.flatten(leg, (255, 255, 255))
    canvas = render.resize_w(canvas, max(600, canvas.width))
    return render.png_bytes(render.with_header(canvas, f"{theme['title']} — lejant", theme["layer"]))


# ---------- EONET dogal olaylar ----------
EVENT_COLORS = {
    "wildfires": (255, 99, 71), "volcanoes": (255, 165, 0), "severeStorms": (135, 206, 250),
    "seaLakeIce": (224, 255, 255), "floods": (30, 144, 255), "drought": (210, 180, 140),
    "dustHaze": (189, 183, 107), "earthquakes": (186, 85, 211), "landslides": (139, 69, 19),
    "snow": (255, 255, 255), "tempExtremes": (255, 20, 147), "waterColor": (0, 206, 209),
    "manmade": (128, 128, 128),
}


def _event_point(geom: dict) -> tuple[float, float] | None:
    c = geom.get("coordinates")
    if not c:
        return None
    if geom.get("type") == "Point":
        return float(c[0]), float(c[1])
    pts = np.array(c[0] if geom.get("type") == "Polygon" else c, dtype=float).reshape(-1, 2)
    return float(pts[:, 0].mean()), float(pts[:, 1].mean())


async def events_png(start: date, end: date, categories: list[str] | None, width: int) -> bytes:
    data, base = await asyncio.gather(
        gibs_api.eonet_events(start.isoformat(), end.isoformat(), categories),
        gibs_api.wms_getmap([BASEMAP_LAYER], WORLD_BBOX, width, width // 2),
    )
    img = render.flatten(render.open_rgba(base))
    draw = ImageDraw.Draw(img)
    W, H = img.size
    f = render.font(max(10, width // 110))
    counts: dict[str, int] = {}
    events = data.get("events", [])
    r = max(3, width // 260)
    for ev in events:
        cat = (ev.get("categories") or [{}])[0]
        cid, ctitle = cat.get("id", "?"), cat.get("title", "?")
        counts[ctitle] = counts.get(ctitle, 0) + 1
        geoms = ev.get("geometry") or []
        if not geoms:
            continue
        pt = _event_point(geoms[-1])  # son konum
        if pt is None:
            continue
        x, y = (pt[0] + 180) / 360 * W, (90 - pt[1]) / 180 * H
        color = EVENT_COLORS.get(cid, (255, 0, 0))
        draw.ellipse([x - r, y - r, x + r, y + r], fill=color, outline=(0, 0, 0))
    if len(events) <= 25:  # az olay varsa adlarini da yaz
        for ev in events:
            geoms = ev.get("geometry") or []
            pt = _event_point(geoms[-1]) if geoms else None
            if pt:
                x, y = (pt[0] + 180) / 360 * W, (90 - pt[1]) / 180 * H
                draw.text((x + r + 2, y - r - 2), ev.get("title", "")[:40], font=f, fill=(255, 255, 255))
    summary = " · ".join(f"{k}: {v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])) or "Bu aralıkta olay yok"
    img = render.with_header(img, f"NASA EONET doğal olaylar — {start} → {end}",
                             f"{len(events)} olay · taban harita GIBS {BASEMAP_LAYER}")
    return render.png_bytes(render.with_footer(img, None, summary))


# ---------- katalog ----------
async def catalog_png() -> bytes:
    rows = []
    ids = MAIN_THEMES + [t for t in THEMES if t not in MAIN_THEMES]
    for t in ids:
        theme = THEMES[t]
        info = await capabilities.get_layer(theme["layer"])
        if info is None:
            rows.append([("• " if t in MAIN_THEMES else "  ") + t, theme["title"], theme["layer"],
                         "YOK / capabilities alınamadı", "-", "-"])
            continue
        rows.append([
            ("• " if t in MAIN_THEMES else "  ") + t, theme["title"], theme["layer"], info.describe_coverage(),
            ", ".join(info.tile_matrix_sets) or "-", "var" if info.colormap_url else "-",
        ])
    img = render.table_image(
        "Earth Jukebox — tema kataloğu (GIBS WMTS GetCapabilities'ten canlı)",
        ["Tema", "Başlık", "GIBS katmanı", "Veri aralığı", "TMS", "Renk haritası"],
        rows, [170, 230, 400, 330, 70, 120],
    )
    return render.png_bytes(render.with_footer(img, None, "• = uygulamada gösterilen 6 ana harita"))
