"""
Çıkış efektleri: salon yankısı ve yumuşak sınırlayıcı (limiter).

Her ikisi de durumunu sıfırdan başlatır; giriş sessizse çıkış da tam sessizdir.
"""

import numpy as np


class _Comb:
    def __init__(self, delay: int, feedback: float, damp: float, channels: int):
        self.buf = np.zeros((delay, channels), dtype=np.float32)
        self.d, self.fb, self.damp = delay, feedback, damp
        self.p = 0
        self.store = np.zeros(channels, dtype=np.float32)

    def process(self, x):
        n = len(x)
        idx = (self.p + np.arange(n)) % self.d
        y = self.buf[idx].copy()
        damped = y * (1.0 - self.damp) + self.store * self.damp
        self.store = damped[-1]
        self.buf[idx] = x + damped * self.fb
        self.p = (self.p + n) % self.d
        return y


class _Allpass:
    def __init__(self, delay: int, g: float, channels: int):
        self.buf = np.zeros((delay, channels), dtype=np.float32)
        self.d, self.g, self.p = delay, g, 0

    def process(self, x):
        n = len(x)
        idx = (self.p + np.arange(n)) % self.d
        b = self.buf[idx].copy()
        y = -self.g * x + b
        self.buf[idx] = x + self.g * y
        self.p = (self.p + n) % self.d
        return y


class Reverb:
    """
    Schroeder salon yankısı. Gecikmeler blok boyundan uzun seçildiği için
    geri besleme tek blok içinde dönmez; tamamen vektörel çalışır.
    process() kuru + ıslak karışımı döndürür.
    """

    def __init__(self, block_size: int = 1024, mix: float = 0.18, channels: int = 2):
        self.mix = float(mix)
        d = max(int(block_size) + 64, 1601)
        self.combs = [_Comb(d + o, fb, 0.28, channels)
                      for o, fb in ((0, 0.80), (113, 0.79), (241, 0.78), (367, 0.77))]
        self.aps = [_Allpass(d + 17, 0.5, channels), _Allpass(d + 89, 0.5, channels)]
        self.max_block = d

    def process(self, x: np.ndarray) -> np.ndarray:
        if self.mix <= 0.0 or len(x) > self.max_block:
            return x
        acc = np.zeros_like(x, dtype=np.float32)
        for c in self.combs:
            acc += c.process(x)
        acc *= 0.25
        for ap in self.aps:
            acc = ap.process(acc)
        wide = acc.copy()
        if acc.shape[1] == 2:
            wide[:, 0] = acc[:, 0] * 0.9 + acc[:, 1] * 0.2
            wide[:, 1] = acc[:, 1] * 0.9 + acc[:, 0] * 0.2
        return x * (1.0 - 0.4 * self.mix) + wide * self.mix


class SoftLimiter:
    """Eşiğin altında şeffaf, üstünde tanh ile yumuşak sınırlama (patlama olmaz)."""

    def __init__(self, threshold: float = 0.75, ceiling: float = 0.98):
        self.threshold = threshold
        self.margin = ceiling - threshold

    def process(self, x: np.ndarray) -> np.ndarray:
        a = np.abs(x)
        over = a > self.threshold
        if not over.any():
            return x
        y = x.copy()
        y[over] = np.sign(x[over]) * (self.threshold + self.margin * np.tanh((a[over] - self.threshold) / self.margin))
        return y
