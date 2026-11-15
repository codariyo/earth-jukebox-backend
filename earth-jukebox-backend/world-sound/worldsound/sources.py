"""
Harita veri kaynakları.

Her kaynak MapSource arayüzünü uygular ve load() ile bir MapData döndürür.
Yeni bir veri kaynağı (başka bir API, veritabanı, kamera...) eklemek için
MapSource'tan türetip load() yazmak yeterlidir.

    ImageFileSource  - diskteki PNG / JPEG
    ArraySource      - bellekteki numpy dizisi veya PIL görüntüsü (entegrasyon)
    NasaGibsSource   - NASA GIBS WMS servisinden canlı uydu katmanı
"""

import io
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import numpy as np
from PIL import Image

from .map_data import GeoBounds, MapData


class MapSource(ABC):
    """Tüm harita kaynaklarının ortak arayüzü."""

    @abstractmethod
    def load(self) -> MapData:
        """Veriyi okuyup MapData olarak döndürür."""

    @property
    def name(self) -> str:
        return self.__class__.__name__


# ===========================================================================
class ImageFileSource(MapSource):
    """Diskteki görüntü dosyası. PNG'deki şeffaflık "ölçüm yok" olarak korunur."""

    EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")

    def __init__(self, path: str, bounds: GeoBounds = GeoBounds()):
        self.path = path
        self.bounds = bounds

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    def load(self) -> MapData:
        with Image.open(self.path) as img:
            img.load()
            return MapData.from_pil(img, self.bounds, self.name, {"source": "file", "path": self.path})


class ArraySource(MapSource):
    """Bellekteki görüntü (numpy dizisi veya PIL). Başka uygulamadan veri almak için."""

    def __init__(self, image, bounds: GeoBounds = GeoBounds(), name: str = "bellek"):
        self.image = image
        self.bounds = bounds
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def load(self) -> MapData:
        if isinstance(self.image, Image.Image):
            return MapData.from_pil(self.image, self.bounds, self._name, {"source": "array"})
        return MapData(np.asarray(self.image), self.bounds, self._name, {"source": "array"})


# ===========================================================================
@dataclass(frozen=True)
class GibsLayer:
    """NASA GIBS katman tanımı."""
    key: str
    title: str
    layer_id: str
    theme: str
    period: str          # verinin güncellenme sıklığı (bilgi amaçlı)
    diverging: bool = False   # mavi-beyaz-kırmızı ıraksak skala mı (ColorPitchMapper.diverging)


# Katman adları NASA GIBS GetCapabilities belgesinden doğrulanmıştır.
GIBS_LAYERS = [
    GibsLayer("truecolor", "Dünya - Gerçek Renk (MODIS Terra)",
              "MODIS_Terra_CorrectedReflectance_TrueColor", "renkler", "günlük"),
    GibsLayer("land_temp", "Kara Yüzey Sıcaklığı - Gündüz (MODIS, 8 günlük)",
              "MODIS_Terra_L3_Land_Surface_Temp_8Day_Day", "sıcaklık", "8 günlük"),
    GibsLayer("sea_temp", "Deniz Yüzeyi Sıcaklığı (GHRSST MUR)",
              "GHRSST_L4_MUR_Sea_Surface_Temperature", "sıcaklık", "günlük"),
    GibsLayer("sea_temp_anom", "Deniz Sıcaklığı Değişimi / Anomali (GHRSST MUR)",
              "GHRSST_L4_MUR_Sea_Surface_Temperature_Anomalies", "sıcaklık değişimi", "günlük", True),
    GibsLayer("currents_zonal", "Okyanus Akıntıları - Doğu/Batı (OSCAR)",
              "OSCAR_Sea_Surface_Currents_Zonal", "okyanus akıntıları", "5 günlük (2024-07'ye kadar)", True),
    GibsLayer("currents_merid", "Okyanus Akıntıları - Kuzey/Güney (OSCAR)",
              "OSCAR_Sea_Surface_Currents_Meridional", "okyanus akıntıları", "5 günlük (2024-07'ye kadar)", True),
    GibsLayer("ndvi", "Bitki Örtüsü - NDVI (MODIS, 16 günlük)",
              "MODIS_Terra_L3_NDVI_16Day", "bitki örtüsü", "16 günlük"),
    GibsLayer("precip", "Yağış Hızı (IMERG)",
              "IMERG_Precipitation_Rate", "yağış", "günlük"),
    GibsLayer("air_temp", "Küresel Hava Sıcaklığı - 2 m (MERRA-2, aylık)",
              "MERRA2_2m_Air_Temperature_Monthly", "küresel sıcaklık", "aylık"),
]


