"""Goruntuyu notalara ceviren kisim (seslendirme / sonification).

Fikir: goruntuyu soldan saga (batidan doguya) tariyoruz. Goruntuyu `steps`
tane dikey seride boluyoruz; her serit bir vurus (step) oluyor.
  - seritteki ortalama deger (renk tonu veya parlaklik)  -> notanin perdesi
  - seritte veri olan piksel orani (kapsama)            -> notanin siddeti
  - veri yoksa                                           -> sus (nota yok)
Perdeleri bir muzik olcegine oturtuyoruz ki gurultu degil melodi ciksin.
"""
import io

import numpy as np
from PIL import Image

from .colormap import Colormap, display, values_from_colormap

SCALES = {
    "major_pentatonic": [0, 2, 4, 7, 9],
    "minor_pentatonic": [0, 3, 5, 7, 10],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "major": [0, 2, 4, 5, 7, 9, 11],
    "whole_tone": [0, 2, 4, 6, 8, 10],  # tedirgin, anomali temasi icin
}
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
MIN_COVERAGE = 0.05  # seridin %5'inden azinda veri varsa sus

# Renk tonu (hue) solgun piksellerde anlamsizdir: beyaz, gri ve siyahin
# "renk tonu" yoktur, HSV bunlara rastgele bir ton verir (genelde 0 = kirmizi).
# Bu yuzden bulut, veri-yok alani ve beyaz zemin "en yuksek deger" sanilir.
# Asagidaki esiklerin altindaki piksel hue temalarinda GECERSIZ sayilir.
MIN_SATURATION = 0.18
MIN_BRIGHTNESS = 0.10


def midi_to_name(midi: int) -> str:
    return f"{NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


def pixel_values(img: Image.Image, feature: str) -> tuple[np.ndarray, np.ndarray]:
    """Her piksel icin 0-1 arasi deger ve 'veri var mi' maskesi dondurur."""
    rgba = np.asarray(img.convert("RGBA"), dtype=np.float32)
    valid = rgba[..., 3] > 0  # seffaf piksel = veri yok

    if feature == "brightness":
        r, g, b = rgba[..., 0], rgba[..., 1], rgba[..., 2]
        values = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
    elif feature == "hue":
        hsv = np.asarray(img.convert("RGB").convert("HSV"), dtype=np.float32) / 255.0
        hue = hsv[..., 0] * 360.0
        hue = np.where(hue > 300, hue - 360, hue)  # mor-kirmiziyi kirmiziya yakin say
        values = np.clip((240.0 - hue) / 240.0, 0.0, 1.0)  # mavi(240)=0, kirmizi(0)=1
        # Solgun pikselleri gecersiz say (bulut, beyaz zemin, veri-yok alanlari)
        valid &= (hsv[..., 1] >= MIN_SATURATION) & (hsv[..., 2] >= MIN_BRIGHTNESS)
    else:
        raise ValueError(f"Bilinmeyen feature: {feature}")
    return values, valid


