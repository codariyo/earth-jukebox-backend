"""Earth Jukebox API — NASA GIBS goruntu servisi.

Calistir:  python -m app.main            (ya da: uvicorn app.main:app --port 3000)
Dokuman:   http://127.0.0.1:3000/docs

KURAL: Her GET istegi GORSEL dondurur (PNG, animasyon icin GIF, karo icin PNG/JPEG).
Hatalar da gorsel olarak doner (hata mesaji yazili PNG + dogru HTTP kodu).
Istisnalar (JSON): /health, /api/themes, /api/sound/*, ve Faz 5 ses kontrolu /api/audio/*
(world-sound muzik sistemi; bkz. app/audio.py ve CONTEXT.md Faz 5).
"""
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import audio, maps, render, sound, speech
from .config import (DEFAULT_WIDTH, HOST, MAIN_THEMES, MAX_FRAMES, MAX_WIDTH, PORT, REGIONS,
                     TEXTURE_MAX_WIDTH, THEMES)
from .gibs_api import GibsError, close_client, prune_map_cache
from .logger import log_nasa_request

PNG = "image/png"
GIF = "image/gif"
IMG_RESPONSES = {200: {"content": {PNG: {}}, "description": "Görsel"}}


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    audio.bridge.close()      # ses kartını bırak (Faz 5)
    await close_client()
    # Harita önbelleği: katman başına yalnızca en yeni tarih kalır, eskiler silinir (CONTEXT.md)
    try:
        res = prune_map_cache()
        print(f"[ONBELLEK] kapanista {res['removed']} eski harita silindi ({res['freed_mb']} MB)", flush=True)
    except Exception as exc:  # temizlik başarısız olsa da kapanış sürsün
        print(f"[ONBELLEK] temizlik yapilamadi: {exc}", flush=True)


app = FastAPI(
    title="Earth Jukebox API",
    description=(
        "NASA GIBS uydu haritaları. Bütün GET uç noktaları **görsel** döndürür.\n\n"
        f"Temalar: {', '.join(THEMES)}\n\nBölgeler: {', '.join(REGIONS)}"
    ),
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])


