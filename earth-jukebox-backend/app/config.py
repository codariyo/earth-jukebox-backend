"""Tema ayarlari: her tema bir GIBS katmanina ve bir enstrumana karsilik gelir.

GIBS API ANAHTARI ISTEMEZ. Asagidaki "layer" degerleri NASA'nin katman adlaridir.
Katman adlari zamanla degisebilir -> `python scripts/check_layers.py` ile dogrula.
Olmayan bir katman cikarsa sadece buradaki "layer" degerini degistir.

cadence (tarih davranisi):
  "daily"   -> her gun veri var
  "8day"    -> 8 gunde bir; tarih en yakin 8 gunluk donemin basina cekilir
  "monthly" -> ayda bir; tarih ayin 1'ine cekilir
  "static"  -> tarih yok (sabit harita)

feature (goruntuden deger cikarma yontemi):
  "colormap"   -> GIBS renk haritasi ile GERCEK deger (Kelvin, mm/saat ...). En dogrusu.
                  Renk haritasi indirilemezse fallback_feature kullanilir.
  "hue"        -> renk tonu tahmini: mavi = dusuk, kirmizi = yuksek
  "brightness" -> parlaklik: koyu = dusuk, acik = yuksek (gercek renkli goruntu icin)
"""
import os
import sys
from pathlib import Path

try:  # .env dosyasi varsa yukle (zorunlu degil)
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # paket yoksa ya da .env bulunamazsa sessizce devam et
    pass

# ---------- NASA GIBS uc noktalari (gibs-api-docs/python-usage sayfasindaki) ----------
GIBS_ROOT = "https://gibs.earthdata.nasa.gov"
GIBS_WMS_URL = f"{GIBS_ROOT}/wms/epsg4326/best/wms.cgi"  # geriye donuk ad (check_layers.py)
GIBS_WMS_TEMPLATE = GIBS_ROOT + "/wms/epsg{epsg}/best/wms.cgi"
GIBS_WMTS_TEMPLATE = GIBS_ROOT + "/wmts/epsg{epsg}/best/wmts.cgi"
GIBS_WMTS_TILE_TEMPLATE = (
    GIBS_ROOT + "/wmts/epsg{epsg}/best/{layer}/default/{time}/{tms}/{z}/{row}/{col}.{ext}"
)
GIBS_COLORMAP_TEMPLATE = GIBS_ROOT + "/colormaps/v1.3/{name}.xml"
GIBS_LEGEND_TEMPLATE = GIBS_ROOT + "/legends/{name}_H.png"
EONET_EVENTS_URL = "https://eonet.gsfc.nasa.gov/api/v3/events"  # sayfadaki "harici servis" ornegi

NASA_API_KEY = os.getenv("NASA_API_KEY", "")  # GIBS icin GEREKMEZ


def _default_cache_dir() -> str:
    # exe olarak calisirken calisma klasoru belirsiz olabilir -> kullanici klasorune yaz
    if getattr(sys, "frozen", False):
        base = os.getenv("LOCALAPPDATA") or str(Path.home())
        return str(Path(base) / "EarthJukebox" / "cache")
    return "cache"


CACHE_DIR = os.getenv("CACHE_DIR") or _default_cache_dir()

# ---------- sunucu ----------
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "3000"))

# ---------- ag / goruntu ayarlari ----------
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "60"))
# Okuma zaman asimi (veri gelmeden beklenen en uzun sure). GIBS bazen bir istegi asili birakiyor; ayni istek
# yeniden atilinca 2-4 sn'de geliyor (olculdu 2026-11-15). 60 sn beklemek yerine 20 sn'de kesip yeniden dene.
# 4096 dokuda GIBS ~8 sn'de yanit vermeye baslar -> 20 sn guvenli.
HTTP_READ_TIMEOUT = float(os.getenv("HTTP_READ_TIMEOUT", "20"))
CAPABILITIES_TTL_HOURS = float(os.getenv("CAPABILITIES_TTL_HOURS", "12"))
# Ayni anda en fazla GIBS istegi. 4 -> 8 (2026-11-15): aralik kareleri siraya giriyordu. Olcum (12 kare, 2048,
# bos onbellek): paralel 3 -> 27.6 sn, paralel 12 -> 5.8 sn. GIBS yanit suresi kare basina 1-5 sn, degisken.
MAX_PARALLEL_GIBS = int(os.getenv("MAX_PARALLEL_GIBS", "8"))
DEFAULT_WIDTH = 1024
MAX_WIDTH = 2048
# /api/texture (3D kure / 2D harita dokusu) icin ust sinir. 4096: GIBS'te ~8 sn, 8192: ~22 sn ve
# katman basina ~66 MB (olculdu, 2026-11-15) -> pratik degil. Bkz. CONTEXT.md Faz 3.
TEXTURE_MAX_WIDTH = 4096
MAX_FRAMES = 12

