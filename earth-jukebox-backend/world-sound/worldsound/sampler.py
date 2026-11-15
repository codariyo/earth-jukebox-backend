"""
Gerçek enstrüman kayıtlarıyla çalan enstrümanlar (örnekleyici / sampler).

instruments.py'deki sentez enstrümanlarıyla AYNI arayüzü kullanır (Instrument.new_voice → Voice:
render / release / finished / released_at / samples / data_midi), böylece motor, sıralayıcı ve
ekolayzer hiç değişmeden çalışır.

Kayıtlar: samples/<anahtar>/m<NNN>.ogg + samples/manifest.json
(scripts/build_instrument_samples.py üretir; kaynak FluidR3_GM, CC BY 3.0 — samples/KAYNAK.txt).

Nasıl çalar
    - Her enstrümanda 3 yarım tonda bir kayıt var; istenen notaya EN YAKIN kayıt seçilir ve en çok
      ±1 yarım ton (keman Si♭6 civarında ±2) hızlandırılıp yavaşlatılarak tam perdeye getirilir.
    - Akort: her kaydın ölçülmüş sapması (manifest tune_cents) çalarken düzeltilir; piyano, keman,
      flüt ve gitarlar aynı notayı birlikte çaldığında aynı akorttadır.
    - Gerçek ses aralığı: harita notası enstrümanın çalabileceği aralığın dışındaysa OKTAV kaydırılarak
      içeri alınır (ör. flüt Do4..Do7). Notanın adı (armoni) değişmez.
    - Piyano ve gitarlar doğal olarak söner. Flüt ve keman, renk sürdükçe çalar: kaydın sabit
      bölümü yumuşak geçişli döngüyle (loop) tekrar eder.
    - Renk bitince (release) notanın sesi enstrümana uygun sürede kısılır.
"""

import json
import threading
from pathlib import Path

import numpy as np

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"

_banks = {}
_bank_lock = threading.Lock()


class SampleBank:
    """Bir enstrümanın çözülmüş kayıtları (bellekte, süreç boyunca tek kopya)."""

    def __init__(self, key: str, entry: dict, sr: int):
        import soundfile as sf
        self.key = key
        self.sr = int(sr)
        self.low, self.high = int(entry["low"]), int(entry["high"])
        self.sustained = bool(entry["sustained"])
        self.roots = np.array(sorted(int(m) for m in entry["notes"]), dtype=np.int64)
        self.data, self.loops, self.tunes = {}, {}, {}
        for m, info in entry["notes"].items():
            # kaydın ölçülmüş akort sapması (sent); çalarken ters yönde düzeltilir
            self.tunes[int(m)] = float(info.get("tune_cents", 0.0))
            x, file_sr = sf.read(SAMPLES_DIR / key / info["file"], dtype="float32")
            if x.ndim > 1:
                x = x.mean(axis=1)
            if file_sr != self.sr:
                raise ValueError(f"{key}: kayıt {file_sr} Hz, beklenen {self.sr} Hz")
            # okuma sırasında bir sonraki örneğe bakıldığı için 1 örneklik sessiz pay
            self.data[int(m)] = np.concatenate([x, np.zeros(2, np.float32)])
            self.loops[int(m)] = tuple(info["loop"]) if info.get("loop") else None

    def nearest_root(self, midi: int) -> int:
        i = int(np.argmin(np.abs(self.roots - midi)))
        return int(self.roots[i])

    def fold(self, midi: int) -> int:
        """Notayı oktav kaydırarak enstrümanın gerçek aralığına alır."""
        while midi < self.low:
            midi += 12
        while midi > self.high:
            midi -= 12
        return midi


def available() -> bool:
    """Kayıtlar ve çözücü (soundfile) hazır mı? Değilse sentez enstrümanlarına düşülür."""
    try:
        import soundfile  # noqa: F401
    except Exception:
        return False
    return (SAMPLES_DIR / "manifest.json").is_file()


def load_bank(key: str, sr: int = 44100) -> SampleBank:
    with _bank_lock:
        bank = _banks.get((key, sr))
        if bank is None:
            manifest = json.loads((SAMPLES_DIR / "manifest.json").read_text(encoding="utf-8"))
            if int(manifest.get("sample_rate", sr)) != sr:
                raise ValueError(f"kayıtlar {manifest['sample_rate']} Hz, motor {sr} Hz")
            bank = SampleBank(key, manifest["instruments"][key], sr)
            _banks[(key, sr)] = bank
        return bank


