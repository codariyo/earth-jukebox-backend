"""Seslendirme (Kadın / Erkek): haritayı Türkçe, gerçek değerleriyle sesli anlatır.

İki parça:
  narration()  → anlatım METNİ: tema, bölge, tarih + bölgenin gerçek değerleri (ortalama, en düşük,
                 en yüksek, nerede yüksek). Değerler sound.snapshot'tan (NASA renk ölçeğinden okunan
                 gerçek birimler) gelir. Konuşmaya uygun yazılır: ondalık virgül, "eksi", birimler okunur.
  synthesize() → METİN → SES (MP3): Microsoft'un doğal (neural) Türkçe sesleri
                 Kadın: tr-TR-EmelNeural   Erkek: tr-TR-AhmetNeural   (edge-tts kütüphanesi, LGPLv3)
                 İnternet gerekir; ses akış hâlinde döner (ilk kelimeler ~1 sn'de çalmaya başlar).
                 Üretilen ses diskte önbelleklenir (aynı cümle bir daha üretilmez).
İnternet/servis yoksa arayüz (eratone-voice.js) Windows'un yerel Türkçe sesine (Tolga) düşer.
"""
import asyncio
import hashlib
import re
from collections import OrderedDict
from datetime import date
from pathlib import Path

from . import sound
from .config import CACHE_DIR, REGIONS, THEMES

VOICES = {"tr_female": "tr-TR-EmelNeural", "tr_male": "tr-TR-AhmetNeural"}
RATE = "+0%"                    # doğal hız (ölçüldü: -4%'te 25 kelimelik anlatım ~20 sn sürüyordu)
MAX_TEXT = 700
SPEECH_CACHE_MAX = 300          # diskte en çok bu kadar konuşma dosyası
FIRST_CHUNK_TIMEOUT = 10.0      # servis bu sürede ses göndermezse arayüz yerel sese düşer

MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos",
          "Eylül", "Ekim", "Kasım", "Aralık"]
UNIT_WORDS = {"°C": "derece", "K": "kelvin", "mm/hr": "milimetre bölü saat", "mm/h": "milimetre bölü saat",
              "m/s": "metre bölü saniye", "cm/s": "santimetre bölü saniye", "%": "yüzde"}


class SpeechError(Exception):
    status = 503


# arayüzdeki enstrüman kimliği (eratone.html data-inst) → okunuşu; sıra arayüzdeki sırayla aynı
INSTRUMENT_NAMES = {"acoustic_guitar": "akustik gitar", "electric_guitar": "elektro gitar",
                    "piano": "piyano", "flute": "yan flüt", "violin": "keman"}


def instruments_phrase(ids) -> str:
    """'piyano ve keman' gibi: "Çalan enstrümanlar: piyano ve keman." Bilinmeyen kimlik atlanır."""
    names = [INSTRUMENT_NAMES[i] for i in INSTRUMENT_NAMES if i in set(ids or [])]
    if not names:
        return "Hiçbir enstrüman seçili değil."
    if len(names) == 1:
        return f"Çalan enstrüman: {names[0]}."
    return f"Çalan enstrümanlar: {', '.join(names[:-1])} ve {names[-1]}."


# ---------------- metin ----------------
def say_date(d: date, monthly: bool = False) -> str:
    return f"{MONTHS[d.month - 1]} {d.year}" if monthly else f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def say_number(v: float, digits: int) -> str:
    s = f"{abs(v):.{digits}f}".replace(".", ",")
    if "," in s:
        s = s.rstrip("0").rstrip(",")
    return ("eksi " if v < 0 and s not in ("0",) else "") + s


def _digits(stats: dict) -> int:
    """Okunacak ondalık hane: geniş aralıkta (sıcaklık) tam sayı daha anlaşılır ve kısa
    ("on derece" — "on virgül bir derece" değil); dar aralıkta (yağış, akıntı) ondalık gerekir."""
    span = abs((stats.get("max_real") or 0) - (stats.get("min_real") or 0))
    return 0 if span >= 5 else 1 if span >= 0.5 else 2