@app.middleware("http")
async def terminal_request_logger(request: Request, call_next):
    # /api/audio/state calarken saniyede ~8 kez sorgulanir: loglanirsa terminal/log dosyasi sisiyor (Faz 5)
    # /api/speech: adres uzun Türkçe metin taşır, log'u şişirmesin
    if request.url.path.startswith("/api") and request.url.path not in ("/api/audio/state", "/api/speech"):
        log_nasa_request(str(request.url), f"GELEN API ISTEGI: {request.method}")
    response = await call_next(request)
    # API görüntüleri WebView2/tarayıcı disk önbelleğine yazılmasın: arayüz zaten bellekte tutuyor
    # (eratone-data.js LRU), sunucu da diskte. Yoksa aynı haritalar ikinci kez birikiyordu (~287 MB).
    if request.url.path.startswith("/api"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


# ---------- hatalar da gorsel ----------
def _error(status: int, title: str, message: str) -> Response:
    return Response(render.error_image(status, title, message), status_code=status, media_type=PNG)


@app.exception_handler(maps.MapRequestError)
async def _map_error(_, exc: maps.MapRequestError):
    return _error(exc.status, "Geçersiz istek" if exc.status == 400 else "Bulunamadı", str(exc))


@app.exception_handler(GibsError)
async def _gibs_error(_, exc: GibsError):
    return _error(exc.status, "NASA GIBS", str(exc))


@app.exception_handler(StarletteHTTPException)
async def _http_error(_, exc: StarletteHTTPException):
    return _error(exc.status_code, "İstek", str(exc.detail))


@app.exception_handler(RequestValidationError)
async def _validation_error(_, exc: RequestValidationError):
    msgs = [f"{'.'.join(str(p) for p in e['loc'][1:])}: {e['msg']}" for e in exc.errors()]
    return _error(422, "Parametre hatası", "\n".join(msgs))


@app.exception_handler(Exception)
async def _unexpected(_, exc: Exception):
    return _error(500, "Sunucu hatası", f"{type(exc).__name__}: {exc}")


# ---------- parametre cozumleme ----------
def parse_bbox(bbox: str | None, region: str | None):
    if bbox:
        try:
            parts = tuple(float(x) for x in bbox.split(","))
        except ValueError:
            raise maps.MapRequestError("bbox biçimi: minBoylam,minEnlem,maxBoylam,maxEnlem")
        if len(parts) != 4 or parts[0] >= parts[2] or parts[1] >= parts[3]:
            raise maps.MapRequestError("bbox biçimi: minBoylam,minEnlem,maxBoylam,maxEnlem (min < max)")
        if parts[0] < -180 or parts[2] > 180 or parts[1] < -90 or parts[3] > 90:
            raise maps.MapRequestError("bbox dünya sınırları dışında (-180..180, -90..90)")
        return parts
    key = region or "dunya"
    if key not in REGIONS:
        raise maps.MapRequestError(f"Bölge yok: {key}. Seçenekler: {', '.join(REGIONS)}")
    return REGIONS[key][1]


def parse_date(d: str | None, name: str = "date") -> date:
    if not d:
        return date.today() - timedelta(days=3)  # uydu verisi birkac gun gecikmeli gelir
    try:
        return date.fromisoformat(d)
    except ValueError:
        raise maps.MapRequestError(f"{name} biçimi: YYYY-AA-GG (örnek 2026-07-01)")


RegionQ = Query(None, description=f"Hazır bölge: {', '.join(REGIONS)} (varsayılan dunya)")
BboxQ = Query(None, description="minBoylam,minEnlem,maxBoylam,maxEnlem — verilirse bölgeyi ezer")


# ---------- arayuz (Eratone) ----------
# FAZ 1: Eratone arayuzu statik HTML olarak sunulur (NiceGUI yerine). Bkz. CONTEXT.md.
# Klasor yoksa (orn. frontend'i paketlemeyen exe) mount atlanir, API yine calisir.
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend" / "static"
INDEX_HTML = FRONTEND_DIR / "eratone.html"
if FRONTEND_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index():
    if not INDEX_HTML.is_file():
        return _error(404, "Arayüz", f"Arayüz dosyası bulunamadı: {INDEX_HTML}")
    return FileResponse(INDEX_HTML, media_type="text/html")


# ---------- uc noktalar ----------
@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}


@app.get("/api/map/{theme}", responses=IMG_RESPONSES, response_class=Response, tags=["Harita"])
async def map_single(
    theme: str,
    date: str | None = Query(None, description="YYYY-AA-GG; boşsa 3 gün öncesi. Veri yoksa en yakın tarih kullanılır."),
    region: str | None = RegionQ,
    bbox: str | None = BboxQ,
    width: int = Query(DEFAULT_WIDTH, ge=128, le=MAX_WIDTH),
    legend: bool = True,
    coast: bool = True,
):
    """TEK TARİH: haritanın PNG görüntüsü (kıyı çizgisi + başlık + GIBS lejantı)."""
    png = await maps.single_map_png(theme, parse_bbox(bbox, region), width, parse_date(date), legend, coast)
    return Response(png, media_type=PNG)


@app.get("/api/map/{theme}/range", responses={200: {"content": {GIF: {}}}}, response_class=Response, tags=["Harita"])
async def map_range(
    theme: str,
    start: str = Query(..., description="Başlangıç YYYY-AA-GG"),
    end: str = Query(..., description="Bitiş YYYY-AA-GG"),
    frames: int = Query(6, ge=2, le=MAX_FRAMES, description="Kare sayısı"),
    region: str | None = RegionQ,
    bbox: str | None = BboxQ,
    width: int = Query(800, ge=128, le=MAX_WIDTH),
    coast: bool = True,
):
    """TARİH ARALIĞI (animasyon): aralıktaki değişim, kare kare GIF.

    Aralık 2 yıldan uzunsa kareler aynı mevsimden seçilir (yıllar arası değişim).
    """
    gif = await maps.range_gif(theme, parse_bbox(bbox, region), width,
                               parse_date(start, "start"), parse_date(end, "end"), frames, coast)
    return Response(gif, media_type=GIF)