# ===========================================================================
class SampleInstrument:
    """Kayıtla çalan enstrüman. Sınıf nitelikleri tınıyı ve stereo yerini belirler."""

    key = "sample"
    label = "Kayıt"
    release = 0.3               # renk bitince sesin kısılma süresi (sn)
    gain = 1.0
    pan = 0.0                   # -1 sol, +1 sağ
    velocity_floor = 0.30       # en hafif nota bile duyulsun (0..1)

    def __init__(self, enabled: bool = False, volume: float = 0.75, octave: int = 0, sr: int = 44100):
        self.enabled = enabled
        self.volume = float(volume)
        self.octave = int(octave)
        self.bank = load_bank(self.key, sr)

    def new_voice(self, midi: int, velocity: float, sr: int, offset: int = 0) -> "SampleVoice":
        played = self.bank.fold(int(midi) + 12 * self.octave)
        return SampleVoice(self, played, velocity, sr, offset, data_midi=int(midi))


class SampleVoice:
    """Bir kaydın tek bir notası. Voice ile aynı arayüz."""

    def __init__(self, instrument: SampleInstrument, midi: int, velocity: float, sr: int,
                 offset: int = 0, data_midi: int = None):
        bank = instrument.bank
        self.inst = instrument
        self.midi = int(midi)
        self.data_midi = self.midi if data_midi is None else data_midi
        self.velocity = float(velocity)
        self.sr = sr
        root = bank.nearest_root(self.midi)
        self.buf = bank.data[root]
        self.loop = bank.loops[root]
        self.end = len(self.buf) - 2
        # perde oranı: kayıt kökünden istenen notaya, kaydın akort sapması düzeltilerek
        # (+ örnekleme hızı farkı). Sonuç: eşit tamperamanda tam nota, tüm enstrümanlar aynı akortta.
        self.rate = 2.0 ** ((self.midi - root) / 12.0 - bank.tunes[root] / 1200.0) * (bank.sr / sr)
        v = float(np.clip(velocity, 0.0, 1.0))
        self.amp = instrument.velocity_floor + (1.0 - instrument.velocity_floor) * v
        self.pos = 0.0
        self.samples = 0
        self.start_offset = int(offset)
        self.released_at = None
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

        p = self.pos + self.rate * np.arange(m)
        if self.loop is not None:
            a, b = self.loop
            over = p >= b
            if over.any():
                p = np.where(over, a + np.mod(p - a, b - a), p)
            self.pos = float(p[-1] + self.rate)
            if self.pos >= b:
                self.pos = a + (self.pos - a) % (b - a)
            alive = np.ones(m, dtype=bool)
        else:
            alive = p < self.end
            self.pos = float(p[-1] + self.rate)
            if not alive[-1]:
                self.finished = True
            p = np.where(alive, p, 0.0)

        i0 = p.astype(np.int64)
        frac = (p - i0).astype(np.float32)
        wave = self.buf[i0] * (1.0 - frac) + self.buf[i0 + 1] * frac
        wave = np.where(alive, wave, 0.0)

        gain = np.full(m, self.amp, dtype=np.float32)
        if self.released_at is not None:
            t = (self.samples + np.arange(m)) / self.sr
            tr = t - self.released_at
            rel = max(self.inst.release, 1e-3)
            gain *= np.where(tr > 0, np.exp(-np.maximum(tr, 0.0) * 6.9 / rel), 1.0).astype(np.float32)
            if tr[-1] >= rel:
                self.finished = True

        out[off:] = (wave * gain).astype(np.float32)
        self.samples += m
        return out


# ===========================================================================
class SampledPiano(SampleInstrument):
    key, label = "piano", "Piyano"
    release, gain, pan = 0.35, 1.0, 0.0


class SampledViolin(SampleInstrument):
    key, label = "violin", "Keman"
    release, gain, pan = 0.25, 0.95, -0.25


class SampledFlute(SampleInstrument):
    key, label = "flute", "Yan Flüt"
    release, gain, pan = 0.15, 0.95, 0.3


class SampledAcousticGuitar(SampleInstrument):
    key, label = "aguitar", "Akustik Gitar"
    release, gain, pan = 0.40, 1.0, -0.45


class SampledElectricGuitar(SampleInstrument):
    key, label = "eguitar", "Elektro Gitar"
    release, gain, pan = 0.30, 0.95, 0.45
