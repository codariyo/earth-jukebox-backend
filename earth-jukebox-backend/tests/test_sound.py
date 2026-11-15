"""Muzik kutusu servisleri (app/sound.py) ve arayuz yardimcilari — internet gerekmez:  pytest"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import sound  # noqa: E402
from app.config import THEMES, WORLD_BBOX  # noqa: E402


def test_weighted_mean_counts_equator_more_than_poles():
    # ust satir (kutba yakin) 0, alt satirlar (ekvatora yakin) 1
    h, w = 90, 10
    values = np.zeros((h, w))
    values[45:] = 1.0  # guney yarim kure (0..-90)
    valid = np.ones((h, w), dtype=bool)
    mean, cov = sound.weighted_mean(values, valid, (-180, -90, 180, 90))
    assert abs(mean - 0.5) < 0.02 and cov == 1.0  # simetrik: esit agirlik

    values = np.zeros((h, w))
    values[30:60] = 1.0  # sadece tropik kusak (+-30) sicak
    mean, _ = sound.weighted_mean(values, valid, (-180, -90, 180, 90))
    assert mean > 0.45  # agirliksiz olsa 0.33 olurdu; tropikler dunyanin yarisi


def test_weighted_mean_ignores_invalid_and_empty():
    values = np.ones((10, 10))
    valid = np.zeros((10, 10), dtype=bool)
    assert sound.weighted_mean(values, valid, WORLD_BBOX) == (None, 0.0)


def test_weighted_strips_shape_and_silence():
    values = np.tile(np.linspace(0, 1, 64), (32, 1))
    valid = np.ones_like(values, dtype=bool)
    valid[:, :16] = False  # bati ceyrek veri yok
    raw = sound.weighted_strips(values, valid, WORLD_BBOX, 8)
    assert len(raw) == 8
    assert raw[0][0] is None and raw[1][0] is None
    vals = [v for v, _ in raw if v is not None]
    assert vals == sorted(vals)  # batidan doguya artan


def test_clamp_bbox_stays_inside_world():
    assert sound.clamp_bbox_around(39, 35) == (15.0, 27.0, 55.0, 51.0)
    b = sound.clamp_bbox_around(85, 175)
    assert b[2] <= 180 and b[3] <= 90 and b[2] - b[0] == 40 and b[3] - b[1] == 24
    b = sound.clamp_bbox_around(-89, -179)
    assert b[0] >= -180 and b[1] >= -90


def test_timeline_text_reports_real_difference_and_trend():
    rows = [{"date": f"{y}-07-01", "value": 0.5 + i * 0.01, "real": 15.9 + i * 0.1, "units": "°C"}
            for i, y in enumerate(range(1985, 2026, 5))]
    text = sound._timeline_text(THEMES["kuresel_isinma"], rows, None)
    assert "1985-07-01" in text and "2025-07-01" in text
    assert "+0.80 °C" in text  # 8 adim * 0.1
    assert "on yılda" in text


# test_speakable_reads_turkish kaldırıldı (2026-11-15): eski NiceGUI arayüzü (frontend/ui.py) silindi.