def _where_highest(series) -> str | None:
    """32 dilimlik batı→doğu dizisinden en yüksek değerlerin bölgenin neresinde olduğu."""
    vals = [v for v in series or [] if v is not None]
    if len(vals) < 6:
        return None
    n = len(series)
    thirds = []
    for i in range(3):
        part = [v for v in series[i * n // 3:(i + 1) * n // 3] if v is not None]
        thirds.append(sum(part) / len(part) if part else None)
    if None in thirds:
        return None
    lo, hi = min(thirds), max(thirds)
    if hi - lo < 0.04:                       # belirgin fark yok (0..1 normalize değer)
        return None
    return ("batısında", "ortasında", "doğusunda")[thirds.index(hi)]


def _title(theme_id: str) -> str:
    return re.sub(r"\s*\(.*?\)", "", THEMES[theme_id]["title"]).strip()


_text_cache: "OrderedDict[tuple, str]" = OrderedDict()


async def narration(theme_id: str, day: date, region: str, intro: bool = False,
                    range_start: date | None = None, range_end: date | None = None,
                    frames: int | None = None, instruments: list[str] | None = None) -> dict:
    """instruments verilirse (arayüzde seçili enstrüman kimlikleri) anlatımın sonunda okunur."""
    if theme_id not in THEMES:
        raise SpeechError(f"'{theme_id}' diye bir tema yok")
    tail = f" {instruments_phrase(instruments)}" if instruments is not None else ""
    label, bbox = REGIONS.get(region, REGIONS["dunya"])
    theme = THEMES[theme_id]
    monthly = theme.get("cadence") == "monthly"
    parts = []
    if intro:
        parts.append("Seslendirme açık. Haritada kırmızı tonlar tiz, mavi tonlar pes notalarla çalar.")
    # Başlık tek cümle (virgüllerle): "Türkiye." gibi kısa cümlelerden sonra ses 1–1,5 sn duruyordu
    head = f"{_title(theme_id)} haritası, {label}"

    if range_start and range_end:
        parts.append(f"{head}. Tarih aralığı: {say_date(range_start, monthly)} ile {say_date(range_end, monthly)} "
                     f"arası, {frames or 0} kare. Kareler sırayla oynatılıyor; müzik her karede o tarihin verisine geçer.")
        return {"text": " ".join(parts) + tail, "date_used": None}

    key = (theme_id, day.isoformat(), region)
    body = _text_cache.get(key)
    used_iso = None
    if body is None:
        snap = await sound.snapshot(theme_id, bbox, day)
        stats = snap.get("stats", {})
        used_iso = snap.get("date_used")
        used = date.fromisoformat(used_iso) if used_iso else day
        # aylık veride ayın günü önemsiz (31 Ağustos istenir, NASA verisi 1 Ağustos tarihlidir: veri VAR)
        same = (used.year, used.month) == (day.year, day.month) if monthly else used == day
        if used_iso and not same:
            b = [f". {say_date(day, monthly)} için veri yok; en yakın veri tarihi {say_date(used, monthly)}."]
        else:
            b = [f", {say_date(used, monthly)}."]
        cov = stats.get("coverage")
        mean, lo, hi = stats.get("mean_real"), stats.get("min_real"), stats.get("max_real")
        unit = UNIT_WORDS.get(stats.get("units") or "", (stats.get("units") or "").strip())
        dg = _digits(stats)
        if theme_id == "dunya_renkleri":
            b.append("Gerçek renkli uydu görüntüsü: beyaz alanlar bulut ve kar, koyu mavi alanlar okyanus.")
        elif mean is not None:
            if theme_id == "yagis" and cov is not None:
                if cov < 0.005:
                    b.append("Bölgede kayda değer yağış yok.")
                else:
                    b.append(f"Bölgenin yüzde {max(1, round(cov * 100))} kadarında yağış var.")
                    b.append(f"Yağış olan yerlerde ortalama {say_number(mean, dg)} {unit}; "
                             f"en yüksek {say_number(hi, dg)}.")
            else:
                if theme_id == "bitki":
                    b.append(f"Bitki indeksi ortalaması {say_number(mean, 2)}; en düşük {say_number(lo, 2)}, "
                             f"en yüksek {say_number(hi, 2)}. Değer bire yaklaştıkça bitki örtüsü yoğunlaşır.")
                elif theme_id == "okyanus_akinti":
                    b.append(f"Doğu–batı akıntı hızı ortalama {say_number(mean, 2)} {unit}; artı değerler doğuya, "
                             f"eksi değerler batıya akışı gösterir.")
                else:
                    b.append(f"Bölge ortalaması {say_number(mean, dg)} {unit}; en düşük {say_number(lo, dg)}, "
                             f"en yüksek {say_number(hi, dg)} {unit}.")
                where = _where_highest(stats.get("series"))
                if where and theme_id != "okyanus_akinti":
                    b.append(f"En yüksek değerler bölgenin {where}.")
                if cov is not None and cov < 0.5:
                    b.append(f"Bölgenin yalnızca yüzde {max(1, round(cov * 100))} kadarında ölçüm var.")
        body = b[0] + ("" if len(b) == 1 else " " + " ".join(b[1:]))
        _text_cache[key] = body
        if len(_text_cache) > 64:
            _text_cache.popitem(last=False)
    parts.append(head + body)
    return {"text": " ".join(parts) + tail, "date_used": used_iso}


# ---------------- ses ----------------
def _speech_dir() -> Path:
    return Path(CACHE_DIR) / "speech"


def _speech_path(text: str, voice: str) -> Path:
    key = hashlib.sha1(f"{VOICES[voice]}|{RATE}|{text}".encode()).hexdigest()
    return _speech_dir() / f"{key}.mp3"


def _trim_cache() -> None:
    files = sorted(_speech_dir().glob("*.mp3"), key=lambda p: p.stat().st_mtime)
    for f in files[:-SPEECH_CACHE_MAX] if len(files) > SPEECH_CACHE_MAX else []:
        try:
            f.unlink()
        except OSError:
            pass


async def synthesize(text: str, voice: str):
    """MP3 parçaları üreten async üreteç. İlk parça gelmeden hata olursa SpeechError fırlatır
    (arayüz yerel sese düşer). Tamamlanan ses diske yazılır."""
    if voice not in VOICES:
        raise SpeechError(f"Bilinmeyen ses: {voice}")
    text = re.sub(r"\s+", " ", text or "").strip()[:MAX_TEXT]
    if not text:
        raise SpeechError("Boş metin")
    path = _speech_path(text, voice)
    if path.is_file():
        data = path.read_bytes()
        path.touch()

        async def cached():
            for i in range(0, len(data), 16384):
                yield data[i:i + 16384]
        return cached()

    try:
        import edge_tts
    except Exception as exc:
        raise SpeechError(f"Konuşma kütüphanesi yok: {exc}")
    stream = edge_tts.Communicate(text, VOICES[voice], rate=RATE).stream()

    async def audio_only():
        async for ch in stream:
            if ch.get("type") == "audio" and ch.get("data"):
                yield ch["data"]

    gen = audio_only()
    try:
        first = await asyncio.wait_for(gen.__anext__(), FIRST_CHUNK_TIMEOUT)
    except StopAsyncIteration:
        raise SpeechError("Konuşma servisi ses döndürmedi")
    except Exception as exc:  # ağ yok, zaman aşımı, servis hatası
        raise SpeechError(f"Konuşma servisine ulaşılamadı ({type(exc).__name__})")

    async def rest():
        buf = bytearray(first)
        yield first
        complete = False
        try:
            async for chunk in gen:
                buf += chunk
                yield chunk
            complete = True
        finally:
            if complete:
                try:
                    _speech_dir().mkdir(parents=True, exist_ok=True)
                    tmp = path.with_suffix(".tmp")
                    tmp.write_bytes(bytes(buf))
                    tmp.replace(path)
                    _trim_cache()
                except OSError:
                    pass
    return rest()
