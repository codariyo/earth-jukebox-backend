"""
Enstrümanlar ve sesler (voice).

Her Instrument bir tını tanımıdır (harmonik yapısı, zarf, vibrato...). Her
nota açık olan TÜM enstrümanlarda AYNI ANDA çalınır: bir nota geldiğinde
etkin her enstrüman kendi Voice nesnesini başlatır. Böylece aynı harita
notası piyano + keman + bas ile birlikte duyulabilir.

Sentez: bant sınırlı dalga tablosu (wavetable). Her nota için tablo yalnız
Nyquist sınırının altındaki harmoniklerle kurulur, tiz notalarda bozulma
(aliasing) olmaz. Sesler gerçek zamanlı üretilir: nota renk sürdükçe çalar,
renk bitince "release" ile söner.

Yeni enstrüman eklemek: Instrument'tan türetip sınıf niteliklerini ayarlayın
ve InstrumentRack.default()'a ekleyin.
"""

import numpy as np

from .color_pitch import midi_to_hz

TABLE_SIZE = 2048


class Instrument:
    key = "base"
    label = "Enstrüman"
    harmonics = (1.0,)
    attack, decay, sustain, release = 0.01, 0.2, 0.8, 0.2
    pluck = 0.0                 # tutulurken bile sönme hızı (1/sn); telli/vurmalılar
    vibrato_depth = 0.0         # frekansın oranı
    vibrato_rate = 5.0
    unison_cents = (0.0,)       # birden fazla hafif kaydırılmış osilatör (koro etkisi)
    noise = 0.0                 # nefes / perde gürültüsü
    drive = 0.0                 # >0: tanh distorsiyon
    gain = 1.0
    pan = 0.0                   # -1 sol, +1 sağ

    def __init__(self, enabled: bool = False, volume: float = 0.75, octave: int = 0):
        self.enabled = enabled
        self.volume = float(volume)
        self.octave = int(octave)   # harita notasını bu kadar oktav kaydır (ör. bas -1)
        self._tables = {}

    def table(self, midi: int, sr: int) -> np.ndarray:
        """Bu nota için bant sınırlı tek periyotluk dalga (önbellekli)."""
        t = self._tables.get(midi)
        if t is not None:
            return t
        f0 = float(midi_to_hz(midi))
        ph = np.arange(TABLE_SIZE + 1, dtype=np.float64) / TABLE_SIZE * 2.0 * np.pi
        w = np.zeros(TABLE_SIZE + 1)
        for k, a in enumerate(self.harmonics, start=1):
            if f0 * k >= sr * 0.45:
                break
            w += a * np.sin(k * ph)
        if self.drive > 0:
            w = np.tanh(w * self.drive)
        peak = np.max(np.abs(w))
        t = (w / peak if peak > 0 else w).astype(np.float32)
        self._tables[midi] = t
        return t

    def new_voice(self, midi: int, velocity: float, sr: int, offset: int = 0) -> "Voice":
        """midi: haritadan gelen nota. Enstrüman kendi oktav kaydırmasını uygular."""
        played = int(np.clip(midi + 12 * self.octave, 12, 120))
        return Voice(self, played, velocity, sr, offset, data_midi=int(midi))


class Voice:
    """Bir enstrümanın çaldığı tek nota."""

    _rng = np.random.default_rng(7)

    def __init__(self, instrument: Instrument, midi: int, velocity: float, sr: int,
                 offset: int = 0, data_midi: int = None):
        self.inst = instrument
        self.data_midi = midi if data_midi is None else data_midi   # haritadaki nota (kapatmak için)
        self.midi = midi
        self.velocity = float(velocity)
        self.sr = sr
        self.table = instrument.table(midi, sr)
        f0 = float(midi_to_hz(midi))
        self.incs = [f0 * (2.0 ** (c / 1200.0)) * TABLE_SIZE / sr for c in instrument.unison_cents]
        self.phases = [float(self._rng.uniform(0, TABLE_SIZE)) for _ in self.incs]
        self.samples = 0
        self.start_offset = int(offset)
        self.released_at = None      # saniye
        self.finished = False

    def release(self, offset: int = 0):
        if self.released_at is None:
            self.released_at = (self.samples + max(0, offset - self.start_offset)) / self.sr

    def render(self, frames: int) -> np.ndarray:
        out = np.zeros(frames, dtype=np.float32)
        off = min(self.start_offset, frames)
        m = frames - off
        self.start_offset = 0
        if m <= 0 or self.finished:
            return out

        inst = self.inst
        t = (self.samples + np.arange(m)) / self.sr

        # --- osilatör(ler) ---
        if inst.vibrato_depth > 0:
            vib = 1.0 + inst.vibrato_depth * np.sin(2 * np.pi * inst.vibrato_rate * t) * np.minimum(t / 0.35, 1.0)
        else:
            vib = None
        wave = np.zeros(m, dtype=np.float64)
        for i, inc in enumerate(self.incs):
            if vib is None:
                ph = self.phases[i] + inc * np.arange(m)
                nxt = self.phases[i] + inc * m
            else:
                steps = inc * vib
                ph = self.phases[i] + np.cumsum(steps) - steps
                nxt = ph[-1] + steps[-1]
            self.phases[i] = nxt % TABLE_SIZE
            idx = np.mod(ph, TABLE_SIZE)
            i0 = idx.astype(np.int64)
            frac = idx - i0
            wave += self.table[i0] * (1.0 - frac) + self.table[i0 + 1] * frac
        wave /= len(self.incs)

        # --- zarf (ADSR) ---
        a, d, s = inst.attack, inst.decay, inst.sustain
        env = np.where(t < a, t / a, s + (1.0 - s) * np.exp(-(t - a) / max(d, 1e-3)))
        if inst.pluck > 0:
            env = env * np.exp(-inst.pluck * t)
        if self.released_at is not None:
            tr = t - self.released_at
            env = env * np.where(tr > 0, np.exp(-np.maximum(tr, 0) * 6.9 / max(inst.release, 1e-3)), 1.0)
            if tr[-1] >= inst.release:
                self.finished = True
        elif inst.pluck > 0 and env[-1] < 1e-4:
            self.finished = True

        if inst.noise > 0:
            wave = wave + self._rng.normal(0.0, inst.noise, m)

        out[off:] = (wave * env * (self.velocity * 0.32)).astype(np.float32)
        self.samples += m
        return out


