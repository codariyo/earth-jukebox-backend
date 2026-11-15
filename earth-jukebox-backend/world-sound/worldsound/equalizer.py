"""
5 bantlı parametrik ekolayzer.

    Bant          Tür          Merkez / köşe   Etkilediği bölge
    -----------   ----------   -------------   ------------------------------
    Bas           alçak raf      100 Hz        kalın sesler, bas gitar
    Düşük Mid     tepe (peak)    300 Hz        sıcaklık, gövde
    Orta          tepe (peak)   1000 Hz        enstrümanların ana tınısı
    Yüksek Mid    tepe (peak)   3000 Hz        netlik, atak
    Tiz           yüksek raf    8000 Hz        parlaklık, hava

Her bant -12 dB ile +12 dB arasında, 0,1 dB hassasiyetle ayarlanır. 0 dB'deki
bant matematiksel olarak etkisizdir (birim filtre). Filtreler RBJ "Audio EQ
Cookbook" formülleriyle kurulur ve seri bağlanır.

YUMUŞAK GEÇİŞ: yeni kazanç bir anda değil, ses bloğu başına en çok RAMP_DB
kadar (saniyede ~60 dB) hedefe yaklaşır. Kaydırıcı sürüklenirken "fermuar"
cızırtısı ve tıkırtı olmaz; 12 dB'lik değişim ~0,2 sn'de tamamlanır.

ÖNEMLİ: Filtre durumları SIFIRDAN başlatılır. (scipy.signal.sosfilt_zi
birim-basamak kararlı durumunu verir; giriş sessizken bile duyulur bir
uğultu/klik üretir. Siyah bir haritada ses çıkmasının sebebi buydu.)
"""

import threading
from dataclasses import dataclass

import numpy as np
from scipy.signal import sosfilt, sosfreqz


@dataclass
class EqBand:
    key: str
    label: str
    kind: str           # lowshelf | peak | highshelf
    freq: float
    q: float = 1.0
    gain_db: float = 0.0


class FiveBandEqualizer:
    MIN_DB, MAX_DB = -12.0, 12.0
    RESOLUTION_DB = 0.1          # ayar hassasiyeti
    RAMP_DB_PER_SEC = 60.0       # kazanç değişim hızı (yumuşak geçiş)

    def __init__(self, sample_rate: int = 44100, channels: int = 2):
        self.sr = int(sample_rate)
        self.channels = int(channels)
        self.bands = [
            EqBand("bass", "Bas", "lowshelf", 100.0, 0.707),
            EqBand("low_mid", "Düşük Mid", "peak", 300.0, 1.0),
            EqBand("mid", "Orta", "peak", 1000.0, 1.0),
            EqBand("high_mid", "Yüksek Mid", "peak", 3000.0, 1.0),
            EqBand("treble", "Tiz", "highshelf", 8000.0, 0.707),
        ]
        self._by_key = {b.key: b for b in self.bands}
        self._lock = threading.Lock()
        self._cur = {b.key: 0.0 for b in self.bands}   # o an UYGULANAN kazanç (hedefe doğru kayar)
        self._sos = self._build_sos()
        self._zi = np.zeros((len(self.bands), 2, self.channels))
        self._dirty = False

    # ------------------------------------------------------------------ ayar
    def set_gain(self, key: str, gain_db: float):
        g = float(np.clip(gain_db, self.MIN_DB, self.MAX_DB))
        g = round(g, 1)                         # 0,1 dB hassasiyet (RESOLUTION_DB)
        with self._lock:
            self._by_key[key].gain_db = g
            self._dirty = True

    def gain(self, key: str) -> float:
        return self._by_key[key].gain_db

    def reset(self):
        for b in self.bands:
            self.set_gain(b.key, 0.0)

    @property
    def is_flat(self) -> bool:
        return all(abs(b.gain_db) < 1e-9 for b in self.bands)

    # ------------------------------------------------------------------ filtre tasarımı
    def _biquad(self, b: EqBand):
        A = 10.0 ** (b.gain_db / 40.0)
        w0 = 2.0 * np.pi * b.freq / self.sr
        cw, sw = np.cos(w0), np.sin(w0)
        alpha = sw / (2.0 * b.q)
        if b.kind == "peak":
            b0, b1, b2 = 1 + alpha * A, -2 * cw, 1 - alpha * A
            a0, a1, a2 = 1 + alpha / A, -2 * cw, 1 - alpha / A
        else:
            sa = 2.0 * np.sqrt(A) * alpha
            if b.kind == "lowshelf":
                b0 = A * ((A + 1) - (A - 1) * cw + sa)
                b1 = 2 * A * ((A - 1) - (A + 1) * cw)
                b2 = A * ((A + 1) - (A - 1) * cw - sa)
                a0 = (A + 1) + (A - 1) * cw + sa
                a1 = -2 * ((A - 1) + (A + 1) * cw)
                a2 = (A + 1) + (A - 1) * cw - sa
            else:  # highshelf
                b0 = A * ((A + 1) + (A - 1) * cw + sa)
                b1 = -2 * A * ((A - 1) + (A + 1) * cw)
                b2 = A * ((A + 1) + (A - 1) * cw - sa)
                a0 = (A + 1) - (A - 1) * cw + sa
                a1 = 2 * ((A - 1) - (A + 1) * cw)
                a2 = (A + 1) - (A - 1) * cw - sa
        return [b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]

    def _build_sos(self, gains: dict = None) -> np.ndarray:
        """gains verilirse (o an uygulanan, kayan kazançlar) onlarla; yoksa hedef kazançlarla."""
        if gains is None:
            return np.array([self._biquad(b) for b in self.bands], dtype=np.float64)
        return np.array([self._biquad(EqBand(b.key, b.label, b.kind, b.freq, b.q, gains[b.key]))
                         for b in self.bands], dtype=np.float64)

    # ------------------------------------------------------------------ işleme
    def process(self, x: np.ndarray) -> np.ndarray:
        """(örnek, kanal) stereo bloğu süzer."""
        with self._lock:
            if self._dirty:
                # uygulanan kazancı hedefe doğru blok uzunluğuyla orantılı kaydır (yumuşak geçiş)
                step = self.RAMP_DB_PER_SEC * len(x) / self.sr
                moving = False
                for b in self.bands:
                    cur, tgt = self._cur[b.key], b.gain_db
                    if abs(tgt - cur) <= step:
                        self._cur[b.key] = tgt
                    else:
                        self._cur[b.key] = cur + (step if tgt > cur else -step)
                        moving = True
                # durum (zi) korunur: katsayı değişirken kesinti olmaz
                self._sos = self._build_sos(self._cur)
                self._dirty = moving
            sos = self._sos
        y, self._zi = sosfilt(sos, x, axis=0, zi=self._zi)
        return y

    def frequency_response(self, freqs: np.ndarray) -> np.ndarray:
        """Verilen frekanslarda toplam kazanç (dB, hedef ayarlarla). Arayüzde eğri çizmek için."""
        with self._lock:
            sos = self._build_sos()
        _, h = sosfreqz(sos, worN=np.asarray(freqs, dtype=np.float64), fs=self.sr)
        return 20.0 * np.log10(np.maximum(np.abs(h), 1e-9))
