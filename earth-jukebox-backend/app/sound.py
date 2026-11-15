"""Muzik kutusu servisleri: haritayi NOTAYA ve KUREYE cevirir (frontend bunlari kullanir).

snapshot()  -> tek tarih: harita batidan doguya taranir, her serit bir nota (sonify.py)
timeline()  -> zaman yolculugu: her tarih icin bolge ortalamasi bir nota (yillar arasi degisim)
texture()   -> 3D kure / 2D harita icin BASLIKSIZ esdikdortgen goruntu
               (Blue Marble taban + veri katmani + kiyi cizgisi, JPEG)
theme_info() -> temanin gercek veri araligi (GIBS capabilities'ten), tarih secici icin
"""
import asyncio
import io
from collections import OrderedDict
from datetime import date, timedelta

import numpy as np
from PIL import Image, ImageEnhance

from . import capabilities, gibs_api, maps, render
from .colormap import display, display_diff
from .config import BASEMAP_LAYER, WORLD_BBOX
from .compare import joint_range
from .sonify import (describe, extract, midi_to_name, real_stats, series_to_notes, sonify_image,
                     value_to_midi)

CAUTION = (
    "Bu, seçilen tarihlerin karşılaştırmasıdır; tek tek günler/aylar bir iklim eğilimini "
    "kanıtlamaz. GIBS görüntüleri keşif amaçlıdır, resmî bilimsel ölçüm değildir."
)


# ---------- tema bilgisi ----------
async def theme_info(theme_id: str) -> dict:
    theme = maps.get_theme(theme_id)
    info = await capabilities.get_layer(theme["layer"])
    first = info.first_date if info else date.fromisoformat(theme["since"])
    last = info.last_date if info else (date.fromisoformat(theme["until"]) if theme.get("until") else date.today())
    unit, step = "D", 1
    if info and info.time_ranges:
        r = max(info.time_ranges, key=lambda tr: tr.end)
        unit, step = r.unit, r.step
    elif theme.get("cadence") == "monthly":
        unit = "M"
    elif theme.get("cadence") == "8day":
        step = 8
    return {
        "id": theme_id,
        "title": theme["title"],
        "layer": theme["layer"],
        "first": first.isoformat() if first else None,
        "last": last.isoformat() if last else None,
        "unit": unit,
        "step": step,
        "coverage": maps.coverage_text(theme, info),
        "legend_url": info.legend_url if info else None,
        "low_word": theme["low_word"],
        "high_word": theme["high_word"],
    }


async def resolve_date(theme_id: str, day: date) -> date | None:
    used, _ = await maps.snap_date(maps.get_theme(theme_id), day)
    return used