@app.get("/api/map/{theme}/compare", responses=IMG_RESPONSES, response_class=Response, tags=["Harita"])
async def map_compare(
    theme: str,
    start: str = Query(..., description="Önce (YYYY-AA-GG)"),
    end: str = Query(..., description="Sonra (YYYY-AA-GG)"),
    region: str | None = RegionQ,
    bbox: str | None = BboxQ,
    width: int = Query(640, ge=128, le=1024, description="Her panelin genişliği"),
    coast: bool = True,
):
    """TARİH ARALIĞI (karşılaştırma): önce | sonra | fark haritası tek PNG'de."""
    png = await maps.compare_png(theme, parse_bbox(bbox, region), width,
                                 parse_date(start, "start"), parse_date(end, "end"), coast)
    return Response(png, media_type=PNG)


@app.get("/api/overview", responses=IMG_RESPONSES, response_class=Response, tags=["Harita"])
async def overview(
    date: str | None = None,
    region: str | None = RegionQ,
    bbox: str | None = BboxQ,
    width: int = Query(560, ge=128, le=1024, description="Her hücrenin genişliği"),
    themes: str | None = Query(None, description="Virgüllü tema listesi; boşsa 6 ana harita"),
):
    """6 ana harita tek görselde (aynı tarih)."""
    ids = [t.strip() for t in themes.split(",") if t.strip()] if themes else None
    for t in ids or []:
        maps.get_theme(t)
    png = await maps.overview_png(parse_bbox(bbox, region), width, parse_date(date), ids)
    return Response(png, media_type=PNG)


@app.get("/api/projection/{theme}", responses=IMG_RESPONSES, response_class=Response, tags=["Harita"])
async def projection(
    theme: str,
    epsg: int = Query(3413, description="4326, 3857, 3413 (Kuzey Kutbu), 3031 (Güney Kutbu)"),
    date: str | None = None,
    size: int = Query(768, ge=128, le=MAX_WIDTH),
):
    """Sayfadaki projeksiyon örnekleri: kutup ve Mercator görünümleri."""
    return Response(await maps.projection_png(theme, epsg, parse_date(date), size), media_type=PNG)


@app.get("/api/tile/{theme}/{z}/{row}/{col}", response_class=Response, tags=["GIBS ham"])
async def wmts_tile(theme: str, z: int, row: int, col: int, date: str | None = None):
    """WMTS GetTile (REST): GIBS'in ham 512x512 karosu."""
    data, media = await maps.tile(theme, z, row, col, parse_date(date))
    return Response(data, media_type=media)


@app.get("/api/legend/{theme}", responses=IMG_RESPONSES, response_class=Response, tags=["GIBS ham"])
async def legend(theme: str):
    """Katmanın GIBS lejantı (renk → değer)."""
    return Response(await maps.legend_png(theme), media_type=PNG)


@app.get("/api/events", responses=IMG_RESPONSES, response_class=Response, tags=["Harita"])
async def events(
    start: str | None = None,
    end: str | None = None,
    categories: str | None = Query(None, description="örn. wildfires,volcanoes,severeStorms"),
    width: int = Query(1200, ge=256, le=MAX_WIDTH),
):
    """NASA EONET doğal olayları Blue Marble haritası üstünde (sayfadaki harici servis örneği)."""
    e = parse_date(end, "end")
    s = parse_date(start, "start") if start else e - timedelta(days=30)
    cats = [c.strip() for c in categories.split(",") if c.strip()] if categories else None
    return Response(await maps.events_png(s, e, cats, width), media_type=PNG)


@app.get("/api/texture/{theme}", responses={200: {"content": {"image/jpeg": {}}}}, response_class=Response,
         tags=["Müzik kutusu"])
async def texture(
    theme: str,
    date: str | None = None,
    region: str | None = RegionQ,
    bbox: str | None = BboxQ,
    width: int = Query(2048, ge=128, le=TEXTURE_MAX_WIDTH),
):
    """3D küre / 2D harita dokusu: başlıksız eşdikdörtgen JPEG (Blue Marble + veri + kıyı)."""
    data, used = await sound.texture(theme, parse_date(date), width, parse_bbox(bbox, region))
    return Response(data, media_type="image/jpeg", headers={"X-Date-Used": used or "zamansiz"})


