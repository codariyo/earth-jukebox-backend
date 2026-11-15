"""
Gerçek kayıtla çalan enstrümanların (sampler.py) ve ekolayzerin iç kontrolleri. Ses kartı gerektirmez.

    - PERDE: her enstrüman, aralığındaki notaları doğru frekansta çalar (YIN ile ölçülür, ±20 sent)
    - ARALIK: harita notası enstrümanın gerçek aralığı dışındaysa oktav kaydırılarak içeri alınır
    - DÜZEY: bir enstrümanın notaları ve enstrümanlar birbirine yakın gürlükte (±6 dB)
    - SÜREKLİLİK: flüt/keman uzun notada kesilmez, döngüde atlama/tıkırtı olmaz
    - SÖNÜM: renk bitince (release) ses enstrümanın süresinde susar
    - KARIŞIM: 5 enstrüman + EQ ±12 dB birlikte çalarken taşma (clipping) olmaz
    - EKOLAYZER: 0,1 dB hassasiyet, yumuşak geçiş
"""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from worldsound import MapSonifier, sampler               # noqa: E402
from worldsound.color_pitch import midi_to_hz             # noqa: E402
from worldsound.equalizer import FiveBandEqualizer      # noqa: E402

SR = 44100
KEYS = ("piano", "violin", "flute", "aguitar", "eguitar")
CLASSES = {
    "piano": sampler.SampledPiano, "violin": sampler.SampledViolin, "flute": sampler.SampledFlute,
    "aguitar": sampler.SampledAcousticGuitar, "eguitar": sampler.SampledElectricGuitar,
}

pytestmark = pytest.mark.skipif(not sampler.available(), reason="kayıtlar ya da soundfile yok")


def render_note(key, midi, seconds, release_at=None, velocity=0.8):
    inst = CLASSES[key](enabled=True)
    v = inst.new_voice(midi, velocity, SR)
    out, n, block = [], int(seconds * SR), 1024
    done = 0
    while done < n:
        if release_at is not None and done >= release_at * SR:
            v.release()
            release_at = None
        out.append(v.render(block))
        done += block
    return np.concatenate(out)[:n], v


def f0_fft(x, f_expect):
    """Temel harmoniğin frekansı: yüksek çözünürlüklü FFT tepe noktası + parabolik ara değerleme.
    (Otokorelasyon/YIN piyanonun inharmonik üst harmoniklerinden etkilenip +30 sent yanılıyordu.)
    Beklenenin ±%6'sı (bir yarım tondan az) aranır; yanlış notada tepe bu bandın kenarına düşer ve
    sapma büyük çıkar."""
    seg = x.astype(np.float64) * np.hanning(len(x))
    n = 1 << 18
    spec = np.abs(np.fft.rfft(seg, n))
    freqs = np.fft.rfftfreq(n, 1 / SR)
    m = (freqs > f_expect * 0.94) & (freqs < f_expect * 1.06)
    i = int(np.argmax(np.where(m, spec, 0)))
    a, b, c = (np.log(spec[j] + 1e-12) for j in (i - 1, i, i + 1))
    return (i + 0.5 * (a - c) / (a - 2 * b + c)) * SR / n


def cents(f, ref):
    return 1200 * np.log2(f / ref)


# ---------------------------------------------------------------- perde
@pytest.mark.parametrize("key", KEYS)
def test_pitch_is_correct_across_range(key):
    bank = sampler.load_bank(key)
    errors = []
    sustained = bank.sustained
    for midi in range(bank.low, bank.high + 1):           # aralıktaki HER nota (kökler + kaydırılanlar)
        x, v = render_note(key, midi, 1.6 if sustained else 1.1)
        seg = x[int(0.3 * SR): int(1.5 * SR)] if sustained else x[int(0.08 * SR): int(1.0 * SR)]
        f = f0_fft(seg, float(midi_to_hz(midi)))
        errors.append((midi, round(float(cents(f, float(midi_to_hz(midi)))), 1)))
    bad = [e for e in errors if abs(e[1]) > 8]
    assert not bad, f"{key}: 8 sentten fazla sapan notalar {bad}"


@pytest.mark.parametrize("key,map_note,expect", [
    ("flute", 36, 60), ("flute", 48, 60), ("flute", 95, 95),
    ("violin", 36, 60), ("aguitar", 95, 83), ("eguitar", 95, 83), ("piano", 36, 36), ("piano", 95, 95),
])
def test_out_of_range_notes_fold_by_octave(key, map_note, expect):
    inst = CLASSES[key](enabled=True)
    v = inst.new_voice(map_note, 0.8, SR)
    assert v.midi == expect and v.midi % 12 == map_note % 12 and v.data_midi == map_note


# ---------------------------------------------------------------- düzey
def rms_db(x):
    return 20 * np.log10(np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-12)