# ===========================================================================
class Piano(Instrument):
    key, label = "piano", "Piyano"
    harmonics = (1.0, 0.5, 0.3, 0.18, 0.1, 0.06, 0.04, 0.02)
    attack, decay, sustain, release = 0.004, 0.25, 0.45, 0.35
    pluck = 1.1
    gain, pan = 1.0, 0.0


class Violin(Instrument):
    key, label = "violin", "Keman"
    harmonics = tuple(1.0 / k for k in range(1, 15))
    attack, decay, sustain, release = 0.09, 0.2, 0.85, 0.30
    vibrato_depth, vibrato_rate = 0.005, 5.5
    gain, pan = 0.75, -0.25


class Flute(Instrument):
    key, label = "flute", "Yan Flüt"
    harmonics = (1.0, 0.12, 0.05, 0.02)
    attack, decay, sustain, release = 0.06, 0.1, 0.9, 0.18
    vibrato_depth, vibrato_rate = 0.003, 4.8
    noise = 0.035
    gain, pan = 0.85, 0.3


class AcousticGuitar(Instrument):
    key, label = "aguitar", "Akustik Gitar"
    harmonics = (1.0, 0.7, 0.45, 0.3, 0.2, 0.12, 0.08, 0.05, 0.03)
    attack, decay, sustain, release = 0.003, 0.15, 0.4, 0.30
    pluck = 2.0
    gain, pan = 1.0, -0.45


class ElectricGuitar(Instrument):
    key, label = "eguitar", "Elektro Gitar"
    harmonics = (1.0, 0.6, 0.5, 0.35, 0.3, 0.2, 0.15, 0.1)
    attack, decay, sustain, release = 0.006, 0.2, 0.7, 0.25
    pluck = 0.25
    drive = 2.2
    gain, pan = 0.55, 0.45


class Bass(Instrument):
    key, label = "bass", "Bas"
    harmonics = (1.0, 0.45, 0.2, 0.08, 0.03)
    attack, decay, sustain, release = 0.006, 0.3, 0.6, 0.20
    pluck = 0.6
    gain, pan = 1.1, 0.0


class Pad(Instrument):
    key, label = "pad", "Synth Pad"
    harmonics = (1.0, 0.5, 0.33, 0.25, 0.2, 0.16)
    attack, decay, sustain, release = 0.5, 0.6, 0.85, 1.0
    unison_cents = (-8.0, 0.0, 8.0)
    gain, pan = 0.5, 0.0


class InstrumentRack:
    """Enstrüman koleksiyonu. Sıra arayüzdeki sırayı belirler."""

    def __init__(self, instruments):
        self._items = {i.key: i for i in instruments}

    @classmethod
    def default(cls) -> "InstrumentRack":
        """Piyano, keman, flüt ve gitarlar GERÇEK KAYITLARLA çalar (sampler.py). Kayıtlar ya da
        çözücüleri (soundfile) yoksa aynı anahtarlarla sentez enstrümanlarına düşülür.
        Bas ve Synth Pad sentezdir (Eratone arayüzünde yoklar)."""
        from . import sampler
        if sampler.available():
            try:
                lead = [
                    sampler.SampledPiano(enabled=True),
                    sampler.SampledViolin(enabled=True),
                    sampler.SampledFlute(),
                    sampler.SampledAcousticGuitar(),
                    sampler.SampledElectricGuitar(),
                ]
            except Exception as ex:          # bozuk/eksik kayıt: sentezle devam
                print("Enstrüman kayıtları yüklenemedi, sentez kullanılıyor:", repr(ex))
                lead = None
        else:
            lead = None
        if lead is None:
            lead = [Piano(enabled=True), Violin(enabled=True), Flute(), AcousticGuitar(), ElectricGuitar()]
        return cls(lead + [Bass(octave=-1), Pad()])

    def __iter__(self):
        return iter(self._items.values())

    def __getitem__(self, key) -> Instrument:
        return self._items[key]

    def keys(self):
        return list(self._items.keys())

    def enabled(self):
        return [i for i in self._items.values() if i.enabled]
