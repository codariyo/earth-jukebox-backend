"""Eratone ses köprüsü: world-sound (MapSonifier) ↔ uygulamanın NASA verisi (Faz 5).

world-sound/ klasöründeki `worldsound` kütüphanesi haritayı piksel piksel müziğe çevirir ve sesi
BU bilgisayarın hoparlörüne verir (sounddevice). Kütüphanenin kendi NASA istemcisi (NasaGibsSource)
KULLANILMAZ: harita katmanı uygulamanın kendi önbellekli GIBS istemcisiyle (maps.fetch_layer →
gibs_api) çekilir ve `MapData` olarak verilir. Böylece arayüzde görünen görüntüyle aynı katman,
aynı tarih, aynı önbellek kullanılır.

Akış (arayüz → /api/audio/* → bu modül):
    source  : tema + tarih + kaynak kutu (2D: bölge kutusu, 3D: dünya) → katman PNG → MapSonifier.load
    view    : görünen boylam/enlem kutusu (2D zoom penceresi / 3D bakılan alan) → set_view_lonlat
    play    : çal / durdur        loop: tarama sonunda başa dön
    instrument: arayüz kimliği → worldsound enstrümanı (aç/kapa, ses düzeyi)
    eq      : 5 bant (bass, low_mid, mid, high_mid, treble), −12…+12 dB
    state   : tarama konumu, çalan notalar, 48 bantlık spektrum (görselleştirme)

Ses kartı ilk ihtiyaçta açılır (uygulama açılışında değil). Ortam değişkeni ERATONE_NO_AUDIO=1 ise
ses kartı hiç açılmaz (testler / sessiz deneme); motor yine çalışır, render() ile ses üretilebilir.
"""
import asyncio
import os
import sys
import threading
from collections import OrderedDict
from datetime import date
from pathlib import Path

from . import maps, render

# world-sound kopyası proje kökünde; paket adı `worldsound`
WS_DIR = Path(__file__).resolve().parent.parent / "world-sound"
if WS_DIR.is_dir() and str(WS_DIR) not in sys.path:
    sys.path.insert(0, str(WS_DIR))

# Arayüzdeki enstrüman kimliği (eratone.html data-inst) → worldsound InstrumentRack anahtarı.
# worldsound'daki "bass" ve "pad" arayüzde yok → kapalı kalır.
INSTRUMENT_MAP = {
    "acoustic_guitar": "aguitar",
    "electric_guitar": "eguitar",
    "piano": "piano",
    "flute": "flute",
    "violin": "violin",
}
EQ_BANDS = ("bass", "low_mid", "mid", "high_mid", "treble")
# Mavi-beyaz-kırmızı ıraksak skala: solukluk = şiddet (worldsound "diverging" kipi)
DIVERGING_THEMES = {"okyanus_akinti", "isinma_anomali"}
SOURCE_WIDTH = 2048          # taranan görüntünün genişliği (ızgara 64 sütun; 12× zoomda bile yeterli)
BASE_SCAN_SPEED = 5.0        # 1x hızda saniyede taranan sütun (64 sütun ≈ 12,8 sn'de bir tur)
SPEED_MIN, SPEED_MAX = 0.25, 2.0   # arayüzdeki hız çubuğu: 0.25x … 2x
DUCK_LEVEL = 0.4             # seslendirme konuşurken müzik düzeyi (−8 dB)
MAP_CACHE = 6                # çözülmüş harita (MapData) bellekte en çok


