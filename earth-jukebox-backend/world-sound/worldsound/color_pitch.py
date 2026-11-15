"""
Renk -> nota eşlemesi.

KURAL
    Kırmızı  = en TİZ nota
    Mavi     = en PES nota
    Ara renkler bu iki uç arasında rengin konumuna göre ORANTILI yerleşir:

        Mavi 240°  ->  Camgöbeği 180°  ->  Yeşil 120°  ->  Sarı 60°  ->  Kırmızı 0°
        (pes)                                                             (tiz)

    Mor/macenta (240°..360°) maviden kırmızıya diğer yoldan geri sarar;
    böylece renk çemberinde hiçbir yerde ani bir sıçrama olmaz.

    Bulunan sürekli perde, seçili dizideki EN YAKIN gerçek notaya oturtulur
    ("Do ile Si arasında Fa'ya daha yakınsa Fa").

SESSİZLİK
    - alpha = 0 (NASA "ölçüm yok")            -> nota yok
    - çok karanlık piksel (siyah)              -> nota yok
    - renksiz piksel (beyaz / gri)             -> nota yok
      (rengi olmayan pikselin kırmızı-mavi ekseninde bir yeri yoktur)
"""

from dataclasses import dataclass

import numpy as np

NOTE_NAMES_TR = ["Do", "Do#", "Re", "Re#", "Mi", "Fa", "Fa#", "Sol", "Sol#", "La", "La#", "Si"]


def midi_to_hz(midi):
    return 440.0 * (2.0 ** ((np.asarray(midi, dtype=np.float64) - 69.0) / 12.0))


def note_name(midi: int) -> str:
    """60 -> 'Do4'"""
    midi = int(midi)
    return f"{NOTE_NAMES_TR[midi % 12]}{midi // 12 - 1}"


# ===========================================================================
class Scale:
    """Bir müzik dizisi (ör. Do majör: Do Re Mi Fa Sol La Si)."""

    PRESETS = {
        "Majör (Do-Re-Mi-Fa-Sol-La-Si)": (0, 2, 4, 5, 7, 9, 11),
        "Minör": (0, 2, 3, 5, 7, 8, 10),
        "Pentatonik": (0, 2, 4, 7, 9),
        "Kromatik (12 yarım ses)": tuple(range(12)),
    }

    def __init__(self, intervals=(0, 2, 4, 5, 7, 9, 11), root: int = 0, name: str = "Majör"):
        self.intervals = tuple(sorted({int(i) % 12 for i in intervals}))
        self.root = int(root) % 12
        self.name = name

    @classmethod
    def preset(cls, name: str, root: int = 0) -> "Scale":
        return cls(cls.PRESETS[name], root, name)

    def notes_between(self, low: int, high: int) -> np.ndarray:
        """[low, high] aralığındaki tüm dizi notaları (MIDI), artan sırada."""
        pcs = {(self.root + i) % 12 for i in self.intervals}
        return np.array([m for m in range(int(low), int(high) + 1) if m % 12 in pcs], dtype=np.int16)

    def __repr__(self):
        return f"Scale({self.name}, kök={NOTE_NAMES_TR[self.root]})"


# ===========================================================================
@dataclass
class SilenceRules:
    """Bir pikselin nota üretmesi için sağlaması gereken koşullar."""
    min_alpha: float = 0.5        # altı: ölçüm yok (şeffaf)
    min_value: float = 0.12       # parlaklık bunun altı: siyah -> sessiz
    min_saturation: float = 0.20  # doygunluk bunun altı: beyaz/gri -> sessiz


