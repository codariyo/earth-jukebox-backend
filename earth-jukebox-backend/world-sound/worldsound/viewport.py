"""
Görünüm (viewport): kullanıcının haritada o an GÖRDÜĞÜ bölge.

Müzik görüntünün tamamından değil, yalnızca bu bölgeden üretilir. Kullanıcı
yakınlaştırdığında veya kaydırdığında görünüm değişir, tarayıcı yeni bölgeyi
tarar ve müzik o anki piksellere göre değişir.

Koordinatlar normalizedir: (0,0) haritanın sol üstü, (1,1) sağ altı.
Bu sayede görüntü çözünürlüğünden bağımsızdır; diğer uygulama kendi harita
görünümünü (boylam/enlem kutusu) from_lonlat() ile doğrudan aktarabilir.
"""

from .map_data import GeoBounds


class Viewport:
    MIN_SIZE = 1.0 / 512.0      # en fazla 512x yakınlaştırma

    def __init__(self, x0: float = 0.0, y0: float = 0.0, x1: float = 1.0, y1: float = 1.0):
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1
        self._clamp()

    # ------------------------------------------------------------------ özellikler
    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def center(self):
        return (self.x0 + self.x1) / 2.0, (self.y0 + self.y1) / 2.0

    @property
    def zoom_level(self) -> float:
        """1.0 = tüm harita, 4.0 = 4 kat yakınlaştırılmış."""
        return 1.0 / max(self.width, self.height)

    def as_tuple(self):
        return (self.x0, self.y0, self.x1, self.y1)

    def copy(self) -> "Viewport":
        return Viewport(*self.as_tuple())

    def __eq__(self, other):
        return isinstance(other, Viewport) and all(
            abs(a - b) < 1e-9 for a, b in zip(self.as_tuple(), other.as_tuple()))

    def __repr__(self):
        return (f"Viewport(x={self.x0:.4f}..{self.x1:.4f}, y={self.y0:.4f}..{self.y1:.4f}, "
                f"zoom={self.zoom_level:.1f}x)")

    # ------------------------------------------------------------------ işlemler
    def set(self, x0, y0, x1, y1) -> "Viewport":
        self.x0, self.y0, self.x1, self.y1 = float(x0), float(y0), float(x1), float(y1)
        self._clamp()
        return self

    def reset(self) -> "Viewport":
        return self.set(0.0, 0.0, 1.0, 1.0)

    def zoom(self, factor: float, cx: float = None, cy: float = None) -> "Viewport":
        """
        factor > 1 yakınlaştırır, < 1 uzaklaştırır.
        (cx, cy) normalize harita noktası sabit kalır (fare imlecinin altı gibi).
        """
        if cx is None or cy is None:
            cx, cy = self.center
        factor = max(1e-6, float(factor))
        new_w = min(1.0, max(self.MIN_SIZE, self.width / factor))
        new_h = min(1.0, max(self.MIN_SIZE, self.height / factor))
        rx = (cx - self.x0) / self.width if self.width else 0.5
        ry = (cy - self.y0) / self.height if self.height else 0.5
        x0 = cx - rx * new_w
        y0 = cy - ry * new_h
        return self.set(x0, y0, x0 + new_w, y0 + new_h)

    def pan(self, dx: float, dy: float) -> "Viewport":
        """Görünümü normalize birimle kaydırır (boyutu korur)."""
        return self.set(self.x0 + dx, self.y0 + dy, self.x1 + dx, self.y1 + dy)

    def _clamp(self):
        w = min(1.0, max(self.MIN_SIZE, self.x1 - self.x0))
        h = min(1.0, max(self.MIN_SIZE, self.y1 - self.y0))
        x0 = min(max(0.0, self.x0), 1.0 - w)
        y0 = min(max(0.0, self.y0), 1.0 - h)
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x0 + w, y0 + h

    # ------------------------------------------------------------------ coğrafya
    def to_lonlat(self, bounds: GeoBounds) -> GeoBounds:
        """Görünümün coğrafi kutusu (NASA'dan bu bölgeyi detaylı çekmek için)."""
        return GeoBounds(
            west=bounds.west + self.x0 * bounds.width,
            east=bounds.west + self.x1 * bounds.width,
            north=bounds.north - self.y0 * bounds.height,
            south=bounds.north - self.y1 * bounds.height,
        )

    @classmethod
    def from_lonlat(cls, bounds: GeoBounds, west, south, east, north) -> "Viewport":
        """Diğer uygulamanın harita görünümünü (boylam/enlem) viewport'a çevirir."""
        return cls(
            (west - bounds.west) / bounds.width,
            (bounds.north - north) / bounds.height,
            (east - bounds.west) / bounds.width,
            (bounds.north - south) / bounds.height,
        )
