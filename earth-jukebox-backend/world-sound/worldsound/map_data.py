"""
Okunmuş harita verisi.

MapData, kaynağı ne olursa olsun (NASA GIBS, PNG dosyası, başka bir uygulamanın
bellekteki görüntüsü) haritayı TEK bir biçimde tutar:

    rgba   : (yükseklik, genişlik, 4) float32, 0..1
             alpha = 0 olan piksel "ölçüm yok" demektir ve asla nota üretmez.
    bounds : haritanın coğrafi sınırları (boylam/enlem). Equirectangular
             (EPSG:4326) varsayılır; NASA GIBS çıktıları bu biçimdedir.
"""

from dataclasses import dataclass, field

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class GeoBounds:
    """Coğrafi sınırlar (derece). Varsayılan: tüm dünya."""
    west: float = -180.0
    south: float = -90.0
    east: float = 180.0
    north: float = 90.0

    @property
    def width(self) -> float:
        return self.east - self.west

    @property
    def height(self) -> float:
        return self.north - self.south

    def as_bbox(self):
        """WMS 1.1.1 / EPSG:4326 BBOX sırası: batı, güney, doğu, kuzey."""
        return (self.west, self.south, self.east, self.north)


class MapData:
    """Harita görüntüsü + coğrafi bilgi. Değişmez (salt okunur) kabul edilir."""

    def __init__(self, rgba: np.ndarray, bounds: GeoBounds = GeoBounds(),
                 name: str = "", meta: dict = None):
        arr = np.asarray(rgba)
        if arr.ndim != 3 or arr.shape[2] not in (3, 4):
            raise ValueError(f"Görüntü (Y, G, 3|4) olmalı, gelen: {arr.shape}")
        if arr.dtype == np.uint8:
            arr = arr.astype(np.float32) / 255.0
        else:
            arr = np.clip(arr.astype(np.float32), 0.0, 1.0)
        if arr.shape[2] == 3:
            alpha = np.ones(arr.shape[:2] + (1,), dtype=np.float32)
            arr = np.concatenate([arr, alpha], axis=2)
        arr.setflags(write=False)

        self.rgba = arr
        self.bounds = bounds
        self.name = name
        self.meta = dict(meta or {})

    # ------------------------------------------------------------------ boyut
    @property
    def height(self) -> int:
        return self.rgba.shape[0]

    @property
    def width(self) -> int:
        return self.rgba.shape[1]

    @property
    def aspect(self) -> float:
        return self.width / max(self.height, 1)

    # ------------------------------------------------------------------ dönüşüm
    @classmethod
    def from_pil(cls, img: Image.Image, bounds: GeoBounds = GeoBounds(), name: str = "", meta=None):
        return cls(np.array(img.convert("RGBA")), bounds, name, meta)

    def to_pil(self) -> Image.Image:
        return Image.fromarray((self.rgba * 255.0 + 0.5).astype(np.uint8), "RGBA")

    def pixel_box(self, x0: float, y0: float, x1: float, y1: float):
        """Normalize (0..1) kutuyu piksel indekslerine çevirir (en az 1 piksel)."""
        W, H = self.width, self.height
        px0 = int(np.clip(np.floor(x0 * W), 0, W - 1))
        py0 = int(np.clip(np.floor(y0 * H), 0, H - 1))
        px1 = int(np.clip(np.ceil(x1 * W), px0 + 1, W))
        py1 = int(np.clip(np.ceil(y1 * H), py0 + 1, H))
        return px0, py0, px1, py1

    def crop(self, x0: float, y0: float, x1: float, y1: float) -> np.ndarray:
        """Normalize kutunun piksellerini (kopyalamadan) döndürür."""
        px0, py0, px1, py1 = self.pixel_box(x0, y0, x1, y1)
        return self.rgba[py0:py1, px0:px1]

    # ------------------------------------------------------------------ coğrafya
    def norm_to_lonlat(self, x: float, y: float):
        b = self.bounds
        return b.west + x * b.width, b.north - y * b.height

    def lonlat_to_norm(self, lon: float, lat: float):
        b = self.bounds
        return (lon - b.west) / b.width, (b.north - lat) / b.height

    def __repr__(self):
        return f"MapData('{self.name}', {self.width}x{self.height}, {self.bounds})"