class AudioBridge:
    def __init__(self):
        self._son = None
        self.error: str | None = None          # ses kartı / kütüphane hatası (arayüze gösterilir)
        self.audio_out = False                 # hoparlöre gerçekten bağlı mı
        self._init_lock = threading.Lock()
        self._load_lock: asyncio.Lock | None = None   # olay döngüsüne bağlı; ilk kullanımda kurulur
        self._version = 0
        self._maps: "OrderedDict[tuple, object]" = OrderedDict()
        self.source: dict = {}
        self.view: tuple | None = None
        self.speed = 1.0                       # müzik hızı (tarama temposu); uygulama her açılışta 1x

    # ---------------- motor ----------------
    def sonifier(self):
        """MapSonifier'ı ilk kullanımda kurar. Kurulamazsa None (sebep self.error)."""
        if self._son is not None:
            return self._son
        with self._init_lock:
            if self._son is not None:
                return self._son
            try:
                from worldsound import MapSonifier
            except Exception as exc:  # scipy / sounddevice / world-sound eksik
                self.error = f"Ses sistemi yüklenemedi: {type(exc).__name__}: {exc}"
                return None
            son = MapSonifier()
            # Arayüzün durumu ayrıca gönderilir; başlangıçta hepsi kapalı (bass/pad arayüzde yok)
            for key in son.instruments.keys():
                son.set_instrument(key, enabled=False)
            # world-sound test uygulamasının ayarları
            son.set_scan_speed(BASE_SCAN_SPEED * self.speed)   # 1x: saniyede 5 sütun
            son.set_max_voices(10)
            son.set_reverb(0.25)
            son.set_master(0.8)
            if os.getenv("ERATONE_NO_AUDIO") != "1":
                try:
                    son.start_audio()
                    self.audio_out = True
                except Exception as exc:  # ses kartı yok / meşgul
                    self.error = f"Ses çıkışı açılamadı: {exc}"
            self._son = son
            return son

    def close(self):
        if self._son is not None:
            try:
                self._son.close()
            except Exception:
                pass
            self._son = None
            self.audio_out = False

    # ---------------- veri: uygulamanın NASA katmanı ----------------
    async def load_source(self, theme_id: str, day: date, bbox) -> dict:
        """Temanın katman görüntüsünü (şeffaf = ölçüm yok) çekip motora yükler. En son istek kazanır."""
        son = self.sonifier()
        if son is None:
            return {"ok": False, "error": self.error}
        if self._load_lock is None:
            self._load_lock = asyncio.Lock()
        self._version += 1
        ver = self._version

        theme = maps.get_theme(theme_id)
        used, _ = await maps.snap_date(theme, day)
        bbox = tuple(float(v) for v in bbox)
        key = (theme_id, used, bbox)
        meta = {"theme": theme_id, "layer": theme["layer"], "date_requested": day.isoformat(),
                "date_used": used.isoformat() if used else None, "bbox": list(bbox)}

        data = self._maps.get(key)
        if data is None:
            w, h = maps.image_size(bbox, SOURCE_WIDTH)
            png = await maps.fetch_layer(theme, bbox, w, h, used)
            if ver != self._version:
                return {"ok": False, "stale": True}
            data = await asyncio.to_thread(self._to_mapdata, png, bbox, theme_id, theme["layer"], meta)
            self._maps[key] = data
            if len(self._maps) > MAP_CACHE:
                self._maps.popitem(last=False)
        else:
            self._maps.move_to_end(key)

        async with self._load_lock:
            if ver != self._version:
                return {"ok": False, "stale": True}
            # load() görünümü sıfırlar ve senkron tarar → olay döngüsünü kilitlememek için iş parçacığında
            await asyncio.to_thread(son.load, data)
            self.source = meta
            if self.view is not None:
                await asyncio.to_thread(self._apply_view)
        return {"ok": True, **meta, "size": [data.width, data.height]}

    @staticmethod
    def _to_mapdata(png: bytes, bbox, theme_id: str, layer: str, meta: dict):
        from worldsound import GeoBounds, MapData
        img = render.open_rgba(png)
        return MapData.from_pil(
            img, GeoBounds(west=bbox[0], south=bbox[1], east=bbox[2], north=bbox[3]),
            f"Eratone {theme_id} {meta.get('date_used')}",
            {"source": "eratone", "layer": layer, "date": meta.get("date_used"),
             "diverging": theme_id in DIVERGING_THEMES},
        )

    # ---------------- görünüm ----------------
    def set_view(self, west: float, south: float, east: float, north: float, restart: bool = False) -> dict:
        """restart=True: bölge değişti → tarama yeni bölgenin başından başlar. HATA (2026-11-15): 3D'de bölge
        seçince yalnız görünen alan değişiyordu, tarama kaldığı yerden sürüyordu; döngü kapalıyken birkaç saniye
        sonra bitip müzik kesiliyordu ve yeni bölge hiç baştan çalınmıyordu."""
        self.view = (float(west), float(south), float(east), float(north))
        if self._son is not None and self._son.map is not None:
            self._apply_view()
            if restart:
                self._son.sequencer.restart()
        return {"ok": True}

    def _apply_view(self):
        son = self._son
        if son is None or son.map is None or self.view is None:
            return
        b = son.map.bounds
        w, s, e, n = self.view
        # kaynak kutunun dışına taşan görünümü içeri kırp (ör. 3D'de bölge dışına dönülünce)
        w, e = max(w, b.west), min(e, b.east)
        s, n = max(s, b.south), min(n, b.north)
        if e - w <= 1e-6 or n - s <= 1e-6:
            son.reset_view()
            return
        son.set_view_lonlat(w, s, e, n)

    # ---------------- komutlar ----------------
    def play(self, playing: bool) -> dict:
        son = self.sonifier()
        if son is None:
            return {"ok": False, "error": self.error}
        son.play() if playing else son.pause()
        return {"ok": True, "playing": son.is_playing, "audio_out": self.audio_out, "error": self.error}

    def set_loop(self, loop: bool) -> dict:
        son = self.sonifier()
        if son is None:
            return {"ok": False, "error": self.error}
        son.sequencer.loop = bool(loop)
        return {"ok": True}

    def set_instrument(self, ui_key: str, enabled: bool | None, volume: float | None) -> dict:
        key = INSTRUMENT_MAP.get(ui_key)
        if key is None:
            return {"ok": False, "error": f"Bilinmeyen enstrüman: {ui_key}"}
        son = self.sonifier()
        if son is None:
            return {"ok": False, "error": self.error}
        son.set_instrument(key, enabled=enabled, volume=volume)
        return {"ok": True, "key": key}

    def set_eq(self, band: str, db: float) -> dict:
        if band not in EQ_BANDS:
            return {"ok": False, "error": f"Bilinmeyen bant: {band}"}
        son = self.sonifier()
        if son is None:
            return {"ok": False, "error": self.error}
        son.set_eq(band, db)
        return {"ok": True, "band": band, "db": son.equalizer.gain(band)}

    def set_speed(self, factor: float) -> dict:
        """Müzik hızı (0.25x … 2x): tarama çizgisinin ilerleme hızı. Notaların perdesi değişmez;
        notalar daha sık/seyrek değişir. Motor henüz kurulmadıysa değer saklanır, kurulunca uygulanır."""
        self.speed = float(min(SPEED_MAX, max(SPEED_MIN, factor)))
        if self._son is not None:
            self._son.set_scan_speed(BASE_SCAN_SPEED * self.speed)
        return {"ok": True, "speed": self.speed}

    def set_duck(self, on: bool) -> dict:
        """Seslendirme sırasında müziği kıs (on) / aç. Motor henüz kurulmadıysa (müzik hiç çalmadı)
        ses kartını boşuna açmamak için kurmaz."""
        if self._son is not None:
            # 0.4 (−8 dB): konuşma (≈ −18 dBFS) müziğin ~9 dB üstünde, net; müzik yine duyulur.
            # (0.25 / −12 dB uzun anlatımlarda müziği "kesilmiş" gibi gösteriyordu — bölge değişiminde ~20 sn.)
            self._son.engine.set_duck(DUCK_LEVEL if on else 1.0)
        return {"ok": True, "duck": bool(on)}

    # ---------------- durum ----------------
    def state(self) -> dict:
        son = self._son
        if son is None:
            return {"ready": False, "playing": False, "error": self.error, "audio_out": False}
        from worldsound import note_name
        sounding = sorted(son.sequencer.sounding)
        return {
            "ready": son.map is not None,
            "playing": son.is_playing,
            "loop": son.sequencer.loop,
            "speed": self.speed,
            "audio_out": self.audio_out,
            "error": self.error,
            "position": round(son.scan_position, 4),
            "notes": [note_name(m) for m in sounding],
            "voices": son.engine.active_voices,
            "spectrum": [round(float(v), 3) for v in son.engine.spectrum],
            "peak": round(float(son.engine.peak), 3),
            "source": self.source,
            "view": list(self.view) if self.view else None,
            "instruments": {k: {"enabled": i.enabled, "volume": round(i.volume, 2)} for k, i in
                            ((k, son.instruments[v]) for k, v in INSTRUMENT_MAP.items())},
            "eq": {b: son.equalizer.gain(b) for b in EQ_BANDS},
        }


bridge = AudioBridge()