@app.get("/api/sound/{theme}", tags=["Müzik kutusu"])
async def sound_snapshot(
    theme: str,
    date: str | None = None,
    region: str | None = RegionQ,
    bbox: str | None = BboxQ,
    steps: int = Query(32, ge=4, le=128, description="Kaç vuruş (dikey şerit)"),
    melodic: bool = Query(True, description="true = bölge içi farklar geniş melodi; false = mutlak ölçek"),
):
    """SESLENDİRME (JSON): harita batıdan doğuya taranır, her şerit bir nota."""
    return await sound.snapshot(theme, parse_bbox(bbox, region), parse_date(date), steps, melodic)


@app.get("/api/sound/{theme}/timeline", tags=["Müzik kutusu"])
async def sound_timeline(
    theme: str,
    start: str = Query(..., description="Başlangıç YYYY-AA-GG"),
    end: str = Query(..., description="Bitiş YYYY-AA-GG"),
    frames: int = Query(10, ge=2, le=MAX_FRAMES),
    region: str | None = RegionQ,
    bbox: str | None = BboxQ,
):
    """ZAMAN YOLCULUĞU (JSON): her tarih için bölge ortalaması bir nota (enlem ağırlıklı)."""
    return await sound.timeline(theme, parse_bbox(bbox, region), parse_date(start, "start"),
                                parse_date(end, "end"), frames)


@app.get("/api/themes", tags=["Müzik kutusu"])
async def themes_info():
    """Temalar ve gerçek veri aralıkları (JSON) — tarih seçici için."""
    return [await sound.theme_info(t) for t in MAIN_THEMES]


# ---------- ses (Faz 5): world-sound muzik sistemi ----------
# Arayuz (frontend/static/eratone-audio.js) bu uc noktalarla app/audio.py koprusunu surer.
# Ses BU bilgisayarin hoparlorunden cikar (masaustu uygulama: sunucu ayni surecte).
class AudioSourceIn(BaseModel):
    theme: str
    date: str | None = None
    region: str | None = None
    bbox: list[float] | None = Field(None, min_length=4, max_length=4)


class AudioViewIn(BaseModel):
    west: float
    south: float
    east: float
    north: float
    restart: bool = False


class AudioPlayIn(BaseModel):
    playing: bool


class AudioLoopIn(BaseModel):
    loop: bool


class AudioInstrumentIn(BaseModel):
    key: str = Field(..., description="acoustic_guitar, electric_guitar, piano, flute, violin")
    enabled: bool | None = None
    volume: float | None = Field(None, ge=0.0, le=1.0)


class AudioEqIn(BaseModel):
    band: str = Field(..., description="bass, low_mid, mid, high_mid, treble")
    db: float = Field(..., ge=-12.0, le=12.0)


def _audio_err(exc: Exception) -> JSONResponse:
    return JSONResponse({"ok": False, "error": str(exc)}, status_code=getattr(exc, "status", 500))


@app.post("/api/audio/source", tags=["Ses"])
async def audio_source(body: AudioSourceIn):
    """Seslendirilecek harita: tema + tarih + kaynak kutu (bbox ya da bölge). Katman uygulamanın GIBS istemcisiyle çekilir."""
    try:
        bbox = parse_bbox(",".join(f"{v:g}" for v in body.bbox) if body.bbox else None, body.region)
        return await audio.bridge.load_source(body.theme, parse_date(body.date), bbox)
    except (maps.MapRequestError, GibsError) as exc:
        return _audio_err(exc)


@app.post("/api/audio/view", tags=["Ses"])
async def audio_view(body: AudioViewIn):
    """Görünen boylam/enlem kutusu: müzik yalnız bu bölgenin piksellerinden üretilir.
    restart=true (bölge değişti): tarama yeni bölgenin BAŞINDAN başlar (zoom/kaydırmada false: kaldığı yerden)."""
    return audio.bridge.set_view(body.west, body.south, body.east, body.north, body.restart)


@app.post("/api/audio/play", tags=["Ses"])
async def audio_play(body: AudioPlayIn):
    return audio.bridge.play(body.playing)


