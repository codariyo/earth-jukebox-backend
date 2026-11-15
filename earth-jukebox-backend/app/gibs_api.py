"""NASA GIBS istemcisi: https://nasa-gibs.github.io/gibs-api-docs/python-usage/ sayfasindaki
servislerin hepsi burada, OWSLib yerine httpx ile (async, paralel istek atabilmek icin).

Sayfadaki baglanti                         -> bu moduldeki fonksiyon
-----------------------------------------------------------------------------
WMS GetMap (EPSG:4326, 1.1.1)               -> wms_getmap(..., epsg=4326)
WMS GetMap (EPSG:3857 / 3413 / 3031, 1.3.0) -> wms_getmap(..., epsg=3413 ...)
Coklu katman / bindirme (Reference, Coast)  -> wms_getmap(layers=[a, b, ...])
WMTS GetCapabilities                        -> wmts_capabilities_xml()
WMTS GetTile (REST)                         -> wmts_tile()
Renk haritasi XML (colormaps/v1.3)          -> fetch_text(colormap_url)
Lejant (legends/..._H.png)                  -> legend_png()
EONET olaylari (harici servis ornegi)       -> eonet_events()

Kurallar:
  * Agdaki HER istek terminale kirmizi + ------ ayracli yazilir (logger.py).
  * Goruntuler diske onbelleklenir (ayni istegi NASA'ya tekrar atmayiz).
  * GIBS hata durumunda goruntu yerine XML dondurur; bunu yakalayip GibsError atariz.
"""
import asyncio
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

import httpx

from .config import (
    CACHE_DIR,
    CAPABILITIES_TTL_HOURS,
    EONET_EVENTS_URL,
    GIBS_LEGEND_TEMPLATE,
    GIBS_WMS_TEMPLATE,
    GIBS_WMTS_TEMPLATE,
    GIBS_WMTS_TILE_TEMPLATE,
    HTTP_READ_TIMEOUT,
    HTTP_TIMEOUT,
    MAX_PARALLEL_GIBS,
)
from .logger import log_nasa_request

HEADERS = {"User-Agent": "EarthJukebox/1.0 (+NASA GIBS python-usage)"}

# Projeksiyonlarin tam kapsami (sayfadaki orneklerle ayni degerler)
PROJECTION_EXTENTS = {
    4326: (-180.0, -90.0, 180.0, 90.0),
    3857: (-20037508.34, -20037508.34, 20037508.34, 20037508.34),
    3413: (-4194304.0, -4194304.0, 4194304.0, 4194304.0),  # Kuzey kutbu
    3031: (-4194304.0, -4194304.0, 4194304.0, 4194304.0),  # Guney kutbu
}


class GibsError(Exception):
    """NASA servisi goruntu/veri yerine hata dondurdugunde."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


# ---------- tekil httpx istemcisi (event loop basina) ----------
_client: Optional[httpx.AsyncClient] = None
_client_loop: Any = None
_sem: Optional[asyncio.Semaphore] = None
_sem_loop: Any = None


def get_client() -> httpx.AsyncClient:
    global _client, _client_loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if _client is None or _client.is_closed or _client_loop is not loop:
        timeout = httpx.Timeout(HTTP_TIMEOUT, connect=10.0, read=HTTP_READ_TIMEOUT)
        _client = httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=HEADERS)
        _client_loop = loop
    return _client


def _semaphore() -> asyncio.Semaphore:
    """Ayni anda en fazla MAX_PARALLEL_GIBS istek (NASA'yi bogmamak icin)."""
    global _sem, _sem_loop
    loop = asyncio.get_running_loop()
    if _sem is None or _sem_loop is not loop:
        _sem = asyncio.Semaphore(MAX_PARALLEL_GIBS)
        _sem_loop = loop
    return _sem


async def close_client() -> None:
    global _client, _client_loop
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None
    _client_loop = None


# ---------- disk onbellegi ----------
# Harita goruntuleri (wms/wmts) katman ve tarih klasorlerine ayrilir:
#     <CACHE_DIR>/wms/<katman>/<YYYY-MM-DD | _tarihsiz>/<sha1>.png
# Boylece uygulama kapanirken prune_map_cache() eski tarihleri tek tek klasor olarak silebilir.
MAP_KINDS = ("wms", "wmts")
STATIC_DIR = "_tarihsiz"          # zamansiz katmanlar (Blue Marble, kiyi cizgisi)
_SESSION_START = time.time()      # bu oturumda kullanilan tarihsiz dosyalari ayirt etmek icin


def _cache_path(kind: str, url: str, ext: str) -> Path:
    key = hashlib.sha1(url.encode()).hexdigest()
    return Path(CACHE_DIR) / kind / f"{key}.{ext}"


def _safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.+-]", "_", text)[:120] or "_"


