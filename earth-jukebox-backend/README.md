# Eratone — NASA uydu verisini dinle

NASA GIBS uydu haritalarını 3D küre ve 2D harita üzerinde gösteren, haritayı müziğe çeviren Windows
masaüstü uygulaması (NASA Space Apps 2026). Haritalar NASA'dan canlı gelir, **API anahtarı gerekmez**.

## Çalıştırma

**Sadece kullanmak (Python gerekmez):** `Eratone_uygulama_*.zip`'i çıkar → `Eratone\Eratone.exe`'ye çift tıkla.

**Kaynak koddan (geliştirme):** Python 3.10+ (64 bit) kurulu olsun, sonra proje klasöründe:

| Komut | Ne yapar |
|---|---|
| `python kurulum.py` | Ortamı kurar (ilk sefer birkaç dakika) ve Eratone'u açar |
| `python kurulum.py --tarayici` | Pencere yerine tarayıcıda açar: http://127.0.0.1:3000 |
| `python kurulum.py --test` | Testleri çalıştırır (internet gerekmez) |
| `python kurulum.py --exe` | `dist\Eratone\Eratone.exe` derler |
| `python kurulum.py --paketle` | `paylasim\` içine paylaşım zip'lerini üretir |

Eratone seçenekleri aynen iletilir: `--no-intro` (açılış animasyonunu atla), `--debug` (geliştirici araçları).
Pencere için Microsoft Edge WebView2 gerekir (Windows 11'de hazır gelir).

## Klasörler

| Yol | Görev |
|---|---|
| `eratone_app.py` | Masaüstü giriş noktası: FastAPI sunucusu + pywebview penceresi |
| `start.py` | Aynı uygulama, tarayıcıda (geliştirme) |
| `app/` | FastAPI arka ucu: NASA GIBS istemcisi + disk önbelleği (`gibs_api.py`), tarih/katman bilgisi (`capabilities.py`), haritalar (`maps.py`), küre dokusu (`sound.py`), müzik köprüsü (`audio.py`), uç noktalar (`main.py`), ayarlar (`config.py`) |
| `frontend/static/` | Arayüz: `eratone.html` (tasarım), `eratone-data.js` (NASA verisi, küre, 2D, aralık oynatıcı), `eratone-audio.js` (müzik paneli ↔ `/api/audio`), `vendor/` (globe.gl, giriş animasyonu, yazı tipleri) |
| `world-sound/` | Müzik motoru: renk → nota, enstrümanlar, 5 bant ekolayzer (kendi `OKUBENI.md`'si var) |
| `tests/` | `pytest` testleri |
| `scripts/` | `make_icon.py` (ikon), `check_layers.py` (NASA katman adlarını doğrular) |
| `Eratone.spec`, `build_eratone.ps1` | exe derleme (güvenli: eski paket derleme bitmeden değişmez) |
| `CONTEXT.md` | Ayrıntılı geliştirme günlüğü: her değişiklik ve nedeni |

## Haritalar

| Tema | NASA GIBS katmanı | Veri |
|---|---|---|
| Dünya'nın Renkleri | MODIS_Terra_CorrectedReflectance_TrueColor | 2000 → dün, günlük |
| Sıcaklık Değişimi | MODIS_Terra_Land_Surface_Temp_Day | 2000 → dün, günlük |
| Okyanus Akıntıları | OSCAR_Sea_Surface_Currents_Zonal | 2014-10 → 2024-07, 5 günlük |
| Bitki Örtüsü | MODIS_Terra_NDVI_8Day | son ~2 yıl, 8 günlük |
| Yağış Dağılışı | IMERG_Precipitation_Rate | 2000 → dün, günlük |
| Küresel Sıcaklık | MERRA2_2m_Air_Temperature_Monthly | 1980 → 2026-08, aylık |

Seçilebilir tarihler her tema için NASA'nın gerçek veri listesinden okunur. Ayrıntı: `docs/KATMANLAR.md`.

## Ses

- **Müzik:** haritanın renkleri notaya dönüşür (mavi pes, kırmızı tiz). Piyano, keman, yan flüt, akustik ve
  elektro gitar **gerçek enstrüman kayıtlarıyla** çalar (`world-sound/worldsound/sampler.py`); her nota
  eşit tamperamanda akortludur, her enstrüman kendi gerçek ses aralığında çalar. 5 bant ekolayzer
  (100 Hz–8 kHz, ±12 dB, 0,5 dB adım).
- **Seslendirme (Kadın/Erkek):** seçili haritayı Türkçe, gerçek değerleriyle okur (`app/speech.py`,
  `frontend/static/eratone-voice.js`). Doğal sesler (Microsoft Emel/Ahmet, `edge-tts`) internet ister;
  yoksa Windows'un yerel Türkçe sesine düşer. Konuşurken müzik kısılır, metin altyazı olarak görünür.
  Seçili ses düğmesine yeniden basmak seslendirmeyi kapatır.

**Atıf:** enstrüman kayıtları FluidR3_GM soundfont'undan (Frank Wen; MIDI.js dönüşümü
[gleitz/midi-js-soundfonts](https://github.com/gleitz/midi-js-soundfonts)),
[CC BY 3.0](https://creativecommons.org/licenses/by/3.0/us/). Ayrıntı: `world-sound/worldsound/samples/KAYNAK.txt`.
Kayıtları yeniden üretmek: `python scripts/build_instrument_samples.py <mp3.js klasörü>`.

## API (aynı adreste)

Arayüzün kullandıkları: `GET /api/themes`, `GET /api/texture/{tema}?date=&width=&region=|bbox=` (JPEG),
`POST /api/audio/source|view|play|loop|instrument|eq|duck`, `GET /api/audio/state`,
`GET /api/narration/{tema}` (anlatım metni), `GET /api/speech?voice=&text=` (MP3, akış).
Hepsi ve diğer görsel uç noktaları (harita, aralık GIF'i, karşılaştırma, projeksiyon, lejant): http://127.0.0.1:3000/docs

Ayarlar `.env` ile değiştirilebilir (örnek: `.env.example`). exe önbelleği ve log: `%LOCALAPPDATA%\Eratone`.
