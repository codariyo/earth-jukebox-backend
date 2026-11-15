"""
Ses motoru.

AudioEngine ses kartından bağımsızdır: render(frames) çağrıldıkça bir blok
stereo ses üretir. Böylece:
    - SoundDeviceOutput ile hoparlöre verilebilir,
    - diğer uygulamanın kendi ses sistemine bağlanabilir,
    - testlerde / dışa aktarımda ses kartı olmadan çalıştırılabilir.

Sinyal yolu:
    ScanSequencer -> nota olayları -> her etkin enstrümanda Voice
    -> stereo karışım -> 5 bant EQ -> yankı -> ana ses -> limiter -> çıkış
"""

import collections
import threading

import numpy as np

from .effects import Reverb, SoftLimiter
from .equalizer import FiveBandEqualizer
from .instruments import InstrumentRack, Voice
from .sequencer import NoteEvent, ScanSequencer


class AudioEngine:
    MAX_VOICES = 160

    def __init__(self, sequencer: ScanSequencer, rack: InstrumentRack = None,
                 sample_rate: int = 44100, block_size: int = 1024):
        self.sr = int(sample_rate)
        self.block = int(block_size)
        self.sequencer = sequencer
        self.rack = rack or InstrumentRack.default()
        self.equalizer = FiveBandEqualizer(self.sr, 2)
        self.reverb = Reverb(self.block, mix=0.18)
        self.limiter = SoftLimiter()
        self.master = 0.8
        self.duck_target = 1.0                  # seslendirme sırasında müziği kısma (set_duck)
        self._duck = 1.0

        self._voices = []
        self._commands = collections.deque()    # arayüz -> ses iş parçacığı
        self.spectrum = np.zeros(48)            # görselleştirme için
        self.peak = 0.0
        self._fft_freqs = np.fft.rfftfreq(self.block, 1.0 / self.sr)
        self._band_edges = np.geomspace(40, 16000, len(self.spectrum) + 1)
        self._window = np.hanning(self.block)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ arayüz komutları
    def set_instrument_enabled(self, key: str, enabled: bool):
        self.rack[key].enabled = bool(enabled)
        self._commands.append(("enable", key, bool(enabled)))

    def set_instrument_volume(self, key: str, volume: float):
        self.rack[key].volume = float(np.clip(volume, 0.0, 1.0))

    def set_instrument_octave(self, key: str, octave: int):
        self.rack[key].octave = int(np.clip(octave, -3, 3))
        self._commands.append(("retune", key, None))

    def set_duck(self, level: float):
        """Konuşma (seslendirme) sırasında müziği kıs: 1.0 = normal, 0.25 = arka plan.
        Değişim yumuşaktır (~0,15 sn), tıkırtı olmaz."""
        self.duck_target = float(np.clip(level, 0.0, 1.0))

    def all_notes_off(self):
        self._commands.append(("panic", None, None))

    @property
    def active_voices(self) -> int:
        return len(self._voices)

    # ------------------------------------------------------------------ ses iş parçacığı
    def _run_commands(self):
        while self._commands:
            cmd, key, val = self._commands.popleft()
            if cmd == "panic":
                for v in self._voices:
                    v.release()
                continue
            # Enstrüman kapandı ya da oktavı değişti: o enstrümanın sesleri söner
            if (cmd == "enable" and not val) or cmd == "retune":
                for v in self._voices:
                    if v.inst.key == key:
                        v.release()
            # Enstrüman açıldı / yeniden ayarlandı: o an çalan harita notalarına hemen katılır
            if (cmd == "enable" and val) or (cmd == "retune" and self.rack[key].enabled):
                inst = self.rack[key]
                playing = {v.data_midi for v in self._voices if v.inst is inst and v.released_at is None}
                for midi, note in self.sequencer.sounding.items():
                    if midi not in playing:
                        self._voices.append(inst.new_voice(midi, note.velocity, self.sr))

    def _apply(self, events):
        for ev in events:
            if ev.kind == "off":
                for v in self._voices:
                    if v.data_midi == ev.midi and v.released_at is None:
                        v.release(ev.offset)
            else:
                # AYNI NOTA, ETKİN TÜM ENSTRÜMANLARDA AYNI ANDA
                for inst in self.rack.enabled():
                    self._voices.append(inst.new_voice(ev.midi, ev.velocity, self.sr, ev.offset))
        if len(self._voices) > self.MAX_VOICES:
            self._voices.sort(key=lambda v: (v.released_at is None, -v.samples))
            self._voices = self._voices[len(self._voices) - self.MAX_VOICES:]

    def render(self, frames: int = None) -> np.ndarray:
        """Bir blok stereo ses (frames, 2) float32 üretir."""
        frames = int(frames or self.block)
        self._run_commands()
        self._apply(self.sequencer.advance(frames))

        mix = np.zeros((frames, 2), dtype=np.float32)
        alive = []
        for v in self._voices:
            inst = v.inst
            mono = v.render(frames)
            g = inst.volume * inst.gain
            if g > 0:
                pan = (inst.pan + 1.0) * np.pi / 4.0
                mix[:, 0] += mono * (g * np.cos(pan))
                mix[:, 1] += mono * (g * np.sin(pan))
            if not v.finished:
                alive.append(v)
        self._voices = alive

        out = self.equalizer.process(mix)
        out = self.reverb.process(out) if frames <= self.reverb.max_block else out
        # müzik kısma (ducking): blok içinde doğrusal geçiş, blok başına en çok 0.15 → ~0,15 sn
        if self._duck != self.duck_target:
            diff = self.duck_target - self._duck
            nxt = self.duck_target if abs(diff) <= 0.15 else self._duck + (0.15 if diff > 0 else -0.15)
            ramp = np.linspace(self._duck, nxt, frames, dtype=np.float32)[:, None]
            self._duck = nxt
            out = out * ramp
        elif self._duck != 1.0:
            out = out * self._duck
        out = self.limiter.process(out * self.master)
        out = np.nan_to_num(out).astype(np.float32)

        self._analyze(out)
        return out

    def _analyze(self, out: np.ndarray):
        self.peak = float(np.max(np.abs(out))) if len(out) else 0.0
        if len(out) != self.block:
            return
        mono = out.mean(axis=1) * self._window
        mag = np.abs(np.fft.rfft(mono)) / (self.block * 0.25)
        bars = np.zeros(len(self.spectrum))
        for i in range(len(bars)):
            m = (self._fft_freqs >= self._band_edges[i]) & (self._fft_freqs < self._band_edges[i + 1])
            if m.any():
                bars[i] = mag[m].max()
        db = 20 * np.log10(np.maximum(bars, 1e-6))
        new = np.clip((db + 70.0) / 70.0, 0.0, 1.0)
        self.spectrum = np.maximum(new, self.spectrum * 0.80)


class SoundDeviceOutput:
    """AudioEngine'i bilgisayarın hoparlörüne bağlar."""

    def __init__(self, engine: AudioEngine):
        self.engine = engine
        self.stream = None
        self.last_error = None

    def start(self):
        import sounddevice as sd
        if self.stream is not None:
            return

        def callback(outdata, frames, time_info, status):
            try:
                outdata[:] = self.engine.render(frames)
            except Exception as ex:                 # ses akışı hiçbir hatada kesilmesin
                outdata.fill(0)
                if self.last_error is None:
                    self.last_error = repr(ex)
                    print("Ses motoru hatası:", self.last_error)

        self.stream = sd.OutputStream(samplerate=self.engine.sr, blocksize=self.engine.block,
                                      channels=2, dtype="float32", callback=callback)
        self.stream.start()

    def stop(self):
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None