def _map_cache_path(kind: str, url: str, ext: str, layers: list[str], day: str | None) -> Path:
    key = hashlib.sha1(url.encode()).hexdigest()
    folder = _safe_name(day) if day else STATIC_DIR
    return Path(CACHE_DIR) / kind / _safe_name("+".join(layers)) / folder / f"{key}.{ext}"


def _remove(path: Path) -> int:
    """Dosyayi siler, bosalan baytlari dondurur (kilitli/eksikse 0)."""
    try:
        size = path.stat().st_size
        path.unlink()
        return size
    except OSError:
        return 0


def prune_map_cache() -> dict:
    """Uygulama kapanirken cagrilir (main.py lifespan). Yalnizca harita goruntulerine dokunur:

      * Tarihli katmanlar: her katman icin SADECE en yeni tarih klasoru kalir, eskiler silinir.
        (Acilista tarih "dun" oldugu icin bir sonraki acilis bu dosyalardan hizli baslar.)
      * Tarihsiz katmanlar (Blue Marble, kiyi): yalnizca bu oturumda kullanilanlar kalir;
        zoom'da uretilen eski bolge goruntuleri silinir.
      * Eski duz duzende (katman klasoru olmayan) kalan dosyalar silinir.
    Renk haritalari, capabilities, lejant ve EONET onbellegi korunur (kucuk, tarihten bagimsiz).
    """
    removed, freed = 0, 0
    for kind in MAP_KINDS:
        root = Path(CACHE_DIR) / kind
        if not root.is_dir():
            continue
        for entry in list(root.iterdir()):
            if entry.is_file():                      # eski duzen (Faz 0-5)
                freed += _remove(entry)
                removed += 1
                continue
            dated = sorted(d for d in entry.iterdir() if d.is_dir() and d.name != STATIC_DIR)
            old = [f for d in dated[:-1] for f in d.rglob("*") if f.is_file()]
            static = entry / STATIC_DIR
            if static.is_dir():
                for f in static.iterdir():
                    try:
                        stale = f.is_file() and f.stat().st_mtime < _SESSION_START
                    except OSError:
                        stale = False
                    if stale:
                        old.append(f)
            for f in old:
                freed += _remove(f)
                removed += 1
            for d in sorted(entry.rglob("*"), key=lambda p: len(p.parts), reverse=True) + [entry]:
                if d.is_dir():
                    try:
                        d.rmdir()                     # yalnizca bossa silinir
                    except OSError:
                        pass
    return {"removed": removed, "freed_mb": round(freed / 1024 / 1024, 1)}


def _fresh(path: Path, ttl_hours: float | None) -> bool:
    if not path.exists():
        return False
    if ttl_hours is None:
        return True
    return (time.time() - path.stat().st_mtime) < ttl_hours * 3600


