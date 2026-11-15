"""Iki tarihi karsilastirip FARKI duyulur hale getiren modul.

Problem: 1985 ile 2025 arasindaki isinma, paletin tamamina gore cok kucuk
(0.007). Mutlak olcekte ikisi de ayni notayi calar, fark duyulmaz.

Cozum: Iki goruntuyu AYRI AYRI degil, ORTAK bir araliga gore olcekle.
Ortak aralik iki goruntunun birlesik min-max'i oldugu icin:
  - fark buyur ve duyulur hale gelir,
  - iki goruntu ayni cetveli kullandigi icin karsilastirma BOZULMAZ.
Bu, her goruntuyu kendi araligina geren normalize'den farklidir;
o yontem farki yok ederdi.
"""
import numpy as np

from .colormap import display_diff
from .sonify import describe, real_stats, series_to_notes


def joint_range(raw_a: list, raw_b: list, padding: float = 0.15) -> tuple:
    vals = [v for v, _ in raw_a + raw_b if v is not None]
    if not vals:
        return (0.0, 1.0)
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-6:
        return (lo - 0.01, hi + 0.01)
    pad = (hi - lo) * padding
    return (lo - pad, hi + pad)


def compare_series(
    raw_a: list, raw_b: list, theme: dict, label_a: str, label_b: str, cmap=None
) -> dict:
    rng = joint_range(raw_a, raw_b)

    pairs = [
        (va, vb)
        for (va, _), (vb, _) in zip(raw_a, raw_b)
        if va is not None and vb is not None
    ]
    if not pairs:
        return {
            "comparable_steps": 0,
            "verdict": "İki tarihte de ortak veri bulunamadı, karşılaştırma yapılamıyor.",
        }

    diffs = [vb - va for va, vb in pairs]
    warmer = sum(1 for d in diffs if d > 0)
    mean_a = float(np.mean([va for va, _ in pairs]))
    mean_b = float(np.mean([vb for _, vb in pairs]))
    mean_diff = mean_b - mean_a

    notes_a = series_to_notes(raw_a, theme, rng)
    notes_b = series_to_notes(raw_b, theme, rng)

    # Her VURUS icin notayi ac (notalar birlestirilmis olabilir), sonra karsilastir
    def per_step(notes: list) -> dict:
        out = {}
        for n in notes:
            for s in range(n["step"], n["step"] + n["dur_steps"]):
                out[s] = n["midi"]
        return out

    pa, pb = per_step(notes_a), per_step(notes_b)
    shared = set(pa) & set(pb)
    jump = sum(1 for s in shared if pa[s] != pb[s])

    # Fark serisi: 0 ortada, artis yukari. Kendi araliginda gerilir.
    max_abs = max(abs(d) for d in diffs) or 1e-6
    diff_raw = []
    for (va, ca), (vb, cb) in zip(raw_a, raw_b):
        if va is None or vb is None:
            diff_raw.append((None, 0.0))
        else:
            diff_raw.append((0.5 + (vb - va) / (2 * max_abs), min(ca, cb)))
    notes_diff = series_to_notes(diff_raw, theme)

    n, cooler = len(pairs), len(pairs) - warmer
    ratio = warmer / n
    if ratio >= 0.9:
        verdict = (
            f"{n} şeritten {warmer} tanesinde {label_b} değeri {label_a} tarihinden yüksek. "
            f"Yön tutarlı, bu rastlantı değil."
        )
    elif ratio <= 0.1:
        verdict = (
            f"{n} şeritten {cooler} tanesinde {label_b} değeri {label_a} tarihinden düşük. "
            f"Yön tutarlı."
        )
    else:
        verdict = (
            f"{n} şeritten {warmer} tanesinde artış, {cooler} tanesinde azalış var. "
            f"Tutarlı bir yön yok, tek bir tarih çiftinden sonuç çıkarma."
        )

    # Renk haritasi varsa farki GERCEK birimle ver (ornegin +0.8 °C)
    real = {}
    if cmap is not None:
        span = cmap.vmax - cmap.vmin
        d_real, unit = display_diff(mean_diff * span, cmap.units)
        real = {
            "units": unit,
            "mean_difference_real": round(d_real, 3),
            "precision": round(cmap.bin_width, 3) if cmap.bin_width else None,
        }
        sign = "+" if d_real >= 0 else ""
        verdict += f" Ortalama fark: {sign}{d_real:.2f} {unit}."
        if cmap.bin_width and abs(mean_diff * span) < cmap.bin_width:
            verdict += (
                f" Not: Bu fark renk haritasının hassasiyetinden ({cmap.bin_width:g} {cmap.units}) "
                f"küçük; yön güvenilir, büyüklük kaba bir tahmindir."
            )

    sa, sb = real_stats(raw_a, cmap), real_stats(raw_b, cmap)

    return {
        **real,
        "comparable_steps": len(pairs),
        "steps_higher_in_b": warmer,
        "mean_a": round(mean_a, 4),
        "mean_b": round(mean_b, 4),
        "mean_difference": round(mean_diff, 4),
        "largest_difference": round(max(diffs, key=abs), 4),
        "joint_range": [round(rng[0], 4), round(rng[1], 4)],
        "notes_changed": jump,
        "verdict": verdict,
        "caution": (
            "Bu, iki tarihin renk paletindeki farkıdır; iklim eğilimi değildir. "
            "İki ayrı güne/aya bakmak bir trend kanıtlamaz, çok yıllı ortalama gerekir. "
            "GIBS görüntüleri keşif amaçlıdır, resmî bilimsel ölçüm değildir."
        ),
        "tracks": {
            label_a: {"notes": notes_a, "description": describe(theme, raw_a, {**_stats(raw_a), **sa}),
                      "mean_real": sa.get("mean_real")},
            label_b: {"notes": notes_b, "description": describe(theme, raw_b, {**_stats(raw_b), **sb}),
                      "mean_real": sb.get("mean_real")},
        },
        "difference_track": {
            "notes": notes_diff,
            "description": (
                f"Fark melodisi: orta nota 'değişim yok' demek. Yukarı çıkan notalar "
                f"{label_b} tarihinin daha yüksek olduğu bölgeleri gösterir."
            ),
        },
    }


def _stats(raw: list) -> dict:
    vals = [v for v, c in raw if v is not None and c >= 0.05]
    covs = [c for _, c in raw]
    return {
        "coverage": float(np.mean(covs)) if covs else 0.0,
        "mean_value": float(np.mean(vals)) if vals else None,
    }