def stretch(values: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Goruntunun kendi deger araligini 0-1'e yayar (kontrast germe).

    DIKKAT: Bu islem goruntuleri KARSILASTIRILAMAZ hale getirir. 1980 ve 2026
    goruntuleri ayri ayri gerilirse ikisi de ayni araliga oturur ve isinma
    DUYULMAZ. Tarihler arasi karsilastirma yapacaksan normalize=False kullan.
    """
    if not valid.any():
        return values
    lo, hi = np.percentile(values[valid], [5, 95])
    if hi - lo < 1e-6:
        return values
    return np.clip((values - lo) / (hi - lo), 0.0, 1.0)


def value_to_midi(value: float, scale: str, octave: int, span_octaves: int = 2) -> int:
    degrees = SCALES[scale]
    n = len(degrees) * span_octaves
    idx = int(round(value * (n - 1)))
    return 12 * (octave + 1) + 12 * (idx // len(degrees)) + degrees[idx % len(degrees)]


def extract(img: Image.Image, theme: dict, cmap: Colormap | None) -> tuple:
    """Goruntuden (0-1 mutlak deger, gecerli maske, kaynak adi) cikarir.

    Oncelik: renk haritasi (gercek veri). Renk haritasi yoksa ya da
    indirilemezse renk tonu / parlaklik tahminine geri duser.
    """
    feature = theme["feature"]
    if feature == "colormap":
        if cmap is not None:
            rgba = np.asarray(img.convert("RGBA"))
            values, valid = values_from_colormap(rgba, cmap)
            return values, valid, "renk_haritasi"
        feature = theme.get("fallback_feature", "hue")
    values, valid = pixel_values(img, feature)
    return values, valid, "parlaklik" if feature == "brightness" else "renk_tonu_tahmini"


def _strips(values: np.ndarray, valid: np.ndarray, steps: int) -> list:
    out = []
    for cols in np.array_split(np.arange(values.shape[1]), steps):
        v, m = values[:, cols], valid[:, cols]
        coverage = float(m.mean()) if m.size else 0.0
        out.append((float(v[m].mean()) if m.any() else None, coverage))
    return out


def strip_series(png_bytes: bytes, theme: dict, steps: int = 32, cmap: Colormap | None = None) -> list:
    """Her seridin MUTLAK (0-1) degeri ve kapsamasi. Karsilastirma icin kullanilir."""
    img = Image.open(io.BytesIO(png_bytes))
    values, valid, _ = extract(img, theme, cmap)
    return _strips(values, valid, steps)


def series_to_notes(raw: list, theme: dict, value_range: tuple | None = None) -> list:
    """Serit degerlerini notalara cevirir. value_range verilirse o aralik 0-1'e yayilir."""
    lo, hi = value_range if value_range else (0.0, 1.0)
    span = max(hi - lo, 1e-6)
    notes = []
    for step, (v, cov) in enumerate(raw):
        if v is None or cov < MIN_COVERAGE:
            continue
        scaled = float(np.clip((v - lo) / span, 0.0, 1.0))
        midi = value_to_midi(scaled, theme["scale"], theme["octave"])
        velocity = round(0.3 + 0.7 * cov, 2)
        if notes and notes[-1]["midi"] == midi and notes[-1]["step"] + notes[-1]["dur_steps"] == step:
            notes[-1]["dur_steps"] += 1
            continue
        notes.append(
            {
                "step": step,
                "dur_steps": 1,
                "midi": midi,
                "note": midi_to_name(midi),
                "velocity": velocity,
                "value": round(v, 4),
            }
        )
    return notes


def real_stats(raw_abs: list, cmap: Colormap | None) -> dict:
    """Serit degerlerini gercek birime cevirir (renk haritasi varsa)."""
    if cmap is None:
        return {}
    series, shown_units = [], cmap.units
    for v, c in raw_abs:
        if v is None or c < MIN_COVERAGE:
            series.append(None)
            continue
        val, shown_units = display(cmap.to_real(v), cmap.units)
        series.append(round(val, 2))
    vals = [s for s in series if s is not None]
    return {
        "units": shown_units,
        "mean_real": round(float(np.mean(vals)), 2) if vals else None,
        "min_real": round(min(vals), 2) if vals else None,
        "max_real": round(max(vals), 2) if vals else None,
        "series_real": series,
        "colormap_title": cmap.title,
        # Renk haritasindaki bir rengin kapsadigi aralik: olcumun hassasiyeti budur
        "precision": round(cmap.bin_width, 3) if cmap.bin_width else None,
    }


def sonify_image(
    png_bytes: bytes,
    theme: dict,
    steps: int = 32,
    normalize: bool | None = None,
    cmap: Colormap | None = None,
) -> dict:
    img = Image.open(io.BytesIO(png_bytes))
    values, valid, source = extract(img, theme, cmap)
    raw_abs = _strips(values, valid, steps)  # gercek deger icin her zaman mutlak seri

    if normalize is None:
        normalize = theme.get("normalize", False)
    raw = _strips(stretch(values, valid), valid, steps) if normalize else raw_abs

    notes = series_to_notes(raw, theme)
    for n in notes:  # nota icindeki "value" alani normalize edilse de mutlak kalsin
        n["value"] = round(raw_abs[n["step"]][0], 4)

    valid_vals = [v for v, c in raw_abs if v is not None and c >= MIN_COVERAGE]
    stats = {
        "coverage": round(float(valid.mean()), 3),
        "mean_value": round(float(np.mean(valid_vals)), 4) if valid_vals else None,
        "normalized": bool(normalize),
        "value_source": source,
        "distinct_notes": len({n["midi"] for n in notes}),
        "series": [None if v is None else round(v, 4) for v, _ in raw_abs],
        **real_stats(raw_abs, cmap if source == "renk_haritasi" else None),
    }
    return {"steps": steps, "notes": notes, "stats": stats, "description": describe(theme, raw_abs, stats)}


def decimals_for(lo: float, hi: float) -> int:
    """Kucuk degerler (orn. akinti 0.03 m/s) '-0.0' gibi anlamsiz gorunmesin."""
    span = max(abs(hi - lo), abs(lo), abs(hi))
    return 1 if span >= 2 else 2 if span >= 0.2 else 3


def describe(theme: dict, raw: list, stats: dict) -> str:
    """Ekran okuyucu icin Turkce aciklama (erisilebilirlik bu yarismanin ana temasi)."""
    title = theme["title"]
    if stats["mean_value"] is None:
        return f"{title}: Bu bölge ve tarih için veri bulunamadı, bu enstrüman sessiz kalacak."

    # Seviye ve kelime AYNI esige gore secilir
    mean = stats["mean_value"]
    if mean < 0.33:
        level, word = "düşük", theme["low_word"]
    elif mean < 0.66:
        level, word = "orta", f"{theme['low_word']} ile {theme['high_word']} arası"
    else:
        level, word = "yüksek", theme["high_word"]

    thirds = np.array_split(np.arange(len(raw)), 3)
    names = ["batısında", "ortasında", "doğusunda"]
    third_means = []
    for t in thirds:
        vals = [raw[i][0] for i in t if raw[i][0] is not None]
        third_means.append(np.mean(vals) if vals else -1)
    peak = names[int(np.argmax(third_means))]

    real = ""
    if stats.get("mean_real") is not None:
        u = stats["units"]
        d = decimals_for(stats["min_real"], stats["max_real"])
        real = (
            f" Ortalama {stats['mean_real']:.{d}f} {u}; en düşük {stats['min_real']:.{d}f}, "
            f"en yüksek {stats['max_real']:.{d}f} {u}."
        )

    cover = round(stats["coverage"] * 100)
    sparse = " Bölgenin çoğunda bu veri yok, o yüzden parça seyrek çalıyor." if cover < 30 else ""
    return (
        f"{title}: Görüntünün %{cover} kadarında veri var. "
        f"Genel seviye {level} ({word}).{real} En yüksek değerler bölgenin {peak}.{sparse} "
        f"Melodi haritayı batıdan doğuya tarayarak çalınır; nota yükseldikçe değer artar."
    )