async def _get(url: str, params: dict | None, label: str) -> httpx.Response:
    full = str(httpx.URL(url, params=params)) if params else url
    log_nasa_request(full, label)
    async with _semaphore():
        for attempt in (1, 2, 3):
            try:
                resp = await get_client().get(url, params=params)
                # GIBS gecici sunucu hatasi (502/503/504, asiri yuk) -> kisa beklemeyle tekrar dene
                if resp.status_code in (500, 502, 503, 504) and attempt < 3:
                    log_nasa_request(full, f"{label} (GIBS HTTP {resp.status_code}, tekrar {attempt + 1}/3)")
                    await asyncio.sleep(0.5 * attempt)
                    continue
                return resp
            except httpx.TransportError as exc:  # ReadTimeout dahil: asili istek kesilir, yeniden atilir
                # Kopan keep-alive baglantisi / anlik baglanti reddi -> artan beklemeyle tekrar dene
                if attempt < 3:
                    await asyncio.sleep(0.6 * attempt)
                    continue
                raise GibsError(f"NASA servisine baglanilamadi ({type(exc).__name__}): {exc} — {full}") from exc
            except httpx.HTTPError as exc:
                raise GibsError(f"NASA servisine baglanilamadi ({type(exc).__name__}): {exc} — {full}") from exc
    raise GibsError(f"NASA servisine baglanilamadi — {full}")


def _check_image(resp: httpx.Response, what: str) -> bytes:
    ctype = resp.headers.get("content-type", "")
    if resp.status_code != 200 or not ctype.startswith("image/") or not resp.content:
        # Yanlis katman adi / tarih / projeksiyon -> GIBS XML hata metni dondurur
        detail = resp.text[:300].strip() if "xml" in ctype or "text" in ctype else ""
        status = 404 if resp.status_code in (400, 404) else 502
        raise GibsError(f"{what}: GIBS goruntu dondurmedi (HTTP {resp.status_code}). {detail}", status)
    return resp.content


async def _cached_image(kind: str, url: str, params: dict | None, label: str, ext: str = "img",
                        layers: list[str] | None = None, day: str | None = None) -> bytes:
    full = str(httpx.URL(url, params=params)) if params else url
    path = _map_cache_path(kind, full, ext, layers, day) if layers else _cache_path(kind, full, ext)
    if path.exists():
        log_nasa_request(full, f"{label} (ONBELLEK)")
        if layers and not day:
            try:
                os.utime(path)    # tarihsiz dosya bu oturumda kullanildi -> kapanista silinmesin
            except OSError:
                pass
        return path.read_bytes()
    # Ayni goruntu ayni anda iki kez istenirse (orn. aralik on-yuklemesi + ekrandaki kare) NASA'ya TEK istek gider
    task = _inflight.get(path)
    if task is None or task.get_loop() is not asyncio.get_running_loop():
        task = asyncio.ensure_future(_download(url, params, label, path))
        _inflight[path] = task
        task.add_done_callback(lambda t, p=path: _inflight.pop(p, None) if _inflight.get(p) is t else None)
    return await asyncio.shield(task)   # bir istemci vazgecse de indirme biter, digerleri kullanir


_inflight: dict = {}   # onbellek yolu -> suren indirme (asyncio.Task)


async def _download(url: str, params: dict | None, label: str, path: Path) -> bytes:
    data = _check_image(await _get(url, params, label), label)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


async def fetch_text(url: str, label: str, ttl_hours: float | None = None) -> str:
    """XML/metin indirir; diskte taze kopya varsa onu kullanir.

    Ag hatasinda eski (bayat) kopya varsa onu dondurur: GIBS gecici olarak
    ulasilamazsa uygulama yine calisir.
    """
    path = _cache_path("text", url, "xml")
    if _fresh(path, ttl_hours):
        return path.read_text(encoding="utf-8")
    try:
        resp = await _get(url, None, label)
        if resp.status_code != 200:
            raise GibsError(f"{label}: HTTP {resp.status_code}", 404 if resp.status_code == 404 else 502)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(resp.text, encoding="utf-8")
        return resp.text
    except GibsError:
        if path.exists():
            return path.read_text(encoding="utf-8")
        raise