def test_levels_are_balanced():
    per_inst = {}
    for key in KEYS:
        bank = sampler.load_bank(key)
        lv = []
        for midi in range(bank.low, bank.high + 1, 6):
            x, _ = render_note(key, midi, 0.5)
            lv.append(rms_db(x[: int(0.4 * SR)]))
        assert max(lv) - min(lv) < 9.0, (key, [round(v, 1) for v in lv])
        per_inst[key] = float(np.median(lv))
    spread = max(per_inst.values()) - min(per_inst.values())
    assert spread < 6.0, {k: round(v, 1) for k, v in per_inst.items()}


# ---------------------------------------------------------------- süreklilik ve sönüm
@pytest.mark.parametrize("key", ["flute", "violin"])
def test_sustained_instruments_hold_without_clicks(key):
    x, v = render_note(key, 72, 6.0)
    assert not v.finished
    win = int(0.05 * SR)
    env = np.array([rms_db(x[i:i + win]) for i in range(int(0.6 * SR), len(x) - win, win)])
    assert env.min() > -40, f"{key}: uzun nota söndü ({env.min():.1f} dB)"
    assert env.max() - env.min() < 9.0, f"{key}: döngüde düzey sıçraması {env.max() - env.min():.1f} dB"
    # tıkırtı: örnekten örneğe sıçrama, notanın kendi değişim hızının çok üstünde olmamalı
    jump = np.abs(np.diff(x[int(0.6 * SR):]))
    assert jump.max() < 8 * np.percentile(jump, 99.5), f"{key}: döngüde tıkırtı"


@pytest.mark.parametrize("key", KEYS)
def test_release_silences_note(key):
    x, v = render_note(key, 67, 2.0, release_at=0.5)
    assert v.finished, f"{key}: release sonrası nota bitmedi"
    tail = x[int((0.5 + CLASSES[key].release + 0.05) * SR):]
    assert np.max(np.abs(tail)) == 0.0


@pytest.mark.parametrize("key", ["piano", "aguitar", "eguitar"])
def test_plucked_instruments_decay_naturally(key):
    x, v = render_note(key, 60, 4.0)
    assert rms_db(x[int(0.05 * SR): int(0.3 * SR)]) - rms_db(x[int(2.5 * SR): int(2.8 * SR)]) > 10


# ---------------------------------------------------------------- karışım + ekolayzer
def rainbow(w=640, h=360):
    hue = np.linspace(0, 1, w, endpoint=False)
    import colorsys
    row = np.array([colorsys.hsv_to_rgb(hh, 1, 1) for hh in hue]) * 255
    img = np.zeros((h, w, 4), np.uint8)
    img[..., :3] = row[None, :, :].astype(np.uint8)
    img[..., 3] = 255
    for i in range(0, h, 40):                   # dikey de farklı renkler: çok nota
        img[i:i + 20, :, :3] = np.roll(img[i:i + 20, :, :3], w // 3, axis=1)
    return img


def test_full_mix_all_instruments_eq_boost_no_clipping():
    s = MapSonifier(SR, 1024, 36, 64)
    s.load(rainbow())
    s.set_scan_speed(10)
    s.set_max_voices(10)
    for k in s.instruments.keys():
        s.set_instrument(k, enabled=k in KEYS, volume=1.0)
    for band in ("bass", "low_mid", "mid", "high_mid", "treble"):
        s.set_eq(band, +12)
    s.play()
    out = s.render_offline(6.0)
    assert np.all(np.isfinite(out))
    assert np.max(np.abs(out)) <= 0.98 + 1e-6, "sınırlayıcı tavanı aşıldı"
    assert rms_db(out) > -30, "karışım duyulamayacak kadar kısık"
    s.close()


def test_equalizer_precision_and_smooth_ramp():
    eq = FiveBandEqualizer(SR)
    eq.set_gain("mid", 2.47)
    assert eq.gain("mid") == pytest.approx(2.5)
    eq.set_gain("mid", 12.0)
    t = np.arange(4096) / SR
    x = np.stack([np.sin(2 * np.pi * 1000 * t)] * 2, axis=1) * 0.1
    first = eq.process(x[:1024])
    # ilk blokta kazanç hedefin (12 dB) çok altında: ani sıçrama yok
    assert rms_db(first[512:]) - rms_db(x[512:1024]) < 3.0
    for _ in range(20):
        y = eq.process(x[:1024])
    assert rms_db(y[512:]) - rms_db(x[512:1024]) > 11.0


def test_duck_lowers_music_smoothly():
    s = MapSonifier(SR, 1024, 36, 64)
    s.load(rainbow())
    s.set_scan_speed(10)
    s.play()
    normal = s.render_offline(1.0)
    s.engine.set_duck(0.25)
    ducked = s.render_offline(1.0)
    assert rms_db(ducked[int(0.3 * SR):]) < rms_db(normal[int(0.3 * SR):]) - 8
    s.close()