class NasaGibsSource(MapSource):
    """
    NASA GIBS WMS (EPSG:4326) kaynağı.

    date=None bırakılırsa TIME parametresi gönderilmez ve GIBS her katmanın
    EN SON MEVCUT verisini verir. (Katmanların son veri tarihleri farklıdır;
    ör. OSCAR akıntıları 2024-07'de biter. Sabit bir tarih çoğu katmanda boş
    görüntü döndürürdü.)

    bounds ile dünyanın yalnız bir bölgesi istenebilir; yakınlaştırılan bölge
    bu yolla daha yüksek çözünürlükte çekilir.
    """

    ENDPOINT = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"

    def __init__(self, layer_id: str, date: Optional[str] = None,
                 bounds: GeoBounds = GeoBounds(), width: int = 2048,
                 height: Optional[int] = None, timeout: float = 60.0):
        self.layer_id = layer_id
        self.date = date or None
        self.bounds = bounds
        self.width = int(width)
        # en-boy oranını coğrafi kutuya göre koru (bozulmasın)
        self.height = int(height or max(2, round(width * bounds.height / bounds.width)))
        self.timeout = timeout

    @property
    def name(self) -> str:
        return f"NASA {self.layer_id}" + (f" {self.date}" if self.date else "")

    def url(self) -> str:
        q = {
            "SERVICE": "WMS", "REQUEST": "GetMap", "VERSION": "1.1.1",
            "LAYERS": self.layer_id, "STYLES": "", "SRS": "EPSG:4326",
            "BBOX": ",".join(f"{v:.6f}" for v in self.bounds.as_bbox()),
            "WIDTH": str(self.width), "HEIGHT": str(self.height),
            "FORMAT": "image/png", "TRANSPARENT": "TRUE",
        }
        if self.date:
            q["TIME"] = self.date
        return self.ENDPOINT + "?" + urllib.parse.urlencode(q)

    def _download(self, attempts: int = 3):
        """Geçici ağ hatalarında (bağlantı kesildi, zaman aşımı) birkaç kez dener."""
        req = urllib.request.Request(self.url(), headers={"User-Agent": "WorldSound/1.0"})
        last = None
        for i in range(attempts):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.headers.get("Content-Type", ""), resp.read()
            except urllib.error.HTTPError:
                raise                                   # sunucu cevabı: tekrar denemek anlamsız
            except (urllib.error.URLError, OSError) as ex:
                last = ex
                time.sleep(1.5 * (i + 1))
        raise RuntimeError(f"NASA GIBS'e bağlanılamadı ({attempts} deneme): {last}")

    def load(self) -> MapData:
        ctype, body = self._download()
        if "image" not in ctype:
            # GIBS hata durumunda XML döner (yanlış katman adı, veri olmayan tarih...)
            raise RuntimeError("NASA GIBS görüntü yerine hata döndürdü: "
                               + body[:300].decode("utf-8", "ignore"))
        img = Image.open(io.BytesIO(body))
        img.load()
        diverging = any(l.diverging for l in GIBS_LAYERS if l.layer_id == self.layer_id)
        data = MapData.from_pil(img, self.bounds, self.name,
                                {"source": "gibs", "layer": self.layer_id, "date": self.date,
                                 "diverging": diverging})
        if float(data.rgba[:, :, 3].max()) == 0.0:
            raise RuntimeError("Bu katman / tarih / bölge için NASA'da veri yok (tamamen boş görüntü).")
        return data