class ColorPitchMapper:
    """Pikselleri notaya çevirir. Tümüyle vektöreldir (milyonlarca pikselde hızlı)."""

    def __init__(self, low_midi: int = 36, high_midi: int = 95,
                 scale: Scale = None, rules: SilenceRules = None, diverging: bool = False):
        self.low_midi = int(low_midi)          # mavi  -> Do2
        self.high_midi = int(high_midi)        # kırmızı -> Si6
        self.scale = scale or Scale.preset("Majör (Do-Re-Mi-Fa-Sol-La-Si)")
        self.rules = rules or SilenceRules()
        # IRAKSAK HARİTA KİPİ (mavi - beyaz - kırmızı skalalar: akıntı, anomali)
        # Bu haritalarda değerin büyüklüğü renk TONUNDA değil SOLUKLUĞUNDA saklıdır:
        # soluk mavi = zayıf, koyu mavi = güçlü. Kip açıkken soluk renkler orta
        # notalara, doygun renkler uçlara (en pes / en tiz) gider. Kapalıyken
        # yalnız renk tonu belirleyicidir.
        self.diverging = bool(diverging)
        self._rebuild()

    def _rebuild(self):
        self._notes = self.scale.notes_between(self.low_midi, self.high_midi)
        if len(self._notes) == 0:
            raise ValueError("Seçili aralıkta dizi notası yok.")

    def set_scale(self, scale: Scale):
        self.scale = scale
        self._rebuild()

    def set_range(self, low_midi: int, high_midi: int):
        self.low_midi, self.high_midi = int(min(low_midi, high_midi)), int(max(low_midi, high_midi))
        self._rebuild()

    @property
    def available_notes(self) -> np.ndarray:
        return self._notes

    # ------------------------------------------------------------------ renk uzayı
    @staticmethod
    def rgb_to_hsv(rgb: np.ndarray):
        """(..., 3) RGB 0..1 -> ton (0..360), doygunluk (0..1), parlaklık (0..1)."""
        r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        cmax = np.max(rgb, axis=-1)
        cmin = np.min(rgb, axis=-1)
        delta = cmax - cmin
        hue = np.zeros_like(cmax)
        nz = delta > 1e-6
        rm = nz & (cmax == r)
        gm = nz & (cmax == g) & ~rm
        bm = nz & ~rm & ~gm
        safe = np.where(nz, delta, 1.0)
        hue = np.where(rm, 60.0 * (((g - b) / safe) % 6.0), hue)
        hue = np.where(gm, 60.0 * (((b - r) / safe) + 2.0), hue)
        hue = np.where(bm, 60.0 * (((r - g) / safe) + 4.0), hue)
        sat = np.where(cmax > 1e-6, delta / np.where(cmax > 1e-6, cmax, 1.0), 0.0)
        return hue, sat, cmax

    @staticmethod
    def hue_position(hue) -> np.ndarray:
        """
        Renk tonunun pes-tiz eksenindeki yeri: 0.0 = mavi (pes), 1.0 = kırmızı (tiz).
            240° mavi -> 0.00   180° camgöbeği -> 0.25   120° yeşil -> 0.50
             60° sarı -> 0.75     0° kırmızı   -> 1.00   300° macenta -> 0.50
        """
        h = np.mod(np.asarray(hue, dtype=np.float64), 360.0)
        return np.where(h <= 240.0, 1.0 - h / 240.0, (h - 240.0) / 120.0)

    def nearest_note(self, continuous_midi) -> np.ndarray:
        """Sürekli perdeyi dizideki en yakın notaya oturtur."""
        notes = self._notes.astype(np.float64)
        x = np.asarray(continuous_midi, dtype=np.float64)
        i = np.clip(np.searchsorted(notes, x), 1, len(notes) - 1)
        lo, hi = notes[i - 1], notes[i]
        pick_hi = (hi - x) < (x - lo)
        out = np.where(pick_hi, hi, lo)
        if len(notes) == 1:
            out = np.full_like(x, notes[0])
        return out.astype(np.int16)

    # ------------------------------------------------------------------ ana işlev
    def map_pixels(self, rgba: np.ndarray):
        """
        (Y, G, 4) RGBA 0..1 -> (midi, güç)
            midi : int16, nota üretmeyen pikselde -1
            güç  : 0..1, rengin canlılığı (nota şiddetine dönüşür)
        """
        rgba = np.asarray(rgba, dtype=np.float32)
        hue, sat, val = self.rgb_to_hsv(rgba[..., :3])
        r = self.rules
        valid = (rgba[..., 3] >= r.min_alpha) & (val >= r.min_value) & (sat >= r.min_saturation)

        pos = self.hue_position(hue)
        if self.diverging:
            w = np.clip((sat - r.min_saturation) / max(1e-6, 1.0 - r.min_saturation), 0.0, 1.0)
            pos = 0.5 + (pos - 0.5) * w
        target = self.low_midi + pos * (self.high_midi - self.low_midi)
        midi = np.where(valid, self.nearest_note(target), -1).astype(np.int16)

        strength = np.clip(np.power(val, 0.7) * (0.35 + 0.65 * sat), 0.0, 1.0)
        strength = np.where(valid, strength, 0.0).astype(np.float32)
        return midi, strength

    def note_for_rgb(self, r: float, g: float, b: float, a: float = None):
        """
        Tek bir renk için nota. Sessizse None.
        Renk 0..1 ya da 0..255 olabilir; alpha verilmezse opak kabul edilir.
        """
        rgb = np.array([r, g, b], dtype=np.float32)
        scale255 = rgb.max() > 1.0 or (a is not None and a > 1.0)
        if scale255:
            rgb = rgb / 255.0
            alpha = 1.0 if a is None else float(a) / 255.0
        else:
            alpha = 1.0 if a is None else float(a)
        arr = np.array([[[rgb[0], rgb[1], rgb[2], alpha]]], dtype=np.float32)
        m, _ = self.map_pixels(arr)
        v = int(m[0, 0])
        return None if v < 0 else v