# Varsayilan bolge: Turkiye  (minLon, minLat, maxLon, maxLat)
DEFAULT_BBOX = (25.0, 35.0, 45.0, 43.0)
WORLD_BBOX = (-180.0, -90.0, 180.0, 90.0)

# Hazir bolgeler: ?region=dunya  (bbox verilirse bbox kazanir)
REGIONS = {
    "dunya": ("Dünya", WORLD_BBOX),
    "turkiye": ("Türkiye", DEFAULT_BBOX),
    "avrupa": ("Avrupa", (-25.0, 34.0, 45.0, 72.0)),
    "akdeniz": ("Akdeniz", (-6.0, 30.0, 37.0, 46.0)),
    "kuzey_amerika": ("Kuzey Amerika", (-170.0, 10.0, -50.0, 75.0)),
    "guney_amerika": ("Güney Amerika", (-90.0, -60.0, -30.0, 15.0)),
    "afrika": ("Afrika", (-20.0, -37.0, 55.0, 38.0)),
    "asya": ("Asya", (40.0, -10.0, 150.0, 60.0)),
    "avustralya": ("Avustralya", (110.0, -45.0, 160.0, -8.0)),
    "amazon": ("Amazon", (-75.0, -15.0, -45.0, 5.0)),
    "kuzey_kutbu": ("Kuzey Kutbu", (-180.0, 60.0, 180.0, 90.0)),
}

# Uygulamada ve /api/overview'da gosterilen 6 ana harita (sira = ekran sirasi)
MAIN_THEMES = [
    "dunya_renkleri",
    "sicaklik",
    "okyanus_akinti",
    "bitki",
    "yagis",
    "kuresel_isinma",
]

# Kiyi cizgisi (zamansiz, seffaf) - her haritanin ustune yerel olarak bindirilir
COASTLINE_LAYER = "Coastlines_15m"
# EONET olaylari icin taban harita (zamansiz)
BASEMAP_LAYER = "BlueMarble_NextGeneration"