# ---------- WMS GetMap ----------
def wms_params(layers: list[str], bbox, width: int, height: int, time: str | None,
               epsg: int = 4326, fmt: str = "image/png", transparent: bool = True) -> dict:
    """Sayfadaki GetMap parametreleri.

    EPSG:4326 icin WMS 1.1.1 kullaniyoruz: BBOX sirasi minLon,minLat,maxLon,maxLat.
    (1.3.0'da EPSG:4326 eksen sirasi ters -> sayfadaki "bbox=-90,-180,90,180" ornegi.)
    Diger projeksiyonlar icin sayfadaki gibi 1.3.0 + CRS + metre cinsinden BBOX.
    """
    params = {
        "SERVICE": "WMS",
        "REQUEST": "GetMap",
        "LAYERS": ",".join(layers),
        "STYLES": "",
        "BBOX": ",".join(f"{v:g}" for v in bbox),
        "WIDTH": str(width),
        "HEIGHT": str(height),
        "FORMAT": fmt,
        "TRANSPARENT": "TRUE" if transparent else "FALSE",
    }
    if epsg == 4326:
        params.update({"VERSION": "1.1.1", "SRS": "EPSG:4326"})
    else:
        params.update({"VERSION": "1.3.0", "CRS": f"EPSG:{epsg}"})
    if time:
        params["TIME"] = time
    return params


async def wms_getmap(layers: list[str], bbox, width: int, height: int, time: str | None = None,
                     epsg: int = 4326, fmt: str = "image/png", transparent: bool = True) -> bytes:
    url = GIBS_WMS_TEMPLATE.format(epsg=epsg)
    params = wms_params(layers, bbox, width, height, time, epsg, fmt, transparent)
    label = f"NASA GIBS WMS GetMap EPSG:{epsg} ({'+'.join(layers)} {time or 'zamansiz'})"
    return await _cached_image("wms", url, params, label, "png", layers=layers, day=time)


# ---------- WMTS ----------
async def wmts_capabilities_xml(epsg: int = 4326) -> str:
    url = GIBS_WMTS_TEMPLATE.format(epsg=epsg) + "?SERVICE=WMTS&REQUEST=GetCapabilities"
    return await fetch_text(url, f"NASA GIBS WMTS GetCapabilities EPSG:{epsg}", CAPABILITIES_TTL_HOURS)


async def wmts_tile(layer: str, time: str | None, tms: str, z: int, row: int, col: int,
                    ext: str, epsg: int = 4326) -> bytes:
    url = GIBS_WMTS_TILE_TEMPLATE.format(
        epsg=epsg, layer=layer, time=time or "default", tms=tms, z=z, row=row, col=col, ext=ext
    )
    return await _cached_image("wmts", url, None, f"NASA GIBS WMTS GetTile ({layer})", ext,
                               layers=[layer], day=time)


# ---------- lejant ----------
async def legend_png(url: str) -> bytes:
    return await _cached_image("legend", url, None, "NASA GIBS lejant", "png")


def legend_url_for(name: str) -> str:
    return GIBS_LEGEND_TEMPLATE.format(name=name)


# ---------- EONET (dogal olaylar) ----------
async def eonet_events(start: str, end: str, categories: list[str] | None = None) -> dict:
    params: dict[str, str] = {"start": start, "end": end, "status": "all"}
    if categories:
        params["category"] = ",".join(categories)
    full = str(httpx.URL(EONET_EVENTS_URL, params=params))
    path = _cache_path("eonet", full, "json")
    if _fresh(path, 6):
        return json.loads(path.read_text(encoding="utf-8"))
    resp = await _get(EONET_EVENTS_URL, params, "NASA EONET olaylari")
    if resp.status_code != 200:
        raise GibsError(f"EONET hata dondurdu (HTTP {resp.status_code})")
    data = resp.json()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return data
