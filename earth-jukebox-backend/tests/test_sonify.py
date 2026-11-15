"""Internet gerektirmeyen test:  pytest"""
import io
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import THEMES  # noqa: E402
from app.sonify import sonify_image  # noqa: E402


def make_png(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr.astype(np.uint8), "RGBA").save(buf, format="PNG")
    return buf.getvalue()


def test_brightness_gradient_rises():
    # soldan saga kararan->aydinlanan goruntu: notalar yukselmeli
    w, h = 256, 64
    grad = np.tile(np.linspace(0, 255, w), (h, 1))
    arr = np.stack([grad, grad, grad, np.full_like(grad, 255)], axis=-1)
    out = sonify_image(make_png(arr), THEMES["dunya_renkleri"], steps=16)
    midis = [n["midi"] for n in out["notes"]]
    assert midis == sorted(midis) and midis[-1] > midis[0]
    assert out["stats"]["coverage"] == 1.0


def test_hue_blue_low_red_high():
    w, h = 128, 32
    arr = np.zeros((h, w, 4))
    arr[:, : w // 2] = [0, 0, 255, 255]  # mavi (serin)
    arr[:, w // 2 :] = [255, 0, 0, 255]  # kirmizi (sicak)
    out = sonify_image(make_png(arr), THEMES["sicaklik"], steps=8)
    assert out["notes"][0]["value"] < 0.1 and out["notes"][-1]["value"] > 0.9
    assert "doğusunda" in out["description"]


def test_transparent_is_silent():
    arr = np.zeros((32, 64, 4))
    out = sonify_image(make_png(arr), THEMES["yagis"], steps=8)
    assert out["notes"] == [] and "veri bulunamadı" in out["description"]


def test_white_pixels_are_not_treated_as_maximum():
    """Beyaz bulut/veri-yok alani 'en yuksek deger' sayilmamali."""
    w, h = 128, 32
    arr = np.zeros((h, w, 4))
    arr[:, : w // 2] = [60, 180, 60, 255]   # yesil = gercek veri
    arr[:, w // 2 :] = [255, 255, 255, 255]  # beyaz = bulut
    out = sonify_image(make_png(arr), THEMES["bitki"], steps=8)
    assert out["stats"]["series"][-1] is None       # beyaz taraf sus
    assert out["stats"]["coverage"] == 0.5


def test_normalize_opens_up_the_melody():
    """Solgun goruntu normalize ile daha fazla nota uretmeli."""
    grad = np.tile(np.linspace(110, 175, 256), (64, 1))
    arr = np.stack([grad, grad, grad, np.full_like(grad, 255)], axis=-1)
    flat = sonify_image(make_png(arr), THEMES["dunya_renkleri"], steps=32, normalize=False)
    wide = sonify_image(make_png(arr), THEMES["dunya_renkleri"], steps=32, normalize=True)
    assert wide["stats"]["distinct_notes"] > flat["stats"]["distinct_notes"]


def test_absolute_mode_keeps_dates_comparable():
    """normalize=False iken soguk ve sicak goruntu farkli nota vermeli."""
    def solid(rgb):
        arr = np.zeros((32, 64, 4))
        arr[:] = list(rgb) + [255]
        return sonify_image(make_png(arr), THEMES["kuresel_isinma"], steps=4, normalize=False)
    cold = solid((80, 120, 255))
    hot = solid((255, 120, 80))
    assert hot["notes"][0]["midi"] > cold["notes"][0]["midi"]


def test_description_is_not_self_contradictory():
    arr = np.zeros((32, 64, 4))
    arr[:] = [120, 200, 90, 255]
    d = sonify_image(make_png(arr), THEMES["yagis"], steps=8)["description"]
    assert not ("orta" in d and "(şiddetli yağış)" in d)


def test_compare_makes_tiny_differences_audible():
    """Gercek veri: 1985 vs 2025, fark 0.007. Mutlak olcekte duyulmuyordu."""
    from app.compare import compare_series
    a = [0.943,0.942,0.936,0.933,0.932,0.933,0.934,0.934,0.933,0.933,0.933,0.93,
         0.928,0.928,0.927,0.928,0.927,0.927,0.926,0.926,0.926,0.925,0.931,0.936,
         0.942,0.948,0.951,0.953,0.95,0.949,0.947,0.945]
    b = [0.949,0.952,0.948,0.944,0.944,0.944,0.943,0.942,0.942,0.941,0.939,0.937,
         0.933,0.93,0.931,0.932,0.932,0.931,0.93,0.93,0.929,0.929,0.934,0.939,
         0.949,0.956,0.958,0.96,0.959,0.959,0.958,0.958]
    r = compare_series([(v,1.0) for v in a], [(v,1.0) for v in b],
                       THEMES["kuresel_isinma"], "1985", "2025")
    assert r["steps_higher_in_b"] == 32
    assert r["notes_changed"] > 10          # ortak olcekte fark duyuluyor
    assert "rastlantı değil" in r["verdict"]
    assert "iklim eğilimi değildir" in r["caution"]


def test_compare_flags_inconsistent_direction():
    """Yari artis yari azalis -> 'sonuc cikarma' uyarisi gelmeli."""
    from app.compare import compare_series
    a = [0.5] * 32
    b = [0.6 if i % 2 == 0 else 0.4 for i in range(32)]
    r = compare_series([(v,1.0) for v in a], [(v,1.0) for v in b],
                       THEMES["kuresel_isinma"], "A", "B")
    assert "Tutarlı bir yön yok" in r["verdict"]


# ---------- Renk haritasi (GIBS colormap v1.3 formati) ----------
SAMPLE_CMAP = """<?xml version="1.0" encoding="UTF-8"?>
<ColorMaps>
  <ColorMap title="Surface Air Temperature" units="K">
    <Entries>
      <ColorMapEntry rgb="227,245,255" transparent="false" sourceValue="[0,1)" value="[-INF,200.0)" ref="1"/>
      <ColorMapEntry rgb="50,140,180" transparent="false" sourceValue="[5,6)" value="[240.0,250.0)" ref="6"/>
      <ColorMapEntry rgb="255,200,50" transparent="false" sourceValue="[8,9)" value="[270.0,280.0)" ref="9"/>
      <ColorMapEntry rgb="255,100,50" transparent="false" sourceValue="[10,11)" value="[290.0,300.0)" ref="11"/>
      <ColorMapEntry rgb="180,20,50" transparent="false" sourceValue="[12,13)" value="[310.0,+INF)" ref="13"/>
    </Entries>
  </ColorMap>
  <ColorMap title="No Data">
    <Entries>
      <ColorMapEntry rgb="0,0,0" transparent="true" sourceValue="-9999" nodata="true" label="Missing Data"/>
    </Entries>
  </ColorMap>
</ColorMaps>"""


def _cmap():
    from app.colormap import parse_colormap
    return parse_colormap(SAMPLE_CMAP, "TEST")


def test_colormap_parsing():
    c = _cmap()
    assert len(c.mids) == 5                     # nodata girisi atlandi
    assert c.units == "K"
    assert sorted(c.mids.tolist()) == [200.0, 245.0, 275.0, 295.0, 310.0]  # INF kenarlari
    assert c.bin_width == 10.0


def test_colormap_gives_real_celsius():
    arr = np.zeros((32, 64, 4))
    arr[:, :32] = [50, 140, 180, 255]   # 245 K
    arr[:, 32:] = [255, 100, 50, 255]   # 295 K
    out = sonify_image(make_png(arr), THEMES["kuresel_isinma"], steps=2, cmap=_cmap())
    s = out["stats"]
    assert s["value_source"] == "renk_haritasi" and s["units"] == "°C"
    assert abs(s["series_real"][0] - (245 - 273.15)) < 0.01   # -28.15 °C
    assert abs(s["series_real"][1] - (295 - 273.15)) < 0.01   #  21.85 °C
    assert "°C" in out["description"]


def test_colormap_unknown_color_is_no_data_and_near_color_matches():
    arr = np.zeros((16, 48, 4))
    arr[:, :16] = [255, 0, 255, 255]     # tabloda yok -> veri yok
    arr[:, 16:32] = [253, 101, 52, 255]  # 255,100,50'ye cok yakin -> eslesir
    arr[:, 32:] = [0, 0, 0, 0]           # seffaf -> veri yok
    out = sonify_image(make_png(arr), THEMES["kuresel_isinma"], steps=3, cmap=_cmap())
    sr = out["stats"]["series_real"]
    assert sr[0] is None and sr[2] is None
    assert abs(sr[1] - 21.85) < 0.01


def test_fallback_when_colormap_missing():
    arr = np.zeros((16, 32, 4)); arr[:] = [255, 0, 0, 255]
    out = sonify_image(make_png(arr), THEMES["kuresel_isinma"], steps=2, cmap=None)
    assert out["stats"]["value_source"] == "renk_tonu_tahmini"
    assert "units" not in out["stats"]


def test_compare_reports_real_degrees():
    from app.compare import compare_series
    c = _cmap()
    span = c.vmax - c.vmin   # 110 K
    a = [(0.6, 1.0)] * 8
    b = [(0.6 + 0.8 / span, 1.0)] * 8      # tam +0.8 K
    r = compare_series(a, b, THEMES["kuresel_isinma"], "1985", "2025", cmap=c)
    assert r["units"] == "°C"
    assert abs(r["mean_difference_real"] - 0.8) < 0.01
    assert "hassasiyetinden" in r["verdict"]  # 0.8 < 10 K bin -> uyari