def _add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    return date(d.year + m // 12, m % 12 + 1, 1)


async def step_date(theme_id: str, day: date, direction: int) -> date:
    """Tarihi temanin veri adimiyla ileri/geri kaydirir, sonra gecerli tarihe oturtur."""
    info = await theme_info(theme_id)
    used = await resolve_date(theme_id, day) or day
    if info["unit"] == "M":
        cand = _add_months(used, direction * info["step"])
    elif info["unit"] == "Y":
        cand = used.replace(year=used.year + direction * info["step"])
    else:
        cand = used + timedelta(days=direction * info["step"])
    snapped = await resolve_date(theme_id, cand) or cand
    if direction > 0 and snapped <= used:  # son veriye dayandik
        return used
    return snapped


# ---------- tek tarih: haritayi tara ----------
async def snapshot(theme_id: str, bbox, day: date, steps: int = 32,
                   melodic: bool = True, width: int = 512) -> dict:
    """melodic=True: notalar seritlerin KENDI araligina yayilir (bolge ici farklar duyulur).
    melodic=False: renk haritasinin tamamina gore mutlak (farkli tarihler karsilastirilabilir)."""
    theme = maps.get_theme(theme_id)
    used, info = await maps.snap_date(theme, day)
    w, h = maps.image_size(bbox, width)
    png, cmap = await asyncio.gather(
        maps.fetch_layer(theme, bbox, w, h, used), maps.colormap_for(theme, info)
    )
    out = sonify_image(png, theme, steps=steps, cmap=cmap)
    # Istatistikler ENLEM AGIRLIKLI: esdikdortgen goruntude kutuplar asiri buyuk gorunur,
    # agirliksiz ortalama kuresel sicakligi ~8 °C dusuk verir.
    values, valid, source = extract(render.open_rgba(png), theme, cmap)
    raw = weighted_strips(values, valid, bbox, steps)
    stats = out["stats"]
    mean, _ = weighted_mean(values, valid, bbox)
    stats["mean_value"] = None if mean is None else round(mean, 4)
    stats["series"] = [None if v is None else round(v, 4) for v, _ in raw]
    stats["area_weighted"] = True
    if cmap is not None and source == "renk_haritasi":
        stats.update(real_stats(raw, cmap))
        if mean is not None:
            stats["mean_real"] = round(display(cmap.to_real(mean), cmap.units)[0], 2)
    if melodic:
        out["notes"] = series_to_notes(raw, theme, joint_range(raw, raw, padding=0.05))
    elif not theme.get("normalize"):
        out["notes"] = series_to_notes(raw, theme)
    out["description"] = describe(theme, raw, stats)
    return {
        "melodic": melodic,
        "kind": "snapshot",
        "theme": theme_id,
        "title": theme["title"],
        "layer": theme["layer"],
        "date_requested": day.isoformat(),
        "date_used": used.isoformat() if used else None,
        "date_note": maps.date_note(day, used),
        "bbox": list(bbox),
        "scale": theme["scale"],
        "root_midi": 12 * (theme["octave"] + 1),
        "low_word": theme["low_word"],
        "high_word": theme["high_word"],
        "coverage": maps.coverage_text(theme, info),
        **out,
    }


# ---------- zaman yolculugu: yillar arasi degisim ----------
def _lat_weights(bbox, h: int) -> np.ndarray:
    """Esdikdortgen goruntude kutuplar sisik gorunur; cos(enlem) ile esit alan agirligi."""
    top, bottom = bbox[3], bbox[1]
    lats = top - (np.arange(h) + 0.5) * (top - bottom) / h
    return np.clip(np.cos(np.radians(lats)), 0.0, None)[:, None]


def weighted_strips(values: np.ndarray, valid: np.ndarray, bbox, steps: int) -> list:
    """sonify._strips gibi (deger, kapsama) serisi, ama her seridin ortalamasi enlem agirlikli."""
    wts = _lat_weights(bbox, values.shape[0]) * valid
    out = []
    for cols in np.array_split(np.arange(values.shape[1]), steps):
        w, m = wts[:, cols], valid[:, cols]
        total = float(w.sum())
        coverage = float(m.mean()) if m.size else 0.0
        out.append((float((values[:, cols] * w).sum() / total) if total > 0 else None, coverage))
    return out


def weighted_mean(values: np.ndarray, valid: np.ndarray, bbox) -> tuple[float | None, float]:
    wts = _lat_weights(bbox, values.shape[0]) * valid
    total = float(wts.sum())
    if total <= 0:
        return None, 0.0
    return float((values * wts).sum() / total), float(valid.mean())


async def timeline(theme_id: str, bbox, start: date, end: date, frames: int = 10,
                   width: int = 360) -> dict:
    theme = maps.get_theme(theme_id)
    wanted = maps.frame_dates(start, end, frames)
    snapped = await asyncio.gather(*(maps.snap_date(theme, d) for d in wanted))
    info = snapped[0][1]
    used: list[date] = []
    for d, _ in snapped:
        if d is None:
            raise maps.MapRequestError(f"{theme['title']} zamansız bir katman; zaman yolculuğu yapılamaz.")
        if d not in used:
            used.append(d)
    used.sort()

    w, h = maps.image_size(bbox, width)
    pngs, cmap = await asyncio.gather(
        asyncio.gather(*(maps.fetch_layer(theme, bbox, w, h, d) for d in used), return_exceptions=True),
        maps.colormap_for(theme, info),
    )

    rows = []
    for d, png in zip(used, pngs):
        if isinstance(png, Exception):
            rows.append({"date": d.isoformat(), "value": None, "coverage": 0.0})
            continue
        values, valid, source = extract(render.open_rgba(png), theme, cmap)
        mean, cov = weighted_mean(values, valid, bbox)
        row = {"date": d.isoformat(), "value": None if mean is None else round(mean, 5), "coverage": round(cov, 3)}
        if mean is not None and cmap is not None and source == "renk_haritasi":
            real, units = display(cmap.to_real(mean), cmap.units)
            row.update(real=round(real, 2), units=units)
        rows.append(row)

    vals = [r["value"] for r in rows if r["value"] is not None]
    if not vals:
        raise maps.MapRequestError("Seçilen tarihlerde bu bölge için veri bulunamadı.", 404)
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.1 or 0.01
    lo, hi = lo - pad, hi + pad  # ortak cetvel: kucuk farklar da duyulur
    for r in rows:
        if r["value"] is None:
            continue
        midi = value_to_midi((r["value"] - lo) / (hi - lo), theme["scale"], theme["octave"])
        r.update(midi=midi, note=midi_to_name(midi), velocity=round(0.35 + 0.65 * min(1.0, r["coverage"] * 1.5), 2))

    return {
        "kind": "timeline",
        "theme": theme_id,
        "title": theme["title"],
        "layer": theme["layer"],
        "start": start.isoformat(),
        "end": end.isoformat(),
        "bbox": list(bbox),
        "scale": theme["scale"],
        "root_midi": 12 * (theme["octave"] + 1),
        "low_word": theme["low_word"],
        "high_word": theme["high_word"],
        "frames": rows,
        "description": _timeline_text(theme, rows, cmap),
        "caution": CAUTION,
    }


def _timeline_text(theme: dict, rows: list, cmap) -> str:
    good = [r for r in rows if r["value"] is not None]
    a, b = good[0], good[-1]
    title = theme["title"]
    if "real" in a and "real" in b:
        u = a["units"]
        diff = b["real"] - a["real"]
        years = np.array([date.fromisoformat(r["date"]).toordinal() / 365.25 for r in good])
        reals = np.array([r["real"] for r in good])
        trend = ""
        if len(good) >= 4 and years[-1] - years[0] >= 3:
            slope = float(np.polyfit(years, reals, 1)[0]) * 10
            d_slope, du = display_diff(slope, u)
            trend = f" Doğrusal eğilim: on yılda yaklaşık {d_slope:+.2f} {du}."
        text = (
            f"{title}: {a['date']} tarihinde bölge ortalaması {a['real']:.1f} {u}, "
            f"{b['date']} tarihinde {b['real']:.1f} {u}. Fark {diff:+.2f} {u}.{trend}"
        )
    else:
        diff = b["value"] - a["value"]
        direction = "arttı" if diff > 0 else "azaldı" if diff < 0 else "değişmedi"
        text = f"{title}: {a['date']} ile {b['date']} arasında göreli değer {direction} ({diff:+.3f})."
    return (
        f"{text} {len(good)} tarih sırayla çalınır; nota yükseldikçe değer "
        f"{theme['high_word']} yönüne gider, alçaldıkça {theme['low_word']} yönüne."
    )


# ---------- kure / harita dokusu ----------
_TEX_CACHE: "OrderedDict[tuple, bytes]" = OrderedDict()
_TEX_MAX = 48


async def _basemap(bbox, w: int, h: int) -> Image.Image | None:
    try:
        return render.open_rgba(await gibs_api.wms_getmap([BASEMAP_LAYER], bbox, w, h))
    except gibs_api.GibsError:
        return None


async def texture(theme_id: str, day: date, width: int = 2048, bbox=WORLD_BBOX) -> tuple[bytes, str | None]:
    """(JPEG, kullanilan tarih). Basliksiz, lejantsiz: kureye dogrudan sarilir."""
    theme = maps.get_theme(theme_id)
    used, _ = await maps.snap_date(theme, day)
    key = (theme_id, used, width, tuple(bbox))
    if key in _TEX_CACHE:
        _TEX_CACHE.move_to_end(key)
        return _TEX_CACHE[key], used.isoformat() if used else None

    w, h = maps.image_size(bbox, width)
    layer_png, coast, base = await asyncio.gather(
        maps.fetch_layer(theme, bbox, w, h, used),
        maps.coastline(bbox, w, h),
        _basemap(bbox, w, h),
    )
    # Birlestirme + JPEG ayri is parcaciginda: olay dongusu bloklanmasin, paralel kareler birbirini beklemesin
    data = await asyncio.to_thread(_compose, theme_id, w, h, layer_png, coast, base)
    _TEX_CACHE[key] = data
    if len(_TEX_CACHE) > _TEX_MAX:
        _TEX_CACHE.popitem(last=False)
    return data, used.isoformat() if used else None


def _compose(theme_id: str, w: int, h: int, layer_png, coast, base) -> bytes:
    if base is not None:
        true_color = theme_id == "dunya_renkleri"
        rgb = base.convert("RGB")
        if not true_color:  # veri katmani one ciksin diye taban harita soluk, NASA lacivertine yakin
            rgb = ImageEnhance.Color(rgb).enhance(0.45)
            rgb = ImageEnhance.Brightness(rgb).enhance(0.55)
            rgb = Image.blend(rgb, Image.new("RGB", rgb.size, (11, 61, 145)), 0.22)
        else:
            rgb = ImageEnhance.Brightness(rgb).enhance(0.8)
        canvas = rgb.convert("RGBA")
    else:
        canvas = Image.new("RGBA", (w, h), render.BG + (255,))
    canvas.alpha_composite(render.open_rgba(layer_png))
    if coast is not None:
        canvas = render.overlay(canvas, coast)

    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="JPEG", quality=88, optimize=True)
    return buf.getvalue()


def clamp_bbox_around(lat: float, lng: float, half_lon: float = 20.0, half_lat: float = 12.0) -> tuple:
    """Tiklanan noktanin cevresinde bolge (haritadan ozel konum secimi)."""
    lng = ((lng + 180) % 360) - 180
    lat = max(-90.0, min(90.0, lat))
    min_lon, max_lon = lng - half_lon, lng + half_lon
    if min_lon < -180:
        min_lon, max_lon = -180.0, -180.0 + 2 * half_lon
    if max_lon > 180:
        min_lon, max_lon = 180.0 - 2 * half_lon, 180.0
    min_lat, max_lat = lat - half_lat, lat + half_lat
    if min_lat < -90:
        min_lat, max_lat = -90.0, -90.0 + 2 * half_lat
    if max_lat > 90:
        min_lat, max_lat = 90.0 - 2 * half_lat, 90.0
    return (round(min_lon, 3), round(min_lat, 3), round(max_lon, 3), round(max_lat, 3))
