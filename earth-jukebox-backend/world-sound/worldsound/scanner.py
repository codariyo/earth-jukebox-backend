"""
Görünür bölge tarayıcı.

Kullanıcının o an gördüğü bölge (Viewport) satır x sütun hücrelik bir ızgaraya
bölünür. Her hücrenin notası, hücreye düşen GERÇEK PİKSELLERİN tek tek
notaya çevrilmesiyle ve en çok tekrarlanan notanın (oy çokluğu) seçilmesiyle
bulunur.

Neden renk ortalaması değil de piksel oylaması?
    Bir hücrede yarısı kırmızı yarısı mavi piksel varsa renk ortalaması MOR
    çıkar ve haritada olmayan bir nota üretir. Piksel oylamasında her piksel
    kendi notasını verir, hücre haritada gerçekten bulunan rengin notasını alır.

Yakınlaştırma
    Izgara her zaman görünür bölgeye oturur. Yakınlaştıkça her hücreye düşen
    piksel sayısı azalır; yeterince yakınlaşınca bir hücre = bir piksel olur
    (gerçek anlamda piksel piksel tarama). Farklı bir bölgeye bakmak tamamen
    farklı pikseller, dolayısıyla farklı bir müzik demektir.
"""

from dataclasses import dataclass

import numpy as np

from .color_pitch import ColorPitchMapper
from .map_data import MapData
from .viewport import Viewport


@dataclass
class ScanGrid:
    """Bir görünümün taranmış hali."""
    notes: np.ndarray        # (satır, sütun) int16 MIDI, -1 = sessiz hücre
    strength: np.ndarray     # (satır, sütun) 0..1
    viewport: Viewport
    pixel_box: tuple         # taranan gerçek piksel kutusu (x0, y0, x1, y1)

    @property
    def rows(self) -> int:
        return self.notes.shape[0]

    @property
    def cols(self) -> int:
        return self.notes.shape[1]

    @property
    def sounding_cells(self) -> int:
        return int((self.notes >= 0).sum())

    def column(self, j: int):
        """j. sütundaki sesli hücreler: [(satır, midi, güç), ...] (yukarıdan aşağı)."""
        col_n = self.notes[:, j]
        col_s = self.strength[:, j]
        return [(i, int(col_n[i]), float(col_s[i])) for i in range(self.rows) if col_n[i] >= 0]


class ViewportScanner:
    def __init__(self, mapper: ColorPitchMapper, rows: int = 36, cols: int = 64,
                 min_valid_fraction: float = 0.30, max_pixels: int = 1_500_000):
        self.mapper = mapper
        self.rows = int(rows)
        self.cols = int(cols)
        self.min_valid_fraction = float(min_valid_fraction)   # hücrenin en az bu kadarı veri olmalı
        self.max_pixels = int(max_pixels)                     # hız için üst sınır

    def set_grid(self, rows: int, cols: int):
        self.rows, self.cols = max(1, int(rows)), max(1, int(cols))

    def scan(self, data: MapData, viewport: Viewport) -> ScanGrid:
        box = data.pixel_box(*viewport.as_tuple())
        px0, py0, px1, py1 = box
        crop = data.rgba[py0:py1, px0:px1]

        # Çok büyük bölge: hız için düzenli seyreltme (her k. piksel)
        h, w = crop.shape[:2]
        if h * w > self.max_pixels:
            k = int(np.ceil(np.sqrt(h * w / self.max_pixels)))
            crop = crop[::k, ::k]
            h, w = crop.shape[:2]

        rows, cols = self.rows, self.cols

        # 1) Her piksel kendi notasını verir
        midi, strength = self.mapper.map_pixels(crop)

        # 2) Pikselin hangi hücreye düştüğü. Görünür bölge ızgaradan küçükse
        #    (çok yakınlaşma) bir piksel birden fazla hücreyi kaplar.
        if h < rows or w < cols:
            ry = (np.arange(rows) * h) // rows
            cx = (np.arange(cols) * w) // cols
            n = midi[np.ix_(ry, cx)]
            s = strength[np.ix_(ry, cx)]
            return ScanGrid(n.astype(np.int16), s.astype(np.float32), viewport.copy(), box)

        cell_r = (np.arange(h) * rows) // h
        cell_c = (np.arange(w) * cols) // w
        cell = (cell_r[:, None] * cols + cell_c[None, :]).ravel()
        n_cells = rows * cols

        flat_midi = midi.ravel()
        flat_str = strength.ravel()
        valid = flat_midi >= 0

        total = np.bincount(cell, minlength=n_cells)
        valid_cnt = np.bincount(cell[valid], minlength=n_cells)

        # 3) Oy çokluğu: her hücrede en çok piksel tarafından verilen nota
        lo = self.mapper.low_midi
        span = self.mapper.high_midi - lo + 1
        key = cell[valid] * span + (flat_midi[valid].astype(np.int64) - lo)
        votes = np.bincount(key, minlength=n_cells * span).reshape(n_cells, span)
        power = np.bincount(key, weights=flat_str[valid], minlength=n_cells * span).reshape(n_cells, span)

        best = votes.argmax(axis=1)
        best_votes = votes[np.arange(n_cells), best]
        best_power = power[np.arange(n_cells), best] / np.maximum(best_votes, 1)

        sounding = (valid_cnt >= self.min_valid_fraction * np.maximum(total, 1)) & (best_votes > 0)
        notes = np.where(sounding, best + lo, -1).astype(np.int16).reshape(rows, cols)
        strg = np.where(sounding, best_power, 0.0).astype(np.float32).reshape(rows, cols)
        return ScanGrid(notes, strg, viewport.copy(), box)