@app.post("/api/audio/loop", tags=["Ses"])
async def audio_loop(body: AudioLoopIn):
    return audio.bridge.set_loop(body.loop)


@app.post("/api/audio/instrument", tags=["Ses"])
async def audio_instrument(body: AudioInstrumentIn):
    return audio.bridge.set_instrument(body.key, body.enabled, body.volume)


@app.post("/api/audio/eq", tags=["Ses"])
async def audio_eq(body: AudioEqIn):
    return audio.bridge.set_eq(body.band, body.db)


@app.get("/api/audio/state", tags=["Ses"])
async def audio_state():
    """Tarama konumu, çalan notalar, spektrum (arayüz görselleştirmesi için, sık sorgulanır)."""
    return audio.bridge.state()


class AudioSpeedIn(BaseModel):
    factor: float = Field(..., ge=0.25, le=2.0, description="0.25x … 2x (1 = normal)")


@app.post("/api/audio/speed", tags=["Ses"])
async def audio_speed(body: AudioSpeedIn):
    """Müzik hızı: tarama temposu 0.25x … 2x (perde değişmez). Arayüzde oynat düğmesinin altındaki çubuk."""
    return audio.bridge.set_speed(body.factor)


class AudioDuckIn(BaseModel):
    on: bool


@app.post("/api/audio/duck", tags=["Ses"])
async def audio_duck(body: AudioDuckIn):
    """Seslendirme konuşurken müziği yumuşakça kısar (on=true) / geri açar. Motor kurulmamışsa etkisiz."""
    return audio.bridge.set_duck(body.on)


# ---------- seslendirme: Kadın / Erkek (app/speech.py) ----------
@app.get("/api/narration/{theme}", tags=["Seslendirme"])
async def narration_text(
    theme: str,
    date: str | None = None,
    region: str = Query("dunya", description=f"Bölge: {', '.join(REGIONS)}"),
    intro: bool = False,
    range_start: str | None = None,
    range_end: str | None = None,
    frames: int | None = Query(None, ge=1, le=60),
    instruments: str | None = Query(None, description="Seçili enstrümanlar, virgülle: piano,violin,…"),
    instruments_only: bool = False,
):
    """Haritanın Türkçe anlatım metni (gerçek değerlerle). Aralık verilirse aralık anlatılır;
    instruments verilirse sonda çalan enstrümanlar okunur. instruments_only=true → yalnız enstrüman cümlesi."""
    ids = [s.strip() for s in instruments.split(",") if s.strip()] if instruments is not None else None
    if instruments_only:
        return {"text": speech.instruments_phrase(ids), "date_used": None}
    try:
        rs = parse_date(range_start, "range_start") if range_start else None
        re_ = parse_date(range_end, "range_end") if range_end else None
        return await speech.narration(theme, parse_date(date), region, intro, rs, re_, frames, ids)
    except (speech.SpeechError, maps.MapRequestError, GibsError) as exc:
        return _audio_err(exc)


@app.get("/api/speech", tags=["Seslendirme"], response_class=Response,
         responses={200: {"content": {"audio/mpeg": {}}}})
async def speech_audio(
    text: str = Query(..., min_length=1, max_length=speech.MAX_TEXT),
    voice: str = Query("tr_male", description="tr_female (Emel) | tr_male (Ahmet)"),
):
    """Metni doğal Türkçe sesle okur (MP3, akış). İnternet gerekir; yoksa 503 → arayüz yerel sese düşer."""
    try:
        chunks = await speech.synthesize(text, voice)
    except speech.SpeechError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=503)
    return StreamingResponse(chunks, media_type="audio/mpeg")


@app.get("/api/catalog", responses=IMG_RESPONSES, response_class=Response, tags=["GIBS ham"])
async def catalog():
    """Temalar, GIBS katmanları ve gerçek veri aralıkları (capabilities'ten) tablo görseli."""
    return Response(await maps.catalog_png(), media_type=PNG)


if __name__ == "__main__":
    import uvicorn

    print(f"\n[OK] Earth Jukebox API: http://{HOST}:{PORT}  (dokuman: /docs)\n")
    uvicorn.run(app, host=HOST, port=PORT)