THEMES = {
    # --- 1. Dunya renkleri (gercek renkli uydu goruntusu) ---
    # Tarih araligi check_layers.py ciktisindan: 2000-02-24 -> bugun
    "dunya_renkleri": {
        "title": "Dünya Renkleri",
        "layer": "MODIS_Terra_CorrectedReflectance_TrueColor",
        "cadence": "daily",
        "since": "2000-02-24",
        "feature": "brightness",
        "instrument": "pad",
        "scale": "major_pentatonic",
        "octave": 4,
        "low_word": "koyu (okyanus/orman)",
        "high_word": "parlak (bulut/kar/çöl)",
        # Gercek renkli goruntu bir olcum degil, gorsel. Kontrast germek serbest.
        "normalize": True,
    },
    # --- 2. Sicaklik degisimi (kara yuzey sicakligi) ---
    "sicaklik": {
        "title": "Sıcaklık Değişimi",
        "layer": "MODIS_Terra_Land_Surface_Temp_Day",
        "cadence": "daily",
        "since": "2000-02-24",
        "feature": "colormap",  # gercek deger; olmazsa renk tonu tahmini
        "fallback_feature": "hue",
        "instrument": "lead",
        "scale": "major_pentatonic",
        "octave": 4,
        "low_word": "serin",
        "high_word": "sıcak",
    },
    # --- 3. Okyanus sicakligi (MUR25 = 0.25 derece, hizli. MUR = 1km, agir) ---
    "okyanus": {
        "title": "Okyanus Sıcaklığı",
        "layer": "GHRSST_L4_MUR25_Sea_Surface_Temperature",
        "cadence": "daily",
        "since": "2002-09-01",
        "feature": "colormap",  # gercek deger; olmazsa renk tonu tahmini
        "fallback_feature": "hue",
        "instrument": "strings",
        "scale": "dorian",
        "octave": 3,
        "low_word": "soğuk su",
        "high_word": "sıcak su",
    },
    # --- 3b. Okyanus akintisi (gercek akinti verisi!) ---
    # Zonal = dogu-bati yonu. Meridional = kuzey-guney yonu.
    # Deger iki yonlu: ortada durgun, iki uca gidince hizli akinti.
    "okyanus_akinti": {
        "title": "Okyanus Akıntıları",
        "layer": "OSCAR_Sea_Surface_Currents_Zonal",
        "cadence": "daily",
        # GIBS WMTS capabilities (2026-11-14): 2014-10-22 -> 2024-07-17, 5 gunluk.
        # Asil tarih listesi calisma aninda capabilities'ten okunur; bu sadece yedek.
        "since": "2014-10-22",
        "until": "2024-07-17",
        "feature": "colormap",  # gercek deger; olmazsa renk tonu tahmini
        "fallback_feature": "hue",
        "instrument": "pad",
        "scale": "dorian",
        "octave": 3,
        "low_word": "batıya akan",
        "high_word": "doğuya akan",
    },
    # --- 4. Bitki ortusu ---
    "bitki": {
        "title": "Bitki Örtüsü",
        "layer": "MODIS_Terra_NDVI_8Day",
        "cadence": "8day",
        # DIKKAT: Bu katman sadece son ~2 yili tutuyor. Eski tarih calismaz.
        "since": "2025-02-12",
        "feature": "colormap",  # gercek deger; olmazsa renk tonu tahmini
        "fallback_feature": "hue",
        "instrument": "bell",
        "scale": "major_pentatonic",
        "octave": 5,
        "low_word": "çıplak/kurak",
        "high_word": "yeşil/yoğun bitki",
    },
    # --- 5. Yagis ---
    "yagis": {
        "title": "Yağış",
        "layer": "IMERG_Precipitation_Rate",
        "cadence": "daily",
        "since": "2000-06-01",
        "feature": "colormap",  # gercek deger; olmazsa renk tonu tahmini
        "fallback_feature": "hue",
        "instrument": "pluck",
        "scale": "minor_pentatonic",
        "octave": 5,
        "low_word": "kuru",
        "high_word": "şiddetli yağış",
    },
    # --- 6. Kuresel isinma (aylik, 1980'den bugune) ---
    "kuresel_isinma": {
        "title": "Küresel Sıcaklık (Aylık)",
        "layer": "MERRA2_2m_Air_Temperature_Monthly",
        "cadence": "monthly",
        "since": "1980-01-01",
        # Son veri 2026-08. Daha yeni tarih istenirse buna cekilir.
        "until": "2026-08-01",
        "feature": "colormap",  # gercek deger; olmazsa renk tonu tahmini
        "fallback_feature": "hue",
        "instrument": "bass",
        "scale": "dorian",
        "octave": 2,
        "low_word": "soğuk",
        "high_word": "sıcak",
    },
    # --- Bonus: normalden sapma. Isinmayi anlatmak icin en etkili katman. ---
    "isinma_anomali": {
        "title": "Sıcaklık Anomalisi (Normalden Sapma)",
        "layer": "GHRSST_L4_MUR25_Sea_Surface_Temperature_Anomalies",
        "cadence": "daily",
        "since": "2002-09-01",
        "feature": "colormap",  # gercek deger; olmazsa renk tonu tahmini
        "fallback_feature": "hue",
        "instrument": "lead",
        "scale": "whole_tone",  # tedirgin edici ses: anormallik duyulsun
        "octave": 5,
        "low_word": "normalden soğuk",
        "high_word": "normalden sıcak",
    },
}

# check_layers.py bunlarin tarih araligini da yazdirir.
DENEYSEL_KATMANLAR = [
    "OSCAR_Sea_Surface_Currents_Meridional",  # kuzey-guney akinti
    "GHRSST_L4_MUR_Sea_Surface_Temperature",  # 1km, cok daha detayli ama yavas
    "MODIS_Terra_Thermal_Anomalies_All",  # yanginlar -> vurmali calgi fikri
]
