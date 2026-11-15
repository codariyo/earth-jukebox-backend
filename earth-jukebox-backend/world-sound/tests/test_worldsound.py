"""
World Sound otomatik testleri. Ses kartı gerektirmez.

Çalıştırma:   python tests/test_worldsound.py
(pytest kuruluysa:  python -m pytest tests)
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from worldsound import ColorPitchMapper, MapSonifier, note_name   # noqa: E402

SR, BLOCK = 44100, 1024


def solid(rgb, w=320, h=160, alpha=255):
    a = np.zeros((h, w, 4), np.uint8)
    a[..., :3] = rgb
    a[..., 3] = alpha
    return a


def make(img, cols=64, rows=36, speed=40.0):
    s = MapSonifier(SR, BLOCK, rows, cols)
    s.load(img)
    s.set_scan_speed(speed)
    return s


def count_note_ons(son, seconds):
    started = []
    son.add_step_listener(lambda info: started.extend(info.started))
    audio = son.render_offline(seconds)
    return started, audio


# ---------------------------------------------------------------- renk -> nota
def test_red_high_blue_low_and_order():
    m = ColorPitchMapper()
    colors = [("mavi", (0, 0, 255)), ("camgöbeği", (0, 255, 255)), ("yeşil", (0, 255, 0)),
              ("sarı", (255, 255, 0)), ("turuncu", (255, 128, 0)), ("kırmızı", (255, 0, 0))]
    notes = [m.note_for_rgb(*c) for _, c in colors]
    assert notes == sorted(notes) and len(set(notes)) == len(notes), notes
    assert notes[0] == m.available_notes[0], "mavi en pes nota olmalı"
    assert notes[-1] == m.available_notes[-1], "kırmızı en tiz nota olmalı"
    print("  " + "  ".join(f"{n}={note_name(x)}" for (n, _), x in zip(colors, notes)))


def test_nearest_note_in_scale():
    m = ColorPitchMapper()                       # Do majör: diyez yok
    pcs = {int(m.note_for_rgb(r, g, 255 - r)) % 12 for r in range(0, 256, 5) for g in (0, 80)}
    assert pcs <= {0, 2, 4, 5, 7, 9, 11}, pcs


def test_black_white_gray_transparent_are_silent():
    m = ColorPitchMapper()
    assert m.note_for_rgb(0, 0, 0) is None, "siyah"
    assert m.note_for_rgb(12, 10, 14) is None, "neredeyse siyah"
    assert m.note_for_rgb(255, 255, 255) is None, "beyaz"
    assert m.note_for_rgb(128, 128, 128) is None, "gri"
    assert m.note_for_rgb(255, 0, 0, 0) is None, "şeffaf (NASA: ölçüm yok)"


def test_diverging_mode_uses_paleness_as_strength():
    m = ColorPitchMapper()
    strong, pale = (20, 40, 255), (150, 170, 255)          # koyu mavi / soluk mavi
    assert m.note_for_rgb(*strong) == m.note_for_rgb(*pale), "normal kip: yalnız renk tonu"
    m.diverging = True
    lo, mid, hi = m.available_notes[0], m.available_notes[len(m.available_notes) // 2], m.available_notes[-1]
    assert m.note_for_rgb(*strong) < m.note_for_rgb(*pale) <= mid, "ıraksak: soluk mavi ortaya yaklaşır"
    assert mid <= m.note_for_rgb(255, 150, 150) < m.note_for_rgb(255, 20, 20), "soluk kırmızı ortaya yakın"
    assert m.note_for_rgb(0, 0, 255) == lo and m.note_for_rgb(255, 0, 0) == hi, "tam doygun uçlar"
    assert m.note_for_rgb(250, 250, 250) is None, "beyaz (akıntı yok) sessiz kalır"


# ---------------------------------------------------------------- kendiliğinden ses yok
def test_no_map_no_sound():
    s = MapSonifier(SR, BLOCK)
    s.play()
    out = s.render_offline(3.0)
    assert np.max(np.abs(out)) == 0.0
    s.close()


def test_black_map_is_exact_silence():
    for name, img in [("siyah", solid((0, 0, 0))), ("beyaz", solid((255, 255, 255))),
                      ("şeffaf kırmızı", solid((255, 0, 0), alpha=0))]:
        s = make(img)
        s.play()
        started, out = count_note_ons(s, 4.0)
        assert not started and np.max(np.abs(out)) == 0.0, (name, len(started), np.max(np.abs(out)))
        s.close()


def test_paused_is_silent():
    s = make(solid((255, 0, 0)))
    out = s.render_offline(2.0)                  # play() çağrılmadı
    assert np.max(np.abs(out)) == 0.0
    s.close()


# ---------------------------------------------------------------- tekrar filtresi
def test_same_color_plays_once():
    s = make(solid((0, 0, 255)))
    s.sequencer.loop = False
    s.play()
    started, out = count_note_ons(s, 64 / 40.0 + 0.5)
    assert len(started) == 1, f"tek renkli harita 1 nota çalmalı, {len(started)} çaldı"
    assert np.max(np.abs(out)) > 0.01


def test_vertical_dedupe_three_bands():
    img = solid((0, 0, 0))
    img[:53, :, :3] = (255, 0, 0)
    img[53:106, :, :3] = (0, 255, 0)
    img[106:, :, :3] = (0, 0, 255)
    s = make(img)
    s.sequencer.loop = False
    s.play()
    started, _ = count_note_ons(s, 64 / 40.0 + 0.5)
    assert len(started) == 3, started
    info = s.last_step
    assert info.stats.cells == 36 and info.stats.unique == 3 and info.stats.vertical_merged == 33


def test_horizontal_change_retriggers_only_on_color_change():
    img = solid((0, 0, 255))
    img[:, 160:, :3] = (255, 0, 0)
    s = make(img)
    s.sequencer.loop = False
    s.play()
    started, _ = count_note_ons(s, 64 / 40.0 + 0.5)
    assert len(started) == 2, started             # mavi bir kez, kırmızı bir kez


# ---------------------------------------------------------------- görünüm / yakınlaştırma
def test_viewport_changes_music():
    img = solid((255, 0, 0))
    img[:, 160:, :3] = (0, 0, 255)
    s = make(img)
    s.set_viewport(0.0, 0.0, 0.45, 1.0)
    s.rescan(sync=True)
    left = set(np.unique(s.grid.notes))
    s.set_viewport(0.55, 0.0, 1.0, 1.0)
    s.rescan(sync=True)
    right = set(np.unique(s.grid.notes))
    assert left == {s.mapper.available_notes[-1]} and right == {s.mapper.available_notes[0]}, (left, right)


def test_zoom_reveals_small_detail():
    img = solid((0, 0, 255), w=1000, h=500)
    img[248:252, 498:502, :3] = (255, 0, 0)      # 4x4 piksellik kırmızı nokta
    s = make(img)
    red = s.mapper.available_notes[-1]
    assert red not in s.grid.notes, "uzaktan küçük nokta baskın olmamalı"
    s.zoom(40.0, 0.5, 0.5)
    s.rescan(sync=True)
    assert red in s.grid.notes, "yakınlaşınca kırmızı nokta duyulmalı"


def test_zoom_switches_notes_live_while_playing():
    img = solid((255, 0, 0))
    img[:, 160:, :3] = (0, 0, 255)
    s = make(img, speed=10.0)
    s.set_viewport(0.0, 0.0, 0.4, 1.0)
    s.rescan(sync=True)
    s.play()
    s.render_offline(0.5)
    assert set(s.sequencer.sounding) == {s.mapper.available_notes[-1]}
    s.set_viewport(0.6, 0.0, 1.0, 1.0)
    s.rescan(sync=True)
    s.render_offline(0.05)                        # bir sonraki adımı beklemeden geçmeli
    assert set(s.sequencer.sounding) == {s.mapper.available_notes[0]}


def test_pixel_vote_not_color_average():
    img = solid((0, 0, 0), w=64, h=36)
    img[:, :, :3] = (255, 0, 0)
    img[:, ::2, :3] = (0, 0, 255)                 # kırmızı/mavi şerit: ortalaması MOR olurdu
    s = make(img, cols=8, rows=4)
    m = s.mapper
    ok = {int(m.available_notes[0]), int(m.available_notes[-1])}
    assert set(np.unique(s.grid.notes)) <= ok, np.unique(s.grid.notes)


# ---------------------------------------------------------------- enstrümanlar
def test_all_enabled_instruments_play_each_note():
    s = make(solid((0, 255, 0)))
    for k in s.instruments.keys():
        s.set_instrument(k, enabled=k in ("piano", "violin", "bass"))
    s.play()
    s.render_offline(0.3)
    assert len(s.sequencer.sounding) == 1
    keys = sorted(v.inst.key for v in s.engine._voices)
    assert keys == ["bass", "piano", "violin"], keys


# ---------------------------------------------------------------- ekolayzer
def _band_gain(eq, freq):
    t = np.arange(SR) / SR
    x = np.stack([np.sin(2 * np.pi * freq * t)] * 2, axis=1) * 0.3
    y = np.concatenate([eq.process(x[i:i + BLOCK]) for i in range(0, len(x), BLOCK)])
    a = np.sqrt(np.mean(y[SR // 2:] ** 2)) / np.sqrt(np.mean(x[SR // 2:] ** 2))
    return 20 * np.log10(a)


def test_equalizer_bands():
    from worldsound import FiveBandEqualizer
    cases = [("bass", 50), ("low_mid", 300), ("mid", 1000), ("high_mid", 3000), ("treble", 14000)]
    for band, f in cases:
        eq = FiveBandEqualizer(SR)
        flat = _band_gain(eq, f)
        eq = FiveBandEqualizer(SR); eq.set_gain(band, +12)
        up = _band_gain(eq, f)
        eq = FiveBandEqualizer(SR); eq.set_gain(band, -12)
        down = _band_gain(eq, f)
        assert abs(flat) < 0.05 and up > 10.5 and down < -10.5, (band, flat, up, down)
        print(f"  {band:<9} @{f:>5} Hz : 0dB->{flat:+.2f}  +12->{up:+.2f}  -12->{down:+.2f} dB")


def test_equalizer_band_isolation():
    from worldsound import FiveBandEqualizer
    eq = FiveBandEqualizer(SR)
    eq.set_gain("treble", +12)
    assert abs(_band_gain(eq, 100)) < 0.5, "tiz ayarı bası etkilememeli"


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"[GEÇTİ] {name}")
        except Exception as ex:
            failed += 1
            print(f"[KALDI] {name}: {ex!r}")
    print(f"\n{len(tests) - failed}/{len(tests)} test geçti")
    sys.exit(1 if failed else 0)
