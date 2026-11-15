# CONTEXT — Earth Jukebox / Eratone entegrasyon günlüğü

Bu dosya başka bir yapay zekaya (ya da ileride aynı projeye dönen birine) kısa yoldan
"burada ne oldu, neyi neden değiştirdik, sıradaki iş ne" diyebilmek için var.
Kodun ne iş yaptığını ayrıntılı anlatmaz (onun için `README.md` ve `app/*.py` başlıkları var);
sadece **değişiklikleri, kararları ve bekleyen işleri** tutar.

> **Kural:** Her oturumda yapılan değişiklik "Değişiklik günlüğü" bölümüne tarih başlığı
> altında yazılır. Dosya/satır verilir, **neden** yapıldığı bir cümleyle açıklanır.
> Hiçbir bölüm silinmez; eskiyen karar "bu artık geçerli değil çünkü…" notuyla üstü çizilir.

---

## 1. Projenin bir cümlelik özeti

**Earth Jukebox (arayüzde: Dünya Bilgi Müzik Kutusu / Eratone)** NASA GIBS uydu verisini
(sıcaklık, bitki, yağış, okyanus akıntısı, küresel ısınma, gerçek renk) Türkçe anlatım ve
müzikle sunan erişilebilir bir keşif aracı. NASA Space Apps 2026 projesi. API anahtarı
gerekmez.

## 2. Aktif mimari (2026-11-15, Faz 1 sonrası)

```
Tarayıcı
  ▲
  │  AKTİF:      frontend/static/eratone.html   ← GET /  (app/main.py sunar)
  │  ~~DONDURULDU: frontend/ui.py + frontend/static/jukebox.js~~ → SİLİNDİ (2026-11-15 temizlik)
  ▼
FastAPI (app/main.py)
  ├── GET /            → eratone.html (FileResponse)
  ├── /static/*        → frontend/static klasörü (StaticFiles; klasör yoksa mount atlanır)
  └── /api/*           → bütün uç noktalar GÖRSEL döndürür (hatalar da PNG)
  │
  ├── app/sound.py      → snapshot / timeline / texture (müzik kutusu uç noktaları)
  ├── app/maps.py       → single_map / range_gif / compare / overview / projection / tile
  ├── app/sonify.py     → görüntü → nota (batıdan doğuya 32 şerit tarama)
  ├── app/compare.py    → iki tarih arası farkı duyulur hale getiren ortak ölçek
  ├── app/colormap.py   → GIBS renk haritası XML → gerçek birim (Kelvin → °C)
  ├── app/capabilities.py → WMTS GetCapabilities ayrıştırma, tarih listesi
  ├── app/render.py     → Pillow ile başlık/lejant/fark/GIF/hata görseli üretimi
  └── app/gibs_api.py   → NASA'ya giden BÜTÜN HTTP istekleri (httpx, disk önbellek, 3 deneme)
```

- Veri yolu: `tarayıcı → FastAPI → gibs_api → NASA GIBS (WMS/WMTS/colormap/legend) + EONET`
- Önbellek: `cache/` altında `wms/`, `wmts/`, `legend/`, `text/`, `eonet/`, `colormaps/`.
  Capabilities 12 saat, EONET 6 saat geçerli. ~~görüntülerin süresi yok (disk şişer)~~ → kapanışta katman başına
  yalnızca en yeni tarih kalır (`prune_map_cache`, 2026-11-15).
- Giriş noktaları:
  - `python start.py` → API + Eratone arayüzü tek portta (3000), tarayıcıyı `/` ile açar.
  - `python -m app.main` → aynı uygulama (arayüz de gelir, çünkü sunumu main.py yapıyor).
  - ~~`python run_server.py`~~ → SİLİNDİ (2026-11-15 temizlik).
  - **`dist/Eratone/Eratone.exe`** → ASIL MASAÜSTÜ UYGULAMA (`eratone_app.py`, `Eratone.spec`,
    `build_eratone.ps1`). Tarayıcısız, kendi penceresi; sunucu süreç içinde 127.0.0.1:38100. Bkz. 6b.
    Geliştirmede derlemeden: `python eratone_app.py [--debug] [--no-intro]`.
  - **`python kurulum.py`** → ekip arkadaşları için tek komut: .venv + paketler + Eratone'u aç (2026-11-15).
  - ~~`dist/EarthJukebox.exe` → ESKİ tkinter API test aracı (`desktop_app.py`)~~ → SİLİNDİ (2026-11-15 temizlik).

## 3. Tema ↔ GIBS katmanı eşleşmesi (`app/config.py` THEMES)

| Tema (slug)        | GIBS katmanı                              | Veri aralığı              | Enstrüman önerisi |
|--------------------|-------------------------------------------|---------------------------|-------------------|
| `dunya_renkleri`   | MODIS_Terra_CorrectedReflectance_TrueColor| 2000-02-24 → bugün (günlük) | pad               |
| `sicaklik`         | MODIS_Terra_Land_Surface_Temp_Day         | 2000-02-24 → bugün (günlük) | lead              |
| `okyanus_akinti`   | OSCAR_Sea_Surface_Currents_Zonal          | 2014-10-22 → 2024-07-17 (5 gün) | pad          |
| `bitki`            | MODIS_Terra_NDVI_8Day                     | 2025-02-12 → bugün (8 gün) | bell              |
| `yagis`            | IMERG_Precipitation_Rate                  | 2000-06-01 → bugün (günlük) | pluck             |
| `kuresel_isinma`   | MERRA2_2m_Air_Temperature_Monthly         | 1980-01 → 2026-08 (aylık)  | bass              |
| `okyanus`          | GHRSST_L4_MUR25_Sea_Surface_Temperature   | 2002-09-01 → bugün (günlük, uygulamada gizli) | strings |
| `isinma_anomali`   | GHRSST_L4_MUR25_SST_Anomalies             | 2002-09-01 → bugün (günlük, gizli) | lead     |

MAIN_THEMES = ilk 6; Eratone arayüzündeki 6 harita kartı birebir bu sırayla eşleşir.

## 4. Bölge ↔ slug eşleşmesi (`app/config.py` REGIONS)

Eratone arayüzü bölge butonlarına `data-region="Türkçe Ad"` yazıyor; backend slug bekliyor.
Dönüşüm tablosu:

| Arayüz etiketi  | Backend slug    |
|-----------------|-----------------|
| Dünya           | `dunya`         |
| Türkiye         | `turkiye`       |
| Avrupa          | `avrupa`        |
| Akdeniz         | `akdeniz`       |
| Kuzey Amerika   | `kuzey_amerika` |
| Güney Amerika   | `guney_amerika` |
| Afrika          | `afrika`        |
| Asya            | `asya`          |
| Avustralya      | `avustralya`    |
| Amazon          | `amazon`        |
| Kuzey Kutbu     | `kuzey_kutbu`   |

## 5. Eratone arayüzü (yeni cephe) — mevcut durum

Kaynak: `C:\Users\EXCALIBUR\Desktop\eratone_234.html` (tek dosya, 5873 satır, 281438 bayt).
Projedeki kopyası: `frontend/static/eratone.html` (birebir aynı, SHA256 eşleşti; Faz 1'de
İÇERİĞİNE DOKUNULMADI). Satır numaraları aşağıda bu dosyaya göredir.

**Yapı:**
- 3310'a kadar tamamı CSS.
- `#intro` overlay'i varsayılan kapalı; `?intro=1` ile Three.js r128 CDN'den yüklenir.
- Üst bar: silindir tarih seçici, 11 bölge dropdown, tarih aralığı paneli (max 60 kare), EQ toggle.
- Sol: 6 harita kartı, içlerinde "[ Harita X Alanı ]" yer tutucuları.
- Merkez: `#globe-3d` ve `#globe-2d` BOŞ divler + 3D/2D toggle + yazı boyutu.
- Sağ: 5 bant EQ + 5 enstrüman mixer slider'ı.
- Alt: 4 seslendirme modu (Erkek, Kadın, 3D Uzamsal, Erişilebilir), play/loop, 5 enstrüman tınısı.

**Kritik tespit:** Dosyada backend'e giden TEK fetch var (satır 4088, intro için Three.js dokusu).
Arayüz tamamen cephe; `#globe-3d`/`#globe-2d` boş, harita kartlarında metin, EQ hiçbir yere
bağlı değil. Yani entegrasyon = "bu cepheyi backend'e bağlamak".

Önemli JS bölümleri (eratone.html; Faz 2 eklemeleriyle satırlar birkaç satır kaydı, ~ yaklaşık):
- ~5160–5300: silindir tarih seçici (`makeDrum`, `setDate`, `stepDay`, `paintDrumLimits`), durum: `currentDay`,
  `currentMonth` (0=Ocak), `currentYear`, `currentRegion` (Türkçe ad). `MIN_YEAR` Faz 2'de 1980.
  Faz 3: `dateMin`/`dateMax` (let) seçilebilir sınır; `setDate`, `stepDay`, `openPicker`, `rebuildFrames` bunlara uyar.
  `window.eratoneSetDateLimits(minIso, maxIso)` (initRange'den sonra) veri katmanının çağırdığı giriş noktası.
- ~5375–5505: tarih aralığı (`rebuildFrames`, `showFrame`, `viewRange`, `viewDate`). Kare tarihleri
  burada hesaplanır; `eratone:range-applied`, `eratone:date-applied`, `eratone:frame` olaylarını yayar.
- ~5680–5700: 3D/2D toggle (`#globe-3d` / `#globe-2d` display değiştirir).
- ~5705–5715: harita kartları (`.map-card[data-theme]` — `data-theme` Faz 2'de eklendi).
- Sonda: `<script src="/static/vendor/globe.gl.min.js">` + `<script src="/static/eratone-data.js">` (Faz 2).

**Veri katmanı (Faz 2): `frontend/static/eratone-data.js` + `eratone-data.css`** — NASA görüntülerini
arayüze yerleştiren kodun TAMAMI burada; eratone.html'e sadece kancalar eklendi. Ayrıntı: günlük → Faz 2.

## 5b. MÜZİK KİTİ BAĞLANTI NOKTALARI — ✅ Faz 5'te world-sound ile BAĞLANDI

> **Güncel durum (Faz 5):** Enstrümanlar, mixer, EQ, Oynat/Döngü → `frontend/static/eratone-audio.js` →
> `/api/audio/*` → `app/audio.py` → `world-sound/worldsound` (MapSonifier). Ayrıntı: günlük → "Faz 5".
> Hâlâ AÇIK UÇ: seslendirme modları (Erkek/Kadın/3D Uzamsal/Erişilebilir — sesli anlatım), eski `app/sonify.py`
> + `/api/sound/*` (eski NiceGUI arayüzünün geçici ses sistemi; Eratone kullanmıyor, silinmedi).
> Aşağısı Faz 1'deki ilk tespittir (kayıt için):

Faz 1'de müziğe HİÇ dokunulmadı. Arayüz zaten bir ses motoruna bağlanmak üzere tasarlanmış:

**Hazır olan (eratone.html ~5728–5797):**
- `window.eratoneAudio` = `{ playing: bool, loop: bool, instruments: { <id>: { active: bool, volume: 0..1 } } }`
- Her değişiklikte `document` üzerinde `eratone:audio` CustomEvent'i yayınlanır:
  `detail = { type, state, ...extra }`
  | `type`       | ne zaman                      | extra                         |
  |--------------|-------------------------------|-------------------------------|
  | `play`       | Oynat/Duraklat (`#btn-main-play`) | — (`state.playing`'e bak)  |
  | `loop`       | Döngü (`#btn-loop`)           | — (`state.loop`'a bak)        |
  | `instrument` | Enstrüman aç/kapa (`.instrument-pill`, en az biri açık kalır) | `instrument`, `on` |
  | `volume`     | Mixer slider (`.mix-slider`)  | `instrument`                  |
- Enstrüman id'leri: `acoustic_guitar`, `electric_guitar`, `piano`, `flute`, `violin`.
  (Projede mevcut soundfont'lar: `acoustic_guitar_nylon`, `acoustic_grand_piano`, `flute`, `violin`
  → `frontend/static/soundfonts/*.js`. **Elektro gitar soundfont'u YOK.**)

**Henüz olay yaymayan (müzik kiti eklerken bağlanmalı):**
- EQ 5 bandı: `.eq-slider[data-target=val-60hz|val-250hz|val-1khz|val-4khz|val-12khz]`, -12..+12 dB.
  Şu an sadece yanındaki etiketi günceller (~5665–5675), `eratone:audio` YAYMAZ.
- Seslendirme modları: `.voice-pill[data-voice=tr_male|tr_female|spatial|screen_reader]` (~5716–5726),
  sadece `active` sınıfı değişir, olay YAYMAZ.
- EQ görselleştirici: `.eq-visualizer .eq-bar` (8 çubuk) — şu an saf CSS animasyonu, gerçek sesle bağlı değil.

**Veri tarafı (backend, zaten var — müzik kiti isterse kullanır):**
- `GET /api/sound/{tema}?date=&region=&steps=32&melodic=true` → nota dizisi JSON (app/sonify.py, geçici)
- `GET /api/sound/{tema}/timeline?start=&end=&frames=` → zaman yolculuğu notaları JSON
- Bunlar da GEÇİCİ ses sistemine ait; yeni motor kendi veri biçimini isterse değiştirilebilir.

**Önerilen bağlama şekli:** Müzik kiti ayrı bir dosya olsun (örn. `frontend/static/audio/eratone-audio.js`),
eratone.html'e `</body>` öncesine tek `<script src="/static/audio/...">` eklensin, `eratone:audio`
olayını dinlesin. Böylece arayüz dosyasına müdahale minimumda kalır.

## 6. Entegrasyon planı (fazlar)

### Faz 0 — hazırlık ✅ (bu dosya)
Dosya anlaşıldı, karar verildi, günlük başladı.

### Faz 1 — statik sunum ✅ (2026-11-15)
- Eratone → `frontend/static/eratone.html`; FastAPI `GET /` + `/static` mount (app/main.py).
- `start.py` NiceGUI'siz; `frontend/ui.py` dondurularak saklandı.
- Ayrıntı: "Değişiklik günlüğü" → 2026-11-15 Faz 1.

### Faz 2 — veri bağlama ✅ (2026-11-15) — 2a–2e yapıldı, 2f'nin yerine kart önizlemeleri
- 6 kart önizlemesi, kart seçimi → 3D küre (globe.gl) + 2D harita, bölge, tek tarih, tarih aralığı + kareler.
- Ayrıntı: "Değişiklik günlüğü" → 2026-11-15 Faz 2. Lejant (renk → değer) arayüzde HENÜZ gösterilmiyor.

### Sıradaki iş: MÜZİK KİTİ (kullanıcı getirecek) — bkz. bölüm 5b
Faz 2 ile bağımsız; müzik kodu ayrı dosya olarak eklenmeli (eratone-data.js örneğindeki gibi).
Veri durumu `window.eratoneData.state` üzerinden okunabilir (tema, bölge, tarih, aralık/kare).

### Faz 2 — veri bağlama (küçük PR'lar)
2a. `window.AppState = { theme, region, date, rangeMode, start, end, frames, view2d }` + değişince `render()` çağrısı.
2b. **2D görünüm:** `#globe-2d` içine `<img src="/api/map/{theme}?date=&region=&legend=false&coast=true">`.
2c. **Harita kartları:** her karta `data-theme="..."` ekle, tıklayınca `AppState.theme` değişsin.
2d. **3D küre:** `frontend/static/vendor/globe.gl.min.js` + `/api/texture/{theme}?date=&width=2048` doku.
2e. **Tarih aralığı:** `/api/map/{theme}/range?start=&end=&frames=` GIF'i `#globe-2d` içine.
2f. **Harita kartı önizlemeleri:** `/api/legend/{theme}` küçük görsel; isteğe bağlı.

### Faz 3 — ses sistemi (sen yeni motoru getirince)
- EQ 5 bandı, 5 enstrüman mixer'ı, 4 seslendirme modu, play/loop, enstrüman tınıları yeni motora bağlanır.
- **Şu an dokunulmayacak** — geçici UI kalsın.

### Faz 4 — temizlik
- NiceGUI tamamen sökülmüşse `frontend/ui.py`, `frontend/static/jukebox.js`, `nicegui` paketini kaldır.
- `desktop_app.py` ve `EarthJukebox.spec` güncellensin (exe yeni arayüzü sunmalı).

## 6b. MASAÜSTÜ UYGULAMA (2026-11-15) — M0–M3 UYGULANDI, M4 (kurulum) bekliyor

**Durum özeti:** `dist\Eratone\Eratone.exe` çalışıyor (onedir klasör, 89 MB, Python gerekmez).
Uygulama adı: **Eratone**. Dağıtım şekli (kurulum programı mı taşınabilir mi) kullanıcı kararı bekliyor;
şimdilik taşınabilir klasör. Intro (açılış animasyonu) uygulamada KAPALI, `--intro` ile açılabilir.
Ayrıntı: Değişiklik günlüğü → "2026-11-15 — Masaüstü uygulaması".

Aşağısı ilk plan metnidir (değişmedi, kayıt için duruyor):

**Hedef:** Tarayıcı açmadan, çift tıklayınca kendi penceresinde açılan Windows uygulaması.
**Seçilen yol:** pywebview (Windows'ta Edge WebView2 motoru) + aynı süreçte FastAPI/uvicorn + PyInstaller.

Neden bu yol:
- Backend zaten Python; ayrı runtime gerekmez. Arayüz (eratone.html) olduğu gibi çalışır.
- WebView2 Windows 11'de hazır (bu makinede v157). Web Audio + speechSynthesis + localStorage destekler
  → gelecekteki müzik kiti (JS ise) değişiklik gerektirmeden çalışır.
- Reddedilenler: Electron (Chromium + Node + Python yan süreci, +150 MB, iki runtime);
  Tauri (Rust araç zinciri + Python yan süreci); tkinter/`desktop_app.py` (HTML gösteremez).

Adımlar (M = masaüstü; Faz 2–4'ten bağımsız numaralandı):
- **M0 Yedek:** Başlamadan proje yedeği (Faz 1 yedeği gibi).
- **M1 Giriş dosyası `eratone_app.py` (YENİ):** boş port seç (3000 dolu olabilir — geliştirme sunucusuyla
  çakışmasın), uvicorn'u arka plan iş parçacığında başlat, `/health` hazır olunca pywebview penceresi aç
  (başlık "Eratone", ~1440×900, min 1024×700, arka plan #03050a — beyaz flaş olmasın). Pencere kapanınca
  sunucu durur, süreç biter. Tek örnek kilidi (ikinci açılış yeni pencere açmasın).
  `webview.start(private_mode=False, storage_path=%LOCALAPPDATA%\Eratone\webview)` → localStorage kalıcı.
- **M2 Çevrimdışı arayüz:** Inter + Outfit woff2 dosyaları `frontend/static/vendor/fonts/`'a, eratone.html'deki
  Google Fonts `<link>`'leri (satır 7–9) yerel CSS ile değişir. Three.js r128 + intro dokuları yalnızca intro
  açılacaksa yerelleşir. (NASA verisi doğası gereği internet ister; önbellekte olan harita internetsiz de gelir.)
- **M3 Paketleme:** PyInstaller **onedir** (onefile her açılışta ~100 MB açtığı için yavaş), `--windowed`,
  ikon `.ico`, `datas`: `frontend/static` → `frontend/static`. `app/main.py` FRONTEND_DIR `__file__`'a göre
  çözüldüğü için `_internal/frontend/static`'i bulur (derlemede doğrulanacak).
  **RİSK:** `--windowed`'da `sys.stdout`/`stderr` = None → uvicorn loglaması ve `app/logger.py` çökebilir.
  Çözüm: frozen modda stdout/stderr `%LOCALAPPDATA%\Eratone\logs\eratone.log`'a yönlendirilir.
  Önbellek klasörü şu an `%LOCALAPPDATA%\EarthJukebox\cache` (config.py) — "Eratone" olarak değiştirilip
  değiştirilmeyeceği karar bekliyor.
- **M4 Kurulum:** Inno Setup → Program Files'a kurulum, Başlat menüsü + masaüstü kısayolu, kaldırıcı.
  WebView2 yoksa (eski Windows 10) Microsoft'un bootstrapper'ı. İmzasız exe'de SmartScreen uyarısı çıkar.
- **M5 Doğrulama listesi:** internetsiz açılış; Ctrl+F5'e gerek yok (her açılış taze); pencere kapatınca süreç
  kalmıyor; ikinci açılış; geliştirme sunucusu 3000'deyken açılış; yüksek DPI ekran; Türkçe TTS sesleri
  (Windows dil paketine bağlı); yazı boyutu tercihi yeniden açılışta korunuyor mu.

Dokunulmayacaklar: `app/` iş mantığı, müzik kodu, `desktop_app.py` (API test aracı olarak kalır,
kendi `EarthJukebox.spec`/`build_exe.ps1`'i ile). Yeni uygulamanın kendi spec + derleme betiği olacak.

Kullanıcı kararı bekleyenler: uygulama/exe adı, ikon dosyası, kurulum programı mı taşınabilir klasör mü,
intro uygulamada açık mı, önbellek klasörü adı.

## 7. Karar defteri (neyi, neden)

- **Neden NiceGUI'yi bırakıp ham HTML'e geçiyoruz?**
  Eratone arayüzü NiceGUI'nin ürettiği DOM'la uyumsuz (silindir tarih seçici, orb'lu
  butonlar, cam efektleri, özel CSS değişkenleri). NiceGUI üzerinden sarmak kodu iki
  katına çıkarırdı. Ham HTML + küçük JS bağlayıcı en kısa yol.

- **Neden MAX_FRAMES=12 → 60 çıkarılmalı?**
  Eratone'un tarih aralığı paneli 60 kareye izin veriyor. Config limiti aşılırsa
  422 döner. Dezavantaj: GIF büyür (60 × ~100 KB ≈ 6 MB), üretim yavaşlar. Alternatif:
  arayüzde limiti 12'ye çekmek — ama o zaman kullanıcıya verilmiş özellik azalıyor.
  **Karar: Config 60'a çıkar, UI'da "Büyük kare sayısı yavaş gelebilir" notu göster.**

- **Neden Three.js r128 (intro) yerinde kalsın?**
  Varsayılan kapalı, sadece `?intro=1` ile çalışıyor. Bir şeyi bozma riski yok.
  Silmek için nedenimiz olana kadar durur.

- **Neden ses sistemine dokunmuyoruz?**
  Kullanıcı yeni bir ses motoru geliştiriyor. Şimdiki `app/sonify.py` + `jukebox.js` Web
  Audio + soundfont dosyaları hep **geçici**. Yeni motor gelince Faz 3'te bağlanacak.

- **Neden CDN bağımlılıkları (Google Fonts, Three.js r128) şimdilik kalsın?**
  İnternet varken çalışır, offline exe'de kırılır. Yerelleştirme Faz 4'te yapılır;
  şimdi yapsak her değişiklikte font dosyasını da güncellemek gerekir, tempoyu kırar.

## 8. Bilinen sorunlar (dokunulmayan borçlar)

- **Önbellek büyümesi:** `cache/wms/`, `cache/wmts/`, `cache/eonet/` sürekli büyüyor.
  "Bugün − 3 gün" varsayılan tarih olduğu için her gün yeni dosya birikiyor.
  **Çözüm fikri:** LRU dosya temizliği (en eski %20'yi sil) + boyut tavanı (örn. 2 GB).
- **CORS `allow_origins=["*"]`:** Yerel kullanımda sorun değil, exe dağıtımında da sorun değil
  çünkü sunucu yerel. Başka siteye gömülecekse daralt.
- **`colormap.get_colormap`:** `app/colormap.py` içinde ayrı bir önbellek yolu var ama
  gerçek akışta `maps.colormap_for` → `gibs_api.fetch_text` kullanılıyor. Ölü kod olabilir;
  grep ile doğrulanmadı, Faz 4'te bakılacak.
- **Okyanus akıntısı 2024-07-17'de bitiyor:** "Bugün" seçildiğinde arayüz hep 2024 Temmuz'u
  gösterir, altına uyarı not düşülür. Beklenen davranış ama kullanıcı şaşırabilir.
- ~~**"Bugün"ün verisi eksik/boş**~~ → **ÇÖZÜLDÜ 2026-11-15 (Faz 3b): kullanıcı kararı (a), uygulama DÜNÜN tarihiyle açılır.**
  Kalan doğal durum: tek günlük MODIS gerçek renkte yörünge şeritleri arasında siyah boşluklar + kutup gecesi siyah.
  İstenirse (c) seçeneği: backend'de gerçek renkte siyah pikseli "veri yok" sayıp Blue Marble'ı göstermek (yapılmadı, sorulmadı).
  Eski kayıt: Uygulama kullanıcı isteğiyle
  BUGÜNÜN tarihiyle açılıyor. GIBS bugünü "var" diye listelediği için backend o tarihe oturuyor ama uydu
  geçişleri henüz işlenmemiş: `dunya_renkleri` (gerçek renk) neredeyse tamamen SİYAH (veri olmayan yer
  opak siyah geliyor, Blue Marble görünmüyor), `sicaklik` bugünde neredeyse boş. 2026-11-15 sabahı
  ekran görüntüsüyle doğrulandı. Seçenekler: (a) açılış tarihi dün; (b) bugün kalsın, şeritte uyarı;
  (c) backend'de gerçek renkte siyah pikseli "veri yok" sayıp Blue Marble'ı göstermek.
  (Eski backend varsayılanı da bu yüzden "bugün − 3 gün"dü: app/main.py parse_date.)

## 9. Değişiklik günlüğü

### 2026-11-15 — Faz 0: Context dosyası
- **Eklendi:** `CONTEXT.md` (bu dosya).
- **Neden:** Başka bir yapay zekaya devretmek için proje durumu, karar defteri ve
  entegrasyon planının tek yerden okunabilmesi. Her değişiklik bu dosyaya işlenecek.
- **Değişen kod:** Yok (sadece doküman).
- **Sonraki adım:** Faz 1 — Eratone HTML'i `frontend/static/eratone.html`'e kopyala,
  `start.py`'ı NiceGUI yerine FileResponse'a çevir.

### 2026-11-15 — Faz 1: Eratone arayüzü FastAPI üzerinden sunuluyor

**Yedek (geri dönüş noktası):** `C:\Users\EXCALIBUR\Desktop\earth-jukebox-backend_YEDEK_2026-11-15_faz0`
— Faz 1 ÖNCESİ projenin tam kopyası (62 dosya, 105 MB). `.venv`, `cache`, `.pytest_cache`,
`__pycache__` hariç (hepsi yeniden üretilebilir). Geri dönmek için: bu klasördeki
`start.py`, `app/main.py`, `frontend/ui.py` dosyalarını projeye geri kopyala ve
`frontend/static/eratone.html`'i sil.

**Değişen / eklenen dosyalar:**

| Dosya | Ne değişti | Neden |
|---|---|---|
| `frontend/static/eratone.html` | **YENİ.** Masaüstündeki `eratone_234.html`'in birebir kopyası (hash eşleşti). | Arayüz projenin içinde, statik klasörde dursun; StaticFiles ile sunulsun. İçeriğe dokunulmadı. |
| `app/main.py` | `Path`, `FileResponse`, `StaticFiles` import edildi. `FRONTEND_DIR`/`INDEX_HTML` sabitleri; `/static` mount (klasör varsa); `GET /` → eratone.html (yoksa 404 hata PNG'si). `/health`'in hemen üstünde, "arayuz (Eratone)" başlıklı bölüm. | Sunum main.py'de olsun ki `start.py`, `python -m app.main`, `run_server.py` hepsi aynı arayüzü versin. Yol `__file__`'a göre mutlak, çalışma klasöründen bağımsız. Klasör kontrolü, frontend'i paketlemeyen exe çökmesin diye. |
| `start.py` | NiceGUI satırları (`from nicegui import ui`, `from frontend.ui import setup`, `setup()`, `ui.run_with(...)`) çıkarıldı. Tarayıcıyı açma ve `--no-browser` korundu. | NiceGUI, Eratone'un body sınıflarıyla (`data-state`, `intro-active`, `app-ready`) çakışırdı; ham HTML en temiz yol (bkz. Karar defteri). |
| `frontend/ui.py` | Sadece en üste "DONDURULDU" docstring notu eklendi. Kod aynı. | Geri dönüş/kıyas için saklanıyor. `tests/test_sound.py` buradan `speakable` import ettiği için silinmedi; `nicegui` paketi bu yüzden requirements'ta kalmalı. |

**Dokunulmayanlar:** `app/` altındaki diğer bütün dosyalar, `frontend/static/jukebox.js`,
`style.css`, soundfont'lar, vendor kütüphaneleri, `desktop_app.py`, `EarthJukebox.spec`,
`requirements.txt`, `README.md` (README hâlâ NiceGUI'yi anlatıyor — Faz 4'te güncellenecek).

**Doğrulama (geçici port 3055'te):**
- `/health` 200 JSON · `/` 200 text/html 281438 bayt (title: "Eratone — Space · Planetary · Sonification")
- `/static/eratone.html` 200 · `/static/vendor/globe.gl.min.js` 200 · `/static/favicon.svg` 200
- `/docs` 200 · `/api/themes` 200 JSON · `/api/legend/sicaklik` 200 PNG
- `pytest`: 40 passed

**Bilinen küçük not:** Eratone HTML'inde `<link rel="icon">` yok; tarayıcı `/favicon.ico`
ister ve 404 hata PNG'si alır. Zararsız. İstenirse HTML'e `<link rel="icon" href="/static/favicon.svg">` eklenir.

**DİKKAT — yaşanan sorun:** Faz 1 sonrası kullanıcı tarayıcıda hâlâ ESKİ (NiceGUI) arayüzü gördü.
Sebep: 3000 portunda değişiklikten önce başlatılmış eski `start.py` süreci çalışıyordu; Python
kodu belleğe yüklendiği için yeni kod devreye girmemişti. Doğrulama ayrı portta (3055) yapıldığı
için bu fark edilmedi. **Kural:** Python dosyası (`start.py`, `app/*.py`) değiştikten sonra sunucu
MUTLAKA yeniden başlatılmalı (Ctrl+C → `python start.py`), tarayıcı Ctrl+F5 ile yenilenmeli.
Kontrol: `Get-NetTCPConnection -LocalPort 3000 -State Listen` → OwningProcess'in başlama saati
değişiklikten sonra mı? (HTML/JS/CSS değişikliklerinde yeniden başlatma gerekmez, Ctrl+F5 yeter.)

**Sonraki adım:** Müzik kiti (bölüm 5b) ya da Faz 2a (AppState + bölge slug tablosu).

### 2026-11-15 — Masaüstü uygulaması (Eratone.exe), plan 6b M0–M3

**Yedek (geri dönüş noktası):** `C:\Users\EXCALIBUR\Desktop\earth-jukebox-backend_YEDEK_2026-11-15_faz1`
— bu işten ÖNCE, Faz 1 SONRASI proje (49 dosya; `.venv`, `cache`, `build`, `__pycache__` hariç).

**Kullanıcı kararları:** exe (bat değil); ad "Eratone"; ikon üretilsin; dağıtım şekli kararsız →
taşınabilir klasör; intro şimdilik kapalı.

**Mimari:** `Eratone.exe` → `eratone_app.py` → aynı süreçte uvicorn (arka plan iş parçacığı,
127.0.0.1:38100) + pywebview penceresi (Edge WebView2). Pencere `http://127.0.0.1:38100/`'i yükler;
arayüz bütün veriyi bu yerel host üzerinden HTTP ile `/api/*`'dan çeker, backend de NASA'dan.
Tarayıcı AÇILMAZ. Pencere kapanınca sunucu durur, süreç biter.

| Dosya | Ne | Neden |
|---|---|---|
| `eratone_app.py` | **YENİ.** Giriş noktası: tek örnek mutex'i (`Local\EratoneDesktopApp`), port seçimi, uvicorn thread, yükleniyor ekranı → `load_url`, kapanışta `server.should_exit`. `--intro`, `--debug` bayrakları. | Tarayıcısız uygulama. Sunucu süreç içinde: "eski sunucu açık kaldı" sorunu (Faz 1'de yaşanan) bu modda olamaz. |
| `eratone_app.py` → port | SABİT 38100 (doluysa 38101…38119, en son rastgele). 3000 bilinçli olarak kullanılmıyor. | WebView2 localStorage'ı host:port'a bağlar; rastgele port her açılışta tercihleri (yazı boyutu) siler. 3000 geliştirme sunucusuyla çakışmasın. |
| `eratone_app.py` → G/Ç | Penceresiz exe'de stdout/stderr → `%LOCALAPPDATA%\Eratone\logs\eratone.log` (5 MB'ta `eratone.old.log`'a döner). | `--windowed`'da `sys.stdout=None`; uvicorn loglaması çöker, `app/logger.py`'ın NASA istek logları kaybolurdu. |
| `eratone_app.py` → önbellek | Sadece exe'de `CACHE_DIR=%LOCALAPPDATA%\Eratone\cache` (env ile; `app/config.py` DEĞİŞMEDİ). Geliştirmede proje `cache/` kullanılır. | Program Files'a yazılamaz; eski test aracının `EarthJukebox\cache`'iyle karışmasın. |
| `eratone_app.py` → WebView2 verisi | `private_mode=False`, `storage_path=%LOCALAPPDATA%\Eratone\webview`. | localStorage/tercihler kalıcı olsun. |
| `Eratone.spec` | **YENİ.** onedir, `console=False`, ikon, `datas=[('frontend/static','frontend/static')]`, `excludes=['nicegui','tkinter','frontend.ui','pytest']`. | onefile her açılışta ~90 MB açtığı için yavaş. Arayüz pakette `_internal\frontend\static` altında; `app/main.py` FRONTEND_DIR bunu `__file__`'dan buluyor (doğrulandı). |
| `build_eratone.ps1` | **YENİ.** `powershell -ExecutionPolicy Bypass -File build_eratone.ps1` → `dist\Eratone\Eratone.exe`. | Tek komutla derleme. |
| `scripts/make_icon.py` + `assets/eratone.ico`, `assets/eratone.png` | **YENİ.** Pillow ile ikon: koyu zemin, camgöbeği dünya, mercan ses dalgası (Eratone paleti). | Kullanıcının ikonu yoktu. Değiştirmek için betiği düzenle → çalıştır → yeniden derle. |
| `frontend/static/vendor/fonts/` | **YENİ.** `fonts.css` + 4 woff2 (Inter, Outfit; latin + latin-ext — Türkçe harfler latin-ext'te). | İnternetsiz açılışta yazı tipleri bozulmasın (M2). |
| `frontend/static/eratone.html` satır 7–9 | Google Fonts `<link>`'leri → `/static/vendor/fonts/fonts.css`; ayrıca `<link rel="icon" href="/static/favicon.svg">`. 3 satır → 3 satır, diğer satır numaraları KAYMADI. | M2 + favicon 404'ü giderildi. **Masaüstündeki orijinal `eratone_234.html` DEĞİŞMEDİ** — artık proje kopyası ondan farklı. |
| `requirements.txt` | `pywebview>=6,<7` eklendi (venv'de 6.2.1 + pythonnet 3.2.1). | Masaüstü pencere bileşeni. |

**Dokunulmayanlar:** `app/` (tamamı), müzik kodu, `desktop_app.py` + `EarthJukebox.spec` + `build_exe.ps1`
(eski API test aracı ayrı yaşıyor), `start.py` (geliştirme sunucusu olarak duruyor), README.

**Doğrulama:**
- Geliştirme: `python eratone_app.py` → pencere açıldı, 38100'de sunucu; pencere `/`, `fonts.css`, woff2, favicon istedi; Google Fonts'a istek yok.
- Exe: `_internal\frontend\static\eratone.html` ve fonts pakette; WebView2 DLL'leri pakette; nicegui pakette DEĞİL.
  `Eratone.exe` → sunucu hazır, `/` Eratone, `/api/themes` 200 (NASA GetCapabilities isteği logda);
  `%LOCALAPPDATA%\Eratone\{cache,logs,webview}` oluştu; pencere başlığı "Eratone";
  pencereyi kapatma (WM_CLOSE) → süreç 10 sn içinde bitti, 38100 serbest kaldı. Logda hata yok.
- `pytest`: 40 passed.
- **Test EDİLMEDİ:** ikinci kopya uyarısı (MessageBox etkileşimli, otomatik test edilemedi), internetsiz açılış,
  yüksek DPI, Türkçe TTS (WebView2'de). Bunlar M5 listesinde.

**ÖNEMLİ — arayüz henüz veri GÖSTERMİYOR:** Veri hattı (pencere → yerel host → FastAPI → NASA) çalışıyor,
ama eratone.html'deki `#globe-3d`, `#globe-2d` ve harita kartları hâlâ boş yer tutucu. Verinin ekrana
yansıması Faz 2'nin işi (bölüm 6, 2a–2f).

**Kullanım notları (diğer yapay zeka için):**
- HTML/JS/CSS değişikliği → exe'yi yeniden derlemeden `dist\Eratone\_internal\frontend\static\` altındaki
  dosya değiştirilerek denenebilir, ama KALICI değişiklik `frontend/static/`'te yapılıp yeniden derlenmeli.
- Python değişikliği → `build_eratone.ps1` ile yeniden derle.
- Geliştirirken derlemeden denemek için: `.venv\Scripts\python.exe eratone_app.py --debug` (sağ tık → İncele).
- Exe açıkken tekrar derlenemez (dosya kilitli) — önce pencereyi kapat.

**Sonraki adımlar:** Faz 2 (veriyi arayüze yansıt) · müzik kiti (5b) · M4 kurulum programı (karar bekliyor).

### 2026-11-15 — Faz 2: NASA verisi arayüze bağlandı (kartlar, 3D küre, 2D harita, tarih, aralık)

**Yedekler:** `..._YEDEK_2026-11-15_faz2-oncesi` (Faz 2 öncesi alınması UNUTULDU; sonradan yeniden kuruldu:
masaüstü orijinal + M2 font değişikliği. Şimdiki dosyayla farkının yalnızca Faz 2 satırları olduğu otomatik
doğrulandı; içinde `GERI_DONUS.txt` talimatı var) · `..._YEDEK_2026-11-15_faz2-sonrasi` (tam proje, 61 dosya).

**Kullanıcı istekleri:** müziğe dokunma; soldaki 6 haritayı API'den çek ve kartlara yerleştir; seçilen kart
2D'de görünsün, 2D alan görsele göre ölçeklensin; aynı görüntü 3D küreye giydirilsin; tarih API'ye bağlansın
(açılışta güncel tarih); aralıkta kare tarihleri "gün / kare" mantığıyla belirlensin.

**Mimari:** Bütün görüntüler `GET /api/texture/{tema}?date=&width=[&region=]` (başlıksız eşdikdörtgen JPEG:
Blue Marble + veri + kıyı; `X-Date-Used` başlığı = backend'in oturduğu gerçek veri tarihi). Aynı uç nokta:
küre dokusu (dünya, 2048; aralık karelerinde 1024), 2D (bölge kutusu; Dünya'da küreyle AYNI URL), kart
önizlemesi (480). Arayüz → yerel host (HTTP) → FastAPI → NASA. Backend'de DEĞİŞİKLİK YOK.

| Dosya | Ne | Neden |
|---|---|---|
| `frontend/static/eratone-data.js` | **YENİ.** Veri katmanının tamamı: durum (`S`), istek kuyruğu (en çok 3 paralel, ekrandaki istek öne geçer), blob önbelleği (160, LRU), globe.gl küre, 2D yerleşim, kart önizlemeleri, aralık ön-yüklemesi, durum şeridi. `window.eratoneData` (okuma). `?ej=1` test kancası. | Tasarım dosyasını kirletmemek; müzik kiti de aynı kalıpla eklenebilsin. |
| `frontend/static/eratone-data.css` | **YENİ.** `.has-globe` (CSS sahte küre çizgilerini gizler), `.has-flat` (WebGL yoksa yedek), `.has-map`, kart önizleme, `.ej-data-chip` şeridi. | Tasarım CSS'ine dokunmadan üstüne yazmak. |
| `eratone.html` `</head>` öncesi | `<link rel="stylesheet" href="/static/eratone-data.css">` | Tasarım stillerinden SONRA yüklensin (üstüne yazsın). |
| `eratone.html` 6 `.map-card` | `data-theme="dunya_renkleri|sicaklik|okyanus_akinti|bitki|yagis|kuresel_isinma"` | Kart → tema eşlemesi (sıra MAIN_THEMES ile aynı). |
| `eratone.html` `showFrame()` | Sonuna `eratone:frame` olayı `{index, date}` | Kare kaydırıcısı/◀▶ veri katmanına bildirsin (önceden olay yoktu). |
| `eratone.html` küre sürükleme (pointerdown) | `if (g.classList.contains('has-globe')) return;` | Eski CSS küre sürüklemesi pointer'ı yakalayıp globe.gl'in döndürmesini bozuyordu. |
| `eratone.html` `MIN_YEAR` + 2 `<input min>` + uyarı metni | 2000 → **1980** | "Küresel Sıcaklık" (MERRA-2) 1980-01'den başlıyor; 2000 sınırı bu veriyi kapatıyordu. Diğer temalar en yakın veriye oturur, şerit bunu yazar. |
| `eratone.html` `</body>` öncesi | `globe.gl.min.js` (projede zaten vardı, yerel) + `eratone-data.js` | |

**Davranış (kullanıcı gözünden):**
- Açılış: aktif kart (1. Dünya'nın Renkleri), **bugün**, Dünya. Önce küre, sonra 6 kart önizlemesi.
- Kart tıklama → tema değişir, küre/2D yeniden yüklenir (aralık açıksa kareleri de).
- Silindirde tarih seçmek tek başına veri ÇEKMEZ; üstteki **"Görüntüle"** uygular (tasarımın amacı bu; kaydırırken
  her adımda NASA'ya istek atılmasın). Tema/bölge değişince UYGULANMIŞ tarih kullanılır.
- Bölge → küre o bölgeye döner (Dünya'da otomatik dönüş), 2D o bölgenin görüntüsü, kartlar o bölge.
- 2D kutu: bölgenin en/boy oranında (Dünya 2:1, Türkiye 2.5:1, Kuzey Kutbu 12:1), orta sahneye sığan en büyük boy;
  yan paneller açılıp kapanınca yeniden sığar (ResizeObserver).
- Küre: çapı orta sahneye göre (200–760 px), tasarımdaki halkanın ~%86'sı (`WORLD_ALT = 1.45`, ölçümle).
- Aralık: "Görüntüle" → kareler `rebuildFrames()`'in tarihleri; ilk kare gösterilir, hepsi arka planda yüklenir
  (şeritte "önbellek x/n"). Kaydırıcı/◀▶ karede gezinir, silindir kare tarihini gösterir. Kart önizlemeleri aralığın ilk tarihi.
- Şerit: `Tema · Bölge · [kare i/n ·] veri: <gerçek veri tarihi> (istenen tarih için veri yoksa uyarı)`.

**Kare tarihi matematiği:** `rebuildFrames()` (tasarımcının kodu, DEĞİŞTİRİLMEDİ):
`kayma_i = round(i · gün_farkı / (kare − 1))`, i = 0…kare−1 → ilk kare = başlangıç, son kare = bitiş, eşit aralık.
Kullanıcının tarifi "gün / kare". Fark: `/ (kare−1)` iki ucu da dahil eder. Örnek 1985-07-01 → 2025-07-01, 6 kare
→ 1985, 1993, 2001, 2009, 2017, 2025 (doğrulandı). Kare sayısı en çok 60 ve en çok gün+1.
Aylık/8 günlük temalarda birden çok kare aynı veri tarihine oturabilir (şerit gerçek tarihi yazar).

**Doğrulama:**
- Bugünle 6 temanın hepsi 200 (kullanılan tarihler: dunya_renkleri/sicaklik 2026-11-15, bitki/yagis 2026-11-13,
  okyanus_akinti 2024-07-17, kuresel_isinma 2026-08-01). Türkiye 2D 1024×410 (oran 2.5 ✓).
- Headless Edge ekran görüntüleri (`?ej=1` kancasıyla): varsayılan 3D; Sıcaklık+Türkiye+2D; küresel ısınma
  1985→2025 6 kare (kare 6/6 ve kare 3/6, 2D). Konsol hatası 0.
  NOT: headless SwiftShader WebGL tuvalini kaydırılmış çiziyor; küre boyutu GERÇEK pencereden ölçüldü.
- Gerçek WebView2 penceresi (dev + derlenmiş exe) PrintWindow ile yakalandı: küre halkaya oturuyor, kartlar dolu.
  Exe log: 7 `/api/texture` 200, hata 0. `pytest` 40 passed. `node --check` temiz.
- **Test EDİLMEDİ:** gerçek pencerede fareyle sürükleme/yakınlaştırma, 60 karelik aralık süresi, internetsiz açılış,
  `?intro=1` ile birlikte (intro kendi Three.js r128'ini CDN'den yükler; globe.gl kendi Three'sini paketler — çakışma denenmedi).

**Bilinen/açık konular:** "Bugün"ün verisi eksik (bkz. Bilinen sorunlar) · lejant gösterilmiyor · tema/bölge
değişince arka plandaki eski istekler iptal edilir ama O AN çalışan istek biter (boşa birkaç istek) ·
`REGIONS` JS'te app/config.py'nin kopyası (değişirse ikisi birlikte güncellenmeli).

**Sonraki adımlar:** "bugün" kararı · müzik kiti (5b) · lejant · M4 kurulum programı.

### 2026-11-15 — Faz 3: zoom'da 3D korunur, tema bazlı tarih sınırları, netlik

**Yedekler:** öncesi = `..._YEDEK_2026-11-15_faz2-sonrasi` (Faz 2 bitince alındı, Faz 3'e kadar değişiklik yok) ·
sonrası = `..._YEDEK_2026-11-15_faz3-sonrasi`.

**Kullanıcı istekleri:** (1) 3D'de kıtalara/Türkiye'ye zoom yapınca görüntü 3D olmaktan çıkıyor → düzelt;
(2) her veri için üst paneldeki tarih seçicide min/max belirle, dışını tasarımdaki "2026 Aralık kapalı" gibi
seçilemez yap; (3) API görüntülerini netleştirmek mümkünse yap.

**(1) Zoom'da düzleşme — sebep ve çözüm.** Sebep: globe.gl tuvali ~420 px'lik KARE kutuydu; yakınlaşınca küre
kareye kırpılıyor, kenar/ufuk görünmüyor → düz harita gibi. Ayrıca bölge (Türkiye) irtifası 0.35'ti: o irtifada
kürenin açısal yarıçapı (asin(1/1.35)=48°) görüş açısından büyük → kenar ekranda hiç yok.
Çözüm: tuval TÜM orta sahneyi kaplar (`.center-stage.ej-globe-full`; `.globe-stage`'in `perspective`'i kapatıldı,
çünkü mutlak konumlu çocuk için kapsayıcı blok oluşturuyordu). Tasarımın sabit halka/parlaması (::before/::after)
bu modda gizli (küre boyu zoom'la değişiyor; globe.gl atmosferi aynı işi görüyor). Zoom sınırı: `MIN_ALT=0.45`
(elle), bölge seçiminde `REGION_MIN_ALT=0.6`, dünya `WORLD_ALT=1.8` (küre sahne yüksekliğinin ~%74'ü).
Görünüm seçici/yazı boyutu z-index:10 olduğu için kürenin üstünde kalır; `.view-info`'ya z-index:5 verildi.

**(2) Tarih sınırları.** Kaynak: `/api/themes` (GIBS capabilities) `first/last/unit/step`.
`eratone-data.js limitsFor()`: max = son veri (aylıkta son ayın sonu, adım>1'de son dönemin sonu), bugünü geçemez.
Ölçülen aralıklar (2026-11-15): dunya_renkleri/sicaklik 2000-02-24→bugün; yagis 2000-06-01→2026-11-13;
bitki 2025-02-12→2026-11-13; okyanus_akinti 2014-10-22→2024-07-21 (son veri 07-17, 5 günlük); kuresel_isinma 1980-01-01→2026-08-31.
Tema seçilince `window.eratoneSetDateLimits` çağrılır → silindir/ızgara seçici/oklar/aralık paneli sınıra uyar,
sınır dışı silindir öğeleri soluk + üstü çizili (`.cylinder-item.is-out`), ızgarada `disabled` + açıklama.
Uygulanmış tarih aralık dışındaysa içeri çekilir ve şeritte "(X bu veride yok; veri aralığı A – B)" yazar.
Aralık (kareler) uygulanmışsa kareler değiştirilmez (backend en yakına oturur).

**(3) Netlik — ölçümler ve yapılanlar.**
- GIBS WMS genişlik testi (MODIS true color, dünya): 4096 → 16.9 MB / 7.9 sn ✓; 8192 → 65.9 MB / 22.5 sn ✗ (pratik değil).
- `app/config.py TEXTURE_MAX_WIDTH = 4096` + `app/main.py` `/api/texture` width üst sınırı (diğer uç noktalar 2048'de kaldı).
- Küre dokusu ilerlemeli: önce 2048 (hızlı/önbellek), arkadan 4096 gelince değişir (şeritte "yüksek çözünürlük yükleniyor…").
  4096 doku ilk seferde ~13 sn, ~2.9 MB JPEG. Aralık karelerinde 2048 (Faz 2'de 1024'tü).
- **Detay yaması:** irtifa < 1.0 iken bakılan alanın görüntüsü `/api/texture?bbox=…` ile, ekranın derece başına
  pikseline denk genişlikte (2048/4096) çekilir ve globe.gl `tilesData` ile küreye döşenir (tileAltitude 0.0012,
  malzeme = kürenin malzeme sınıfı → aynı ışık). Kutu yüksekliği kovalı (16…80°), merkez ızgaraya oturur → küçük
  dönüşte aynı yama/önbellek. Tarih çizgisini aşmaz (API bbox sınırı). `onZoom` + 450 ms gecikme ile güncellenir.
  Örnek: Türkiye irtifa 0.6 → yama 120°×48° @2048 (~17 px/°; ekran ~15 px/°) vs dünya 4096 (~11 px/°).
- WebGL: `renderer.setPixelRatio(min(2, devicePixelRatio))`, dokulara azami anizotropik filtre.
- 2D: görüntü genişliği kutunun gerçek piksel sayısına göre 1024/2048/4096.
- **Sınır:** verinin kendi çözünürlüğü. MERRA-2 (küresel sıcaklık) ~0.5°, IMERG (yağış) 0.1°, OSCAR (akıntı) 1/3° →
  yakınlaşınca pikselli görünür, daha büyük görüntü çekmek bunu düzeltmez (kıyı çizgisi ve taban harita netleşir).
  MODIS (gerçek renk 250 m, sıcaklık 1 km, NDVI) gerçekten netleşir.

**Faz 2 hatası düzeltildi:** tema değişince `cancelBackground()` kart önizleme isteklerini de iptal ediyordu → 3–6. kartlar
"—" kalıyordu. Artık yalnızca aralık ön-yüklemesi iptal edilebilir (`getImage(url, high, cancelable)`).

| Dosya | Değişiklik |
|---|---|
| `app/config.py` | `TEXTURE_MAX_WIDTH = 4096` (+ ölçüm notu) |
| `app/main.py` | import + `/api/texture` `width` le=`TEXTURE_MAX_WIDTH` |
| `eratone_app.py` | `ERATONE_QUERY` ortam değişkeni (yalnızca test: adrese parametre ekler, örn. `ej=1&pov=39,35,0.6`) |
| `eratone.html` | `dateMin/dateMax`, `paintDrumLimits()`, `setDate`/`stepDay`/`openPicker`/`rebuildFrames` sınırları, `window.eratoneSetDateLimits` |
| `eratone-data.js` | tam sahne küre, zoom sınırları, ilerlemeli 4096, detay yaması, anizotropi/DPR, tarih sınırları, kart iptal hatası, test kancası (`pov`, `picker`, `sizes`) |
| `eratone-data.css` | `.ej-globe-full` kuralları, `.cylinder-item.is-out` |

**Doğrulama:** headless Edge (`?ej=1`): okyanus_akinti → tarih 21 Temmuz 2024'e çekildi, 51 silindir öğesi soluk,
yıl seçicide 47 yıldan 36'sı kapalı (1980–2013, 2025–2026); kuresel_isinma → 31 Ağustos 2026, 2026 ay seçicide 4 kapalı
(Eylül–Aralık); bitki+Türkiye → irtifa 0.6, kavis sağ/solda görünüyor, yama çekildi, kartların hepsi dolu; aralık 3D/2D
regresyonu temiz; konsol hatası 0. Exe: 4096 doku ve bbox yaması 200. `pytest` 40 passed. `node --check` temiz.
**Görsel olarak doğrulanamadı:** tarih seçici ızgarasının kendisi (headless'te açılış animasyonu sanal zamanda ilerlemiyor;
DOM'da açık ve kapalı öğe sayıları doğru), gerçek pencerede fareyle zoom/döndürme hissi, yama kenarlarında dikiş.

**Not (geliştirme sunucusu):** Python (app/) değiştiği için 3000'deki `start.py` sunucusu YENİDEN BAŞLATILMALI;
eskisi `width=4096`'yı 422 ile reddeder (arayüz 2048'de kalır, yama 4096 isterse gelmez).

### 2026-11-15 — Faz 3b: açılış tarihi DÜN

**Yedek:** öncesi = `..._YEDEK_2026-11-15_faz3-sonrasi` (arada değişiklik yok).
**Kullanıcı kararı:** "dünden başlat" (Faz 2'deki "bugünün verisi eksik" sorusuna seçenek a).
**Neden:** bugünün uydu geçişleri gün içinde işlenir; sabah açılışta gerçek renk neredeyse tamamen siyah, sıcaklık boştu.

| Dosya | Değişiklik |
|---|---|
| `eratone.html` `initDate()` | silindir açılışta dün (`t.setDate(t.getDate() - 1)`) |
| `eratone.html` `initRange()` | tarih aralığı panelinin varsayılan bitişi de dün (başlangıç: o yılın 1 Ocak'ı) |
| `eratone-data.js` | `yesterday()`; `S.date` açılışta dün; yorumlar güncellendi |

**Değişmeyen:** bugün hâlâ SEÇİLEBİLİR (`dateMax` = bugün; tema sınırı daha erkense o). Backend'in tarih verilmeyen
isteklerdeki varsayılanı (`app/main.py parse_date` → bugün − 3) dokunulmadı; arayüz her zaman tarih gönderir.
**Doğrulama:** headless Edge: silindir "14 Kasım 2026", istekler `date=2026-11-14` (2048 → 4096 → kart 480), gerçek renk küre
dolu (yörünge boşlukları siyah şerit), konsol hatası 0. Exe yeniden derlendi, paket güncel.

### 2026-11-15 — Faz 4: 2D haritada fare tekerleğiyle zoom

**Yedek:** öncesi = `..._YEDEK_2026-11-15_faz3b-sonrasi` (hash ile doğrulandı: arada değişiklik yok) · sonrası = `..._faz4-sonrasi`.
**Kullanıcı isteği:** "2d kısmına scroll ile zoom atabilme özelliğini ekle".
**Değişen dosyalar:** yalnızca `frontend/static/eratone-data.js` ("2D yakınlaştırma (Faz 4)" bölümü) ve `eratone-data.css`.
eratone.html ve backend DEĞİŞMEDİ.

**Davranış:**
- Tekerlek: imlecin altındaki harita noktası sabit kalarak 1×–12× (`Z_MAX`). Adım: `exp(-deltaY·0.0015)` (deltaMode satır/sayfa da çevrilir).
- Yakınken sürükle = kaydır; görüntü kutuyu hep doldurur (kenardan boşluk yok). Çift tık: 2× yaklaş / zoomdaysa sığdır.
- Sağ altta `+ 1.0× − ⤢` (butonlar 1.6× adım; aria-label'lı, ekran okuyucu oranı duyurur).
- Zoom durumu kutu boyuna ORANLA tutulur (`Z = {s, ox, oy}`) → pencere/panel değişince aynı yer kalır.
- Tema/tarih/aralık karesi değişince zoom KORUNUR (aynı yeri karşılaştırmak için); bölge değişince sıfırlanır.
- **Netlik:** zoom ≥1.3× ve 400 ms durunca, görünen pencerenin boylam/enlem kutusu `/api/texture?bbox=` ile kutunun
  piksel genişliğinde (1024/2048/4096) çekilir ve dönüşümsüz `.ej-map-detail` olarak üstüne konur; zoom/kaydırma
  başlayınca gizlenir (altta dönüşümlü ana görüntü görünür), durunca yenisi gelir. Örnek: bitki+Türkiye 4× → 5°×2° @2048
  ≈ 410 px/° (MODIS NDVI 250 m ≈ 444 px/° — verinin kendi çözünürlüğü). Şeritte "yakın görüntü netleştiriliyor…".
- Zoomdayken tasarımın tarama çizgisi (::after) gizlenir.

**Test kancası eklemeleri:** `z2d=ölçek,u,v` (zoomAt doğrudan), `wheel=n&pan=dx,dy` (gerçek WheelEvent/PointerEvent yolu).
**Doğrulama:** headless: dünya 5× (pencere 72°×36° ✓), Türkiye 4× (bbox 31.75–36.75 / 38.3–40.3 ✓, net görüntü göründü),
6 tekerlek → 2.46× (= e^(6·0.15) ✓), sürükleme sınır içinde ✓, konsol hatası 0. `pytest` 40 passed.
NOT: headless ekran görüntüsü çekilirken sayfa farklı viewport yüksekliğiyle yeniden yerleşiyor (JS 685 px ölçüyor,
görüntü 778 px) — Faz 2'deki "WebGL tuvali kaymış" görüntüsünün de sebebi bu; gerçek pencerede yok.

**⚠ EXE DERLENEMEDİ (bekliyor):** derleme sırasında kullanıcının açık `Eratone.exe`'si (PID 16760) `dist\Eratone`
dosyalarını kilitliyordu → PyInstaller `PermissionError` ile yarıda kaldı (betik yine de "Hazir" yazdı — yanıltıcı;
`build_eratone.ps1` iyileştirilmeli: paket dosya hash'i kontrolü). Klasörden bir kısım dosya silinmiş olabilir
(89.1 → 88.8 MB). **Eratone kapatılınca `build_eratone.ps1` yeniden çalıştırılmalı.**
**Betik düzeltildi:** `build_eratone.ps1` artık Eratone açıksa başlamaz, PyInstaller çıkış kodunu kontrol eder ve
paketteki `frontend/static` dosyalarını hash ile projedekilerle karşılaştırır; sorun varsa "DERLEME BASARISIZ" + çıkış 1.
(Doğrulandı: Eratone açıkken "ERATONE ACIK (PID …)" yazıp 1 ile çıktı.)

### 2026-11-15 — Faz 5: world-sound müzik sistemi bağlandı (enstrümanlar + ekolayzer)

**Yedek:** öncesi = `..._YEDEK_2026-11-15_faz4-sonrasi` (arada değişiklik yok) · sonrası = `..._faz5-sonrasi`.
**Kullanıcı isteği:** `C:\Users\EXCALIBUR\Desktop\world-sound` (kullanıcının müzik sistemi) projeye KOPYALANSIN,
kodlar tamamen okunsun; enstrümanlar ve ekolayzer sisteme bağlansın; müzik verisi kendi içinden değil BİZİM
uygulamadan gelsin; `baslat.bat` ve PNG'ler (kopyada) temizlensin; ASIL KLASÖRE DOKUNULMASIN.

**world-sound nedir (okunarak çıkarıldı, OKUBENI.md ile uyumlu):** Python kütüphanesi `worldsound`.
`MapSonifier` tek giriş noktası. Harita (RGBA, alpha=0 = ölçüm yok) → görünen bölge (Viewport, normalize ya da
boylam/enlem) → 36×64 ızgara, her hücre piksel OY ÇOKLUĞUYLA nota alır (renk ortalaması değil) → renk→nota:
kırmızı en tiz, mavi en pes, ara renkler orantılı, dizinin en yakın notası (Do majör, Do2–Si6) → siyah/beyaz/gri/
şeffaf SESSİZ → tekrar filtresi (dikey: aynı nota bir kez; yatay: sürer, yeniden tetiklenmez; en çok N nota) →
tarama çizgisi soldan sağa (sütun/sn) → her nota açık TÜM enstrümanlarda (wavetable sentez, ADSR) → 5 bant EQ
(RBJ biquad: 100 Hz raf, 300/1k/3k tepe, 8k raf; ±12 dB) → Schroeder yankı → limiter → sounddevice (hoparlör).
Iraksak kip (akıntı/anomali): solukluk = şiddet. Kendi NASA istemcisi `NasaGibsSource` (Eratone'da KULLANILMAZ).
Kendi testleri: 17/17 (ses kartı gerekmez).

**Kopya:** `world-sound/` (proje kökü). 25 dosya hash ile birebir kopyalandı, sonra KOPYADAN silindi:
`baslat.bat`, `samples/*.png` (2) + boş `samples/`, 4 `WhatsApp Image*.jpeg` (test uygulamasının örnek haritaları;
kullanıcı "png" dedi, JPEG'ler de aynı işi gördüğü için silindi — orijinalde duruyor). `test_app.py`,
`ornek_entegrasyon.py`, `sources.py` (NasaGibsSource) DOKUNULMADAN duruyor (bağımsız çalışmaya devam eder;
`find_images` örnek yoksa boş döner). `OKUBENI.md`'ye kopya notu eklendi, `baslat.bat` satırı güncellendi.
Orijinal klasör: 25 dosya, değişmedi (her adımda kontrol edildi).

**Mimari:**
```
eratone.html (tasarım)          eratone-data.js                      eratone-audio.js (YENİ)
 Oynat/Döngü/enstrüman/mixer ──► 'eratone:audio' ───────────────────► POST /api/audio/play|loop|instrument
 .eq-slider 'input' ─────────────────────────────────────────────────► POST /api/audio/eq
                                 'eratone:view' {theme,date,source,box} ► POST /api/audio/source + /view
                                                                       GET /api/audio/state (~8/sn çalarken)
app/main.py /api/audio/* ──► app/audio.py AudioBridge ──► world-sound MapSonifier ──► hoparlör (sounddevice)
                              └ katman: maps.snap_date + maps.fetch_layer (uygulamanın önbellekli GIBS istemcisi)
```
- **Veri bizim uygulamadan:** `load_source` temanın GIBS katmanını (`maps.fetch_layer`, ŞEFFAF PNG — Blue Marble/kıyı
  karışmamış ham veri) kaynak kutuda 2048 px genişlikte çeker → `MapData` (meta `source: "eratone"`) → `MapSonifier.load`.
  Aynı katman/tarih/önbellek arayüzle ortak (dünya 2048 isteği küre dokusunun içindeki katmanla aynı URL → disk önbelleği).
- **Kaynak kutu:** 2D'de bölge kutusu, 3D'de tüm dünya. **Görünen kutu:** 2D'de zoom penceresi; 3D'de irtifa < 1.0
  ise bakılan alan (detay yamasıyla aynı hesap), değilse bölge (Dünya'da tüm dünya). Görünüm yeni kaynakta korunur.
- **Eşleme:** arayüz `acoustic_guitar→aguitar, electric_guitar→eguitar, piano, flute, violin`; worldsound'daki
  `bass` ve `pad` arayüzde olmadığı için KAPALI. EQ kaydırıcıları sırayla `bass, low_mid, mid, high_mid, treble`.
  **EQ etiketleri** motorun gerçek frekanslarına göre düzeltildi (eratone.html, yalnız metin): 60Hz→100Hz,
  250Hz→300Hz, 4kHz→3kHz, "Tiz & Kristal (Air 12kHz)"→"Tiz (8kHz)". Kaydırıcı kimlikleri (`val-60hz` …) DEĞİŞMEDİ.
- **Iraksak kip:** `okyanus_akinti`, `isinma_anomali` → `diverging=True`.
- **Motor ayarları** (world-sound test uygulamasındaki gibi): 5 sütun/sn, en çok 10 nota, yankı 0.25, ana ses 0.8.
- **Tembel başlatma:** İlk "Çal"a kadar backend'e HİÇBİR şey gitmez (motor/ses kartı/NASA isteği yok). İlk "Çal"da
  arayüzün enstrüman/ses düzeyi/EQ/döngü durumu toplu gönderilir; sonra her değişiklik anında.
- **Döngü kapalıyken** tarama bir tur sonunda motor kendiliğinden durur → arayüz Oynat düğmesini geri alır.
- **Görsel geri bildirim:** çalan notalar şeridi (`.ej-notes`, veri şeridinin üstünde), 2D'de kırmızı tarama çizgisi
  (`.ej-scanline`, konum = görünen pencere içindeki tarama), ekolayzer panelindeki 8 çubuk gerçek spektrumla
  (48 bant → 8; tasarımın sahte animasyonu çalarken durur, `.eq-visualizer.ej-live`).
- **Log:** `/api/audio/state` istek logundan muaf (main.py middleware); masaüstünde uvicorn `access_log=False`.
- **Kapanış:** lifespan → `audio.bridge.close()` (ses kartı bırakılır).
- `ERATONE_NO_AUDIO=1` → ses kartı açılmaz (testler / sessiz deneme).

| Dosya | Ne |
|---|---|
| `world-sound/` | **YENİ** — kullanıcının müzik sisteminin temizlenmiş kopyası (yukarıda) |
| `app/audio.py` | **YENİ** — `AudioBridge` (tembel motor, uygulama katmanı → MapData, görünüm, komutlar, durum), `bridge` tekil |
| `app/main.py` | `/api/audio/source|view|play|loop|instrument|eq` (POST, JSON, pydantic doğrulama) + `GET /api/audio/state`; lifespan kapanışı; log muafiyeti; docstring istisnaları |
| `frontend/static/eratone-audio.js` | **YENİ** — arayüz ↔ /api/audio köprüsü, nota şeridi, tarama çizgisi, canlı EQ çubukları |
| `frontend/static/eratone-data.js` | `viewBox()`, `emitView()` (en çok 4/sn), render/applyZ/onZoom/bölge'de çağrı; test kancası `play=1` |
| `frontend/static/eratone-data.css` | `.ej-notes`, `.ej-scanline`, `.eq-visualizer.ej-live` |
| `frontend/static/eratone.html` | `<script src="/static/eratone-audio.js">` + 4 EQ etiketi metni |
| `eratone_app.py` | uvicorn `access_log=False` |
| `tests/test_audio.py` | **YENİ** — 6 test (internet/ses kartı gerekmez): veri uygulamadan gelir, eşleme, görünüm→nota, görünüm korunur, ıraksak kip, uç noktalar |
| `requirements.txt` | `scipy`, `sounddevice` |
| `Eratone.spec` | `pathex=['world-sound']`, `collect_submodules('worldsound')`, `sounddevice`, `_sounddevice_data` (PortAudio DLL) |

**Doğrulama:**
- `pytest`: 63 passed (40 eski + 6 ses köprüsü + 17 world-sound kendi testleri; pytest world-sound/tests'i de toplar).
- Gerçek ses kartı, ana ses 0 (DUYULMADAN): kart açıldı (Realtek), `kuresel_isinma` 2025-07-01 uygulamanın istemcisiyle
  çekildi (meta `source: eratone`), Türkiye görünümünde Sol6/La6/Si6 (Temmuz sıcak = kırmızı = tiz), tarama ilerledi, durdu.
- Headless Edge (ses kartı kapalı sunucu, `?ej=1&theme=sicaklik&region=Türkiye&view=2d&z2d=2,…&play=1`): Çal'dan önce motor
  YOK; sonra kaynak sicaklik/Türkiye, görünüm 30–40°/37–41° (2× zoom penceresi), akustik gitar açık %80, diğerleri kapalı,
  EQ +2/0/+4/+1/+5 (arayüz varsayılanları), döngü kapalı; istekler 5 instrument, 5 eq, 1 loop, 1 play, 1 source, 2 view; konsol hatası 0.
- **Duyarak test EDİLMEDİ** (kullanıcının hoparlöründe ses çalınmadı). Exe derlenmedi (aşağıda).

~~**⚠ EXE DERLENMEDİ**~~ → **DERLENDİ (2026-11-15, Faz 5 sonrası):** `build_eratone.ps1` → çıkış 0, "arayüz dosyaları
doğrulandı", klasör **162.3 MB** (önce 89 MB; artış scipy + PortAudio). Exe içinde doğrulandı (Çal'a basılmadan, ses çıkmadan):
`/api/audio/instrument` motoru kurdu, `audio_out=True`, hata yok; `/api/audio/source` kuresel_isinma 2025-07-01 2048×1024 yükledi.

**Eski exe log hataları — açıklama:** `%LOCALAPPDATA%\Eratone\logs\eratone.log`'da 443 `FileNotFoundError` vardı; HEPSİ 07:48–09:23
oturumlarında, `/api/texture` isteklerinde (500). Sebep: Faz 4'te yarıda kalan derleme (açık exe dosyaları kilitliyordu)
`dist\Eratone`'dan dosya silmişti — büyük ihtimalle `certifi\cacert.pem` (dosya adı vermeyen FileNotFoundError, httpx'in SSL
sertifika paketini yüklerken verdiği hata ile aynı) → NASA'ya HTTPS isteği atılamıyordu. Kullanıcı o arada bozuk paketi kullandı.
Yeni pakette `cacert.pem` var; yeni derlemenin oturumunda NASA isteği başarılı, hata 0. (Faz 4'te `build_eratone.ps1` artık açık
exe varken başlamıyor, aynı durum tekrarlanmaz.)

**Jüri/takım özet sayfası:** https://claude.ai/artifact/SuG4SzjsLK8VYgUcPKtvRv (özel; paylaşmak için sayfanın Share menüsü).
Kaynağı geçici klasörde (scratchpad `eratone-ozet/`), uygulamanın headless ekran görüntülerinden 3 görsel içerir.

### 2026-11-15 — Harita önbelleği: yalnızca en güncel veri kalır, kapanışta eskiler silinir

**İstek:** "önbellek verilerinde sadece en güncel verileri tutsun, uygulama kapatıldığında eski verileri silsin (haritalar)".
**Yedek:** `Desktop\earth-jukebox-backend_YEDEK_2026-11-15_onbellek-oncesi\` (değişen 4 dosyanın önceki hâli).

**Durum (önce):** hiçbir şey silinmiyordu. `%LOCALAPPDATA%\Eratone\cache\wms` 707 dosya / 425 MB; ayrıca WebView2'nin HTTP
önbelleği (`webview\EBWebView\Default\Cache`) aynı harita görüntülerinin ikinci kopyasını tutuyordu: 287 MB.

**Ne yapıldı:**
1. `app/gibs_api.py` — harita görüntüleri (wms/wmts) artık klasörlere ayrılıyor:
   `cache/wms/<katman>/<YYYY-MM-DD | _tarihsiz>/<sha1>.png`. Dosya adları hash olduğu için tarih başka türlü bilinemiyordu.
   Yeni `prune_map_cache()`:
   - tarihli katman → **her katman için yalnızca en yeni tarih klasörü kalır** (açılış "dün" olduğu için sonraki açılış hızlı),
   - tarihsiz katman (Blue Marble, kıyı) → yalnızca **bu oturumda kullanılanlar** kalır (önbellekten okununca `os.utime` ile
     işaretlenir; zoom'da üretilen eski bölge görüntüleri gider),
   - eski düz düzendeki dosyalar (Faz 0–5, `wms/<sha1>.png`) silinir → mevcut 425 MB ilk kapanışta temizlenir,
   - renk haritaları, capabilities, lejant, EONET **korunur** (küçük, tarihten bağımsız, ağ yokken uygulamayı ayakta tutar).
2. `app/main.py` — lifespan kapanışında `prune_map_cache()` (hata olsa da kapanış sürer, sonuç log'a `[ONBELLEK]` satırı).
   Middleware: `/api/*` yanıtlarına `Cache-Control: no-store` → WebView2 haritaları kendi diskine yazmaz (arayüz zaten blob
   LRU'da, sunucu diskte tutuyor). `/static` normal önbelleklenir.
3. `eratone_app.py` — pencere açılmadan önce `EBWebView\Default\Cache` silinir (eski 287 MB'ı temizler; kapanışta değil çünkü o
   an WebView2 süreci dosyaları kilitli tutabiliyor). `Local Storage` (tercihler) ayrı klasörde, dokunulmaz.

**Neden kapanışta (açılışta değil):** kullanıcı öyle istedi; ayrıca açılışta "oturumda kullanılan" bilgisi henüz yok. Uygulama
Görev Yöneticisi'nden öldürülürse temizlik o sefer atlanır, bir sonraki normal kapanışta yapılır (kural içeriğe bakıyor).
Geliştirme sunucusu (`start.py`, proje `cache/`) da aynı lifespan'ı kullanır → aynı temizlik.

**Dokunulmayan:** `%LOCALAPPDATA%\EarthJukebox\cache` (~46 MB) — eski NiceGUI/EarthJukebox exe'sinin önbelleği, Eratone kullanmıyor.
Kullanıcı onaylarsa elle silinebilir.

**Doğrulama:** `pytest` 66 passed (+3: `tests/test_cache.py` — klasör düzeni, en yeni tarih kalır/eskiler ve boş klasörler gider,
boş önbellek). Gerçek uvicorn + NASA (geçici CACHE_DIR): kuresel_isinma 2025-06 ve 2025-07 çekildi → kapanışta 2025-06 silindi,
2025-07 + Blue Marble + kıyı kaldı; `/api/texture` yanıtında `Cache-Control: no-store`.

**Ek bulgu — lifespan kapanışı exe'de HİÇ çalışmıyordu (düzeltildi):** ilk exe testinde temizlik olmadı. Log: "Shutting down →
Waiting for background tasks to complete" ve orada kalıyor; süren NASA istekleri bitmeden `Backend.stop()` 5 sn'de zaman aşımına
uğruyor, süreç bitiyor → `lifespan` sonrası (Faz 5'ten beri `audio.bridge.close()` dahil) hiç çalışmamış. uvicorn 0.54'te
`force_exit` lifespan'ı da atlıyor, o yüzden çözüm `timeout_graceful_shutdown=2`: 2 sn sonra görevler iptal, sonra lifespan kapanışı.
- `eratone_app.py`: `uvicorn.Config(..., timeout_graceful_shutdown=2)`, `stop()` join 5 → 15 sn.
- `start.py`: `uvicorn.run(app, host=HOST, port=PORT, timeout_graceful_shutdown=2)` (önce: `uvicorn.run(app, host=HOST, port=PORT)`;
  bu dosya yedekte yok, tek satır değişti).

**Gerçek önbellekte sonuç (exe kapanışı, 2026-11-15 ~10:59):** `[ONBELLEK] kapanista 707 eski harita silindi (425.5 MB)`;
`cache\wms` 425 MB → 12 dosya / 30.5 MB (6 katman, her biri tek klasör: en yeni tarih / `_tarihsiz`). WebView2 `Cache`
287 MB → 6.5 MB (açılışta silindi; kalan 6.5 MB statik JS/CSS/font).

**⚠ Derleme durumu (2026-11-15 ~11:00):** temizlik düzeltmesinden sonraki derleme BAŞARISIZ: `dist\Eratone` silinirken
`ClrLoader.dll` kilitliydi (ilk testin süreci/antivirüs). PyInstaller yarıda kaldı → `dist` yine eksik (`certifi\cacert.pem` yok →
yeni harita NASA'dan indirilemiyor, yalnızca önbellekteki açılıyor). Ardından kullanıcı 11:00:35'te bu eksik paketi açtı; süreç
kapatılmadı (kural). → **ÇÖZÜLDÜ** (aşağıdaki bölümün sonunda yeniden derlendi). Kullanıcının o sırada gördüğü "HTTP 500"
hataları bu eksik paketten (100× `FileNotFoundError`, sertifika dosyası yok).

### 2026-11-15 — Aralık kareleri: otomatik oynatma + hızlı yükleme + HTTP 500 açıklaması

**İstek:** "http 500 hatası alıyorum fixleme yap; tarih aralığı seçtiğim zaman otomatik olarak oynatma butonunu ayarla, kareleri
otomatik olarak izlettirsin, hızlı apileri alsın, kare görüntüleri çok geç geliyor."
**Yedek:** `Desktop\earth-jukebox-backend_YEDEK_2026-11-15_oynatici-oncesi\` (10 dosya: app/config, sound, gibs_api, main;
frontend eratone-data.js/.css, eratone.html; eratone_app.py, start.py, CONTEXT.md).

**HTTP 500:** kod hatası değil — kullanıcının açtığı exe yarım kalan derlemenin eksik paketiydi (yukarı bkz.). Yeniden derlendi,
`cacert.pem` var, exe testinde kapanış öncesi hata 0.

**Neden geç geliyordu (ölçüldü, boş önbellek):** kare = NASA WMS 2048×1024 (2–5 sn, değişken). Arayüz aynı anda 3, backend 4 istek →
12 kare 27.6 sn (paralel 3) vs 5.8 sn (paralel 12). Ayrıca GIBS bazen bir isteği asılı bırakıyor ya da 5xx dönüyor; aynı URL
yeniden atılınca 2–4 sn'de geliyor, ama uygulama 60 sn bekliyordu → oynatıcı o karede takılıyordu, sonra 502.
Birleştirme (taban+veri+kıyı+JPEG) 2048'de ~55 ms: darboğaz değil.

**Yapılanlar:**
| Dosya | Değişiklik |
|---|---|
| `app/config.py` | `MAX_PARALLEL_GIBS` 4 → 8; yeni `HTTP_READ_TIMEOUT = 20` |
| `app/gibs_api.py` | httpx `Timeout(60, connect=10, read=20)` → asılı istek 20 sn'de kesilip yeniden atılır (mevcut 3 deneme döngüsü); GIBS 500/502/503/504 da yeniden denenir; `_inflight`: aynı görüntü aynı anda istenirse NASA'ya TEK indirme (`asyncio.shield`) |
| `app/sound.py` | `texture()` birleştirmeyi `_compose()`'a ayırdı, `asyncio.to_thread` ile çalışır (olay döngüsü bloklanmaz) |
| `frontend/static/eratone-data.js` | `MAX_PARALLEL` 3 → 6; 2D aralık kareleri en çok 2048 (`RANGE_MAP_W`); ön-yükleme şu anki kareden ileri sırayla; **aralık oynatıcısı** (aşağıda); oynatırken detay yaması (3D) / detay görüntüsü (2D) istenmez; test kancası `plog=1`, `rdelay=ms` |
| `frontend/static/eratone-data.css` | `.ej-player` (durum şeridinin üstünde, ortada) |
| `tests/test_cache.py` | +2: aynı görüntü tek indirme, GIBS 504 → tekrar |

**Aralık oynatıcısı** (`eratone-data.js` "aralık oynatıcı"; `P` durumu en üstte, S'nin altında):
- Aralık panelinde "Görüntüle" → kareler KENDİLİĞİNDEN oynar, sonda başa döner. Sahnede ▶/⏸ + "Kare i/n · tarih" + hız düğmesi
  (0.5 / 1 / 2 / 4 kare/sn, varsayılan 1).
- Sonraki kare yüklenmeden geçilmez (şerit "sonraki kare yükleniyor…"). 5 sn'den uzun gecikirse (`SKIP_MS`) hazır olan sonraki
  kareye atlanır; geciken kare arkada yüklenir, sonraki turda görünür. Alınamayan kare (`failed`) beklenmeden geçilir.
- Kareler `#frame-slider` üzerinden ilerletilir (eratone.html `showFrame`) → üstteki tarih silindiri ve paneldeki kaydırıcı aynı
  kareyi gösterir. ◀ ▶ / kaydırıcıya elle dokunmak duraklatır (`P.self` ile ayırt edilir). Üstteki tek tarih "Görüntüle" → durur, gizlenir.
- Ana ▶ (müzik) düğmesinden BAĞIMSIZ. Müzik çalarken her kare `eratone:view` yayınlar → ses kaynağı o karenin tarihine geçer
  (dokunulmadı; aynı WMS URL'si → diskten).
- eratone.html'e DOKUNULMADI.

**Doğrulama:**
- `pytest` 68 passed.
- Headless Edge, geliştirme sunucusu, boş önbellek, `sicaklik` 12 kare:
  - açılışla aynı anda aralık (en kötü durum): 11/12 kare ~26 sn; 6. kare NASA'da takıldı → oynatıcı 5 sn sonra atladı, döngü sürdü.
  - açılış bittikten sonra aralık (`rdelay=15000`, gerçek kullanım): 2. kare **3 sn**, 9/12 kare 7 sn, 12/12 kare 13 sn; sonra
    1 kare/sn takılmadan döngü. Ekran görüntüsünde oynatıcı ⏸ "Kare 1/12 · 1 Haziran 2023" "1 kare/sn".
- Exe yeniden derlendi (çıkış 0, 162.3 MB, `cacert.pem` var). Exe'de `ERATONE_QUERY` ile 2022 aralığı: 14 NASA isteği; pencere
  kapatılınca **3.9 sn**'de kapandı, "Cancel 2 running task(s)" → `[ONBELLEK] kapanista 16 eski harita silindi` (2022 kareleri dahil).
  Log'daki tek hatalar kapanışta iptal edilen 2 indirmenin `CancelledError`'ı (beklenen, kapanıştan sonra).
- Gerçek pencerede (kullanıcının ekranında) oynatıcıya bakılmadı; ekran görüntüsü headless.

### 2026-11-15 — Açılış animasyonu, seslendirme modu sadeleşti, birleşik Görüntüle, Harita düğmesi

**İstek:** giriş animasyonu (intro tarzı, bitince uygulamaya geçsin); alt panelde 3D Uzamsal + Erişilebilir kalksın, Erkek/Kadın
"Seslendirme Modu" altında ortalı; Tarih Aralığı panelindeki Görüntüle kalksın, iki Görüntüle birleşsin, panelde aralığı
aktifleştiren düğme olsun (aktif → aralık, değil → tek görsel); sol üstteki "Harita AÇIK [anahtar]" → yalnızca ikon + "Harita".
**Yedek:** `Desktop\earth-jukebox-backend_YEDEK_2026-11-15_arayuz-intro-oncesi\` (eratone.html, eratone-data.js/.css,
eratone_app.py, Eratone.spec, CONTEXT.md).

**1. Açılış animasyonu** (tasarımcının Three.js girişi, önceden `?intro=1` ile ve "Sistemi Başlat"a basınca çalışıyordu):
- Varsayılan AÇIK. `?intro=0` (exe: `--no-intro` / `ERATONE_INTRO=0`) kapatır; test kancası `?ej=1` atlar (`ej=1&intro=1` zorlar).
- Kendiliğinden oynar: "Sistemi Başlat" gizli; dünya dokuları hazır olunca 1.4 sn döner (`AUTO_IDLE_MS`), sonra fırlatma
  (3.2 sn) → dalış (1.5 sn) → `eratone:started` → 1 sn (önce 2 sn) → 1.4 sn solma → uygulama. Doku gecikirse en geç 6 sn'de
  başlar (`AUTO_MAX_MS`, prosedürel yüzey). "Atla" düğmesi duruyor. Bekleme yazısı "Dünya verisi hazırlanıyor" (`TEXT.idle`;
  çizim döngüsü her 90 ms `TEXT[state]` yazdığı için setReadout yetmiyordu).
- İnternetsiz: Three.js r128 + 3 doku (earth_day/night/bump_roughness_clouds_4096) `frontend/static/vendor/intro/`'a indirildi
  (2.8 MB; kaynak cdnjs ve three.js deposu, MIT). Exe'ye `frontend/static` ile birlikte girer.
- Arka planda uygulama aynı anda yüklenir (NASA verisi animasyon sürerken gelir).
- Ölçüm (headless Edge, gerçek zaman): fırlatma 2.3 sn, uygulamaya geçiş 8.9 sn (+1.4 sn solma). NOT: `--screenshot/--dump-dom
  --timeout` modlarında zamanlayıcılar gerçek zamanlı ilerlemiyor → orada animasyon "takılı" görünür; test canlı modda yapıldı.
- `eratone_app.py`: `SHOW_INTRO`/`--intro` → `NO_INTRO`/`--no-intro`.

**2. Seslendirme modu:** `data-voice="spatial"` ve `"screen_reader"` düğmeleri HTML'den silindi (başka bağımlılık yoktu).
`.bottom-player .voice-btn-group { justify-content: safe center }` → Erkek/Kadın başlığın altında ortalı.

**3. Birleşik Görüntüle:**
- Paneldeki `#btn-view-range` gizli (`hidden` + `display:none !important`; JS dinleyicisi için DOM'da duruyor).
- Panel başlığına `#range-mode` anahtarı (role=switch, "Aralık kapalı/açık"). Yalnızca modu değiştirir; uygulamak için üstteki
  `#btn-view-date` "Görüntüle": `rangeMode ? viewRange() : viewDate()`. Açıkken panel alanları tam opak, "Tarih Aralığı"
  düğmesinde camgöbeği nokta (`.btn-range.range-on`); kapalıyken alanlar %60 soluk (yine düzenlenebilir). Görüntüle'nin
  title/aria-label'ı moda göre değişir. Varsayılan kapalı (her açılışta).
- `window.eratoneSetRangeMode(on)` (test kancası kullanır). eratone-data.js test kancası: `range=` → mod aç + üstteki Görüntüle;
  yeni `rpanel=ms` paneli açar.
- Aralık uygulanınca kareler yine kendiliğinden oynar (önceki bölüm).

**4. Harita düğmesi:** `#map-state` ("Açık") ve `.map-switch` HTML'den silindi; yalnızca ikon + "Harita". Tıklama mantığı aynı
(`toggleMaps`, `syncMapsButton` — `map-state` yoksa atlar). Panel açıkken düğme camgöbeği vurgulu (`.active`).

**Doğrulama:** `pytest` 68 passed; `node --check` eratone-data.js; headless ekran görüntüleri: Harita düğmesi yalnızca
ikon+yazı, Erkek/Kadın ortalı, panel başlığında "Aralık kapalı" anahtarı, panel altında Görüntüle yok; animasyon kendiliğinden
başlayıp uygulamaya geçiyor (konsol izleme, sonra izleme satırları silindi). Konsol hatası yok.
~~**⚠ Exe DERLENMEDİ**~~ → **DERLENDİ ve gerçek pencerede kontrol edildi** (kullanıcı kapattıktan sonra; çıkış 0, 165 MB,
`vendor/intro` 4 dosya pakette). PrintWindow yakalamaları (gerçek WebView2 penceresi):
- normal açılış: 6. sn animasyon (gerçek Blue Marble dokulu küre, "ERATONE / Hear the changing Earth"), 18. sn uygulama
  (Harita düğmesi yalnızca ikon + "Harita"). Log: kapanıştan önce hata 0, `vendor/intro` 404 yok, kapanışta `[ONBELLEK]`.
- `ERATONE_QUERY` ile aralık: panel başlığında "ARALIK AÇIK", panel altında Görüntüle yok, "Tarih Aralığı"nda nokta,
  oynatıcı "Kare 10/12 · 21 Temmuz 2024 · 1 kare/sn", 12/12 kare ~12 sn, üst tarih + kaydırıcı aynı kare.
- Bu kontrolde bulunan hata düzeltildi: durum şeridinde açılıştan kalan "yüksek çözünürlük yükleniyor…" aralık karelerinde
  kalıyordu (eski isteğin `t !== token` dalı chipExtra'yı temizlemiyordu) → `render()` başında `chipExtra = ''`. Yeniden
  derlendi, son yakalamada şerit "kare 6/12 · veri: 29 Haziran 2024 · önbellek 12/12"; kapanış 2.1 sn, hata 0.
- Yakalamada alt panel pencerenin altında kaldı (DPI ölçekli pencere boyutu); Erkek/Kadın ortalaması headless görüntüde doğrulandı.

### 2026-11-15 — HATA: küre görüntüleri soluk/bembeyaz (giriş animasyonu yüzünden) + "Sistemi Başlat" geri geldi

**Şikâyet:** "API'den gelen görseller bozuldu, çok çirkin, kontrastı düzelt" + "Sistemi Başlat'ı neden kaldırdın, ona basınca girsin".
**Yedek:** `Desktop\earth-jukebox-backend_YEDEK_2026-11-15_renk-buton-oncesi\` (eratone.html, eratone-data.js, CONTEXT.md).

**Kök neden (ölçüldü):** API görüntüleri DEĞİŞMEMİŞTİ. Giriş varsayılan olunca Three.js r128 global `window.THREE` olarak yüklendi.
globe.gl (`vendor/globe.gl.min.js`, `window.THREE` 3 kez okuyor) global THREE varsa paketindeki yeni Three.js yerine onu kullanıyor
→ küre r128 ile çizildi: `outputEncoding 3000` (doğrusal, sRGB dönüşümü yok) → dokular yıkanmış/bembeyaz. Test kancası `three=1`:
düzeltme öncesi `window.THREE object, outputEncoding 3000`; sonrası `window.THREE undefined, outputColorSpace srgb` (giriş kapalıyla aynı).
Log'daki "Multiple instances of Three.js being imported" uyarısı bunun işaretiydi (gözden kaçmıştı).
**Düzeltme:** giriş betiğinin başında `const THREE = window.THREE; delete window.THREE;` → r128 yalnızca girişe ait, globe.gl
yüklenirken global THREE yok. **KURAL:** sayfaya global THREE koyan hiçbir şey globe.gl'den önce yüklenmemeli.
Exe'de doğrulandı: animasyon yüklü + `introskip` sonrası küre doğal renk/kontrast (önceki `kure.jpg` ile aynı).

**Sistemi Başlat:** otomatik başlatma kaldırıldı, düğme görünür; basınca fırlatma → dalış → uygulama ("Atla" da duruyor).
`TEXT.idle` özgün metnine döndü ("İmleci gezdir · Sürükleyerek döndür").

**Yeni test kancaları:** `?introskip=ms` (girişi bu süre sonra atla; giriş yüklüyken renk testi), `?ej=1&three=1` (küre çizicisinin
Three.js bilgisi konsola).

**build_eratone.ps1 GÜVENLİ DERLEME:** iki kez derleme sırasında açık/açılan Eratone `dist\Eratone`'u kilitledi, PyInstaller eski
klasörü yarım silip `cacert.pem`'i götürdü (kullanıcı bozuk paketle HTTP 500 aldı; 12:11'de yine oldu). Artık:
`--distpath build\dist_yeni` → doğrula (arayüz dosyaları + cacert) → `dist\Eratone`'u `Eratone_eski` olarak yeniden adlandır
(kullanımdaysa Windows izin vermez → eski paket SAĞLAM, çıkış 2, mesaj) → taşı → eskiyi sil. Eratone açıkken de derlenebilir;
`-Yerlestir` hazır paketi derlemeden yerine koyar. Bu oturumda: derleme çıkış 0, 165 MB, cacert var; exe'de hata 0.

### 2026-11-15 — Temizlik (boyut 663 → 422 MB) + `kurulum.py` + paylaşım paketleri

**İstek:** kullanılmayan dosya/kodları sil (çalışanlara dokunma), boyutu düşür; ekip arkadaşlarının indirip çalıştırabileceği
`kurulum.py` gibi bir betik.
**Yedek:** `Desktop\earth-jukebox-backend_YEDEK_2026-11-15_temizlik-oncesi\` (silinen/değişen 35 dosya, 50.6 MB, aynı göreli
yollarla + `venv_pip_freeze.txt` + `GERI_DONUS.txt`). `build\` ve `cache\` yedeklenmedi (yeniden üretilir).

**Nasıl karar verildi:** `eratone.html`'in yüklediği dosyalar (7 + fonts.css'teki 4 font + giriş JS'inin 3 dokusu) ve Python
import zinciri (`main.py` → app/* modüllerinin HEPSİ; compare/sonify/colormap dahil) çıkarıldı; bunların dışında kalanlar silindi.

**Silinenler:**
| Ne | Boyut | Neden kullanılmıyordu |
|---|---|---|
| `build\` | 107 MB | PyInstaller ara dosyaları; her derlemede baştan üretilir |
| `dist\EarthJukebox.exe` + `desktop_app.py`, `EarthJukebox.spec`, `build_exe.ps1` | 38 MB | eski tkinter API test aracı |
| `cache\` | 33 MB | geliştirme önbelleği; uygulama yeniden oluşturur |
| `frontend/static/soundfonts/` (4 mp3.js), `jukebox.js`, `style.css`, `vendor/leaflet.*`, `vendor/soundfont-player.min.js` | 10.7 MB | eski NiceGUI arayüzünün dosyaları; eratone.html yüklemiyor |
| `frontend/ui.py`, `frontend/__init__.py` | 45 KB | eski NiceGUI arayüzü (dondurulmuştu) |
| `docs/gibs_capabilities.xml` | 2.2 MB | `scripts/check_layers.py` her çalıştığında yeniden indirip yazar |
| `docs/frontend-ornek.js`, `run_server.py`, `exe_err.log`, `exe_out.log`, `postman/`, `.postman/`, tüm `__pycache__`, `.pytest_cache` | ~0.2 MB | eski örnek/araç/log |
| `.venv`: nicegui + yalnızca ona bağlı 27 paket (aiohttp, docutils, socketio, jinja2, …) | 40 MB | yalnızca NiceGUI kullanıyordu; `pip check` temiz |

**Kod değişiklikleri (çalışan koda dokunulmadı):**
- `tests/test_sound.py`: `test_speakable_reads_turkish` kaldırıldı (silinen `frontend/ui.py`'yi test ediyordu) → 67 test.
- `requirements.txt`: `nicegui` ve `pytest` çıktı; `requirements-dev.txt`: `pytest` eklendi.
- `Eratone.spec`: excludes `['tkinter', 'pytest']` (nicegui/frontend.ui artık yok); eski spec notu silindi.
- `start.py` docstring, `.gitignore` (`!Eratone.spec`, `paylasim/`, `*.log`, `.pytest_cache/`), `README.md` baştan yazıldı
  (eskisi NiceGUI + EarthJukebox.exe anlatıyordu).
- Bilinen önemsiz uyarı: testlerde starlette "httpx yerine httpx2 kurun" DeprecationWarning (httpx2 nicegui ile gitti; yalnızca TestClient).

**Yeni `kurulum.py`** (Python 3.10+ 64 bit, Windows): `python kurulum.py` → `.venv` oluştur, `requirements.txt` kur, import
doğrula, `.venv/.eratone_kurulum` damgası (requirements + Python sürümü hash'i; değişmediyse kurulumu atlar), Eratone'u aç.
`--kur`, `--tarayici` (start.py), `--test` (dev paketleri + pytest), `--exe` (dev + build_eratone.ps1), `--paketle`
(`paylasim\Eratone_kaynak_*.zip` = kaynak, .venv/build/dist/cache/log/.env HARİÇ; `paylasim\Eratone_uygulama_*.zip` =
`dist\Eratone` + BENIOKU.txt; cacert yoksa reddeder). Diğer argümanlar eratone_app.py'ye iletilir (`--no-intro`, `--debug`).
WebView2 kayıt defterinde yoksa yalnızca uyarır.

**Doğrulama:**
- pytest 67 passed; `import app.main, app.audio, eratone_app, webview, scipy.signal, sounddevice` tamam; eratone.html'in
  istediği her dosya mevcut.
- `kurulum.py --kur` (mevcut .venv) → damga yazıldı; ikinci çalıştırma "Kurulum güncel"; `--test` 67 passed.
- **Sıfırdan ekip arkadaşı simülasyonu:** kaynak zip (3.2 MB, 67 dosya) geçici klasöre açıldı, `.venv` yokken
  `python kurulum.py --test` → 103 sn'de kurdu, 67 passed; o kurulumdan sunucu: `/`, `/static/*`, `/api/texture/...` 200.
  Geçici klasör silindi.
- `kurulum.py --exe` sırasında kullanıcının Eratone'u açıktı → güvenli derleme yeni paketi `build\dist_yeni`'de bıraktı,
  eski pakete dokunmadı (çıkış 2). Kapanınca `build_eratone.ps1 -Yerlestir` → **154.6 MB** (önce 165; frontend 14.7 → 4.7 MB).
  Exe açıldı: küre doğru renk, kartlar dolu, kapanıştan önce hata 0.
- `kurulum.py --paketle` (18 sn): kaynak **3.2 MB**, uygulama **69.0 MB** (239 girdi, BENIOKU + exe + cacert var).

**Sonuç:** proje 663 → 494 MB (72 MB'ı yeni `paylasim\` zip'leri); zip'ler hariç **422 MB** = `.venv` 262 + `dist` 155 + kod ~5.

### 2026-11-15 — Seslendirme (Kadın/Erkek) çalışıyor + gerçek enstrüman kayıtları + hassas ekolayzer

**İstek:** Kadın/Erkek seslendirme hiç çalışmıyordu → gerçekçi, anlaşılır, rahat duyulur sesler; enstrümanlar
gerçeğinden bağımsız/alakasızdı → gerçeğe yakın, net notalı, ekolayzerle uyumlu; ekolayzer hassaslaşsın.
Diğer işlevler bozulmasın. **Yedek:** `Desktop\earth-jukebox-backend_YEDEK_2026-11-15_ses-oncesi\` (26 dosya + pip freeze).

**1. Seslendirme**
- Araştırma: Windows'ta yerel Türkçe ses yalnız **Microsoft Tolga (erkek, OneCore)**; Türkçe kadın yerel ses YOK.
  WebView2 `speechSynthesis` yalnız yerel sesleri veriyor (gizli pencerede ölçüldü: 18 ses, Türkçe sadece Tolga,
  çevrim içi 0). → Doğal sesler backend'den: `edge-tts` 7.3.1 (LGPLv3) → **tr-TR-EmelNeural** (kadın),
  **tr-TR-AhmetNeural** (erkek). Microsoft'un Edge "Sesli Oku" servisi; resmî/belgeli API değil, internet ister.
  Yedek: servis/internet yoksa arayüz yerel Tolga'ya düşer (kadın seçiliyse altyazıda "internet yok: yerel erkek sesi").
- `app/speech.py` (YENİ): `narration()` = konuşmaya uygun Türkçe metin (sound.snapshot'ın gerçek değerleri:
  ortalama/en düşük/en yüksek + birim okunuşu "derece", "milimetre bölü saat"; ondalık virgül, "eksi"; geniş aralıkta
  tam sayı; yağışta kapsam; bitki indeksi; akıntı yönü; "X için veri yok, en yakın tarih Y" — aylıkta aynı ay = veri
  var; aralık anlatımı; intro). `synthesize()` = MP3 akışı (ilk parça 10 sn'de gelmezse SpeechError → 503),
  disk önbelleği `CACHE_DIR/speech/<sha1>.mp3` (en çok 300).
- `app/main.py`: `GET /api/narration/{tema}?date=&region=&intro=&range_start=&range_end=&frames=` (JSON),
  `GET /api/speech?voice=tr_female|tr_male&text=` (audio/mpeg, akış; hata 503 JSON), `POST /api/audio/duck {on}`.
  `/api/speech` istek log'una yazılmaz (adreste uzun metin).
- `app/audio.py`: `set_duck(on)` → motor müziği 0,25'e kısar; motor yoksa (müzik hiç çalmadı) KURMAZ.
- `worldsound/engine.py`: `set_duck(level)` + blok içi doğrusal geçiş (~0,15 sn, tıkırtısız), limiter'dan önce.
- `frontend/static/eratone-voice.js` (YENİ): Kadın/Erkek düğmeleri; konuşur: düğmeye basınca (kısa giriş + harita),
  tema/bölge/tarih değişince, aralık uygulanınca bir kez (900 ms bekleyip sonuncusu); açılışta ve aralık karelerinde
  konuşmaz. Yeni anlatım eskisini keser. Konuşurken: müzik kısılır (`/api/audio/duck`), altyazı (`.ej-voice-caption`,
  sahnenin üst ortası), konuşan düğmenin halkası yanıp söner (`.is-speaking`). HTMLAudioElement akışla çalar.
- `eratone.html`: ses düğmesi işleyicisi — seçili düğmeye yeniden basmak KAPATIR, `eratone:voice {voice|null}` yayar;
  `eratone-voice.js` betik satırı. Varsayılan Erkek seçili (tasarım); yalnız kullanıcı bir şey değiştirince konuşur.
- Ölçüm: ilk ses ~1,5 sn (akış), önbellekten 0,01 sn; düzey RMS −17…−19 dBFS (müzik kısılıyken rahat duyulur);
  ~45 kelimelik anlatım ~17 sn. Kısa cümleler 1–1,5 sn duraklatıyordu → başlık tek cümle ("…haritası, Türkiye, 14 Kasım 2026.").

**2. Enstrümanlar: gerçek kayıtlar (örnekleyici)**
- Kaynak: FluidR3_GM soundfont (Frank Wen), MIDI.js dönüşümü gleitz/midi-js-soundfonts, **CC BY 3.0** (atıf README
  + `samples/KAYNAK.txt`). Piyano/naylon gitar/flüt/keman temizlik yedeğindeki mp3.js'lerden, elektro gitar
  (electric_guitar_clean) indirildi.
- `scripts/build_instrument_samples.py` (YENİ) → `world-sound/worldsound/samples/<anahtar>/m<NNN>.ogg` + manifest.json
  (82 kayıt, **1,6 MB**): 3 yarım tonda bir kayıt (çalarken en çok ±1 yarım ton kaydırılır), mono, DC sil, baştaki
  sessizliği kırp, sönenlerde −60 dB kuyruk + 40 ms kapanış, flüt/kemanda yumuşak geçişli döngü (crossfade 150 ms,
  sıfır geçişte), düzey −18 dBFS RMS, **akort ölçümü** (`tune_cents`, FFT temel harmonik). Keman kaynak kayıtları
  −21…+38 sent akortsuzdu → düzeltilir. Kaynakta keman Si♭6 boş → komşu kayıt kullanılır.
- Gerçek ses aralıkları: piyano 33–99, klasik gitar 40–83 (Mi2–Si5), elektro gitar 40–86, yan flüt 60–96 (Do4–Do7),
  keman 55–96 (Sol3–Do7). Aralık dışı harita notası OKTAV kaydırılarak içeri alınır (nota adı/armoni korunur).
- `worldsound/sampler.py` (YENİ): SampleBank (süreç başına tek kopya), SampleInstrument/SampleVoice — Instrument/Voice
  ile AYNI arayüz (motor/sıralayıcı/EQ değişmedi). Doğrusal ara değerleme, akort düzeltmesi, döngü, release.
- `worldsound/instruments.py`: `InstrumentRack.default()` piyano/keman/flüt/gitarları kayıtla kurar; kayıt ya da
  soundfile yoksa aynı anahtarlarla eski sentez enstrümanlarına düşer. Bas ve Synth Pad sentez (arayüzde yok).
- Ölçüm (her nota, FFT temel frekans): en büyük sapma piyano 0,4 · keman 2,2 (vibrato) · flüt 0,9 · akustik 0,5 ·
  elektro 0,7 sent. Enstrüman düzeyleri −19…−22 dBFS (fark < 3 dB).

**3. Ekolayzer**
- `worldsound/equalizer.py`: 0,1 dB çözünürlük; **yumuşak geçiş** (uygulanan kazanç hedefe 60 dB/sn ile kayar,
  12 dB ≈ 0,2 sn; fermuar cızırtısı/tıkırtı yok). Bant frekansları/Q değişmedi (testler ±12 dB'de >10,5 dB).
- `eratone.html`: 5 kaydırıcı `step="0.5"`, değer "+2,5 dB" biçiminde.
- `eratone-audio.js`: eskiden 80 ms'lik BEKLETME (debounce) vardı — sürükleme durana kadar hiçbir şey gitmiyordu;
  şimdi en çok 40 ms'de bir gönderir (throttle) + bırakınca son değer kesin gider → sürüklerken duyulur.

**Paketleme:** requirements `soundfile>=0.12`, `edge-tts>=7.0` (aiohttp geri geldi); world-sound/requirements soundfile.
`Eratone.spec`: datas `world-sound/worldsound/samples` → `worldsound/samples`, `_soundfile_data` (libsndfile_x64.dll);
hiddenimports soundfile, edge_tts. Exe 155 → **160,1 MB**.

**Doğrulama:** pytest **105 passed** (+27 `world-sound/tests/test_sampler.py`: her notada perde ±8 sent, oktav katlama,
düzey dengesi, flüt/keman 6 sn kesintisiz + tıkırtısız döngü, release, doğal sönüm, 5 enstrüman + EQ +12 dB'de
taşma yok, EQ hassasiyet + yumuşak geçiş, ducking; +11 `tests/test_speech.py`: metin biçimi, aylık aynı ay, yağış,
aralık, 503 yedek, akış + önbellek, duck motoru açmaz). Canlı: 6 harita anlatımı; headless Edge (sessiz): Kadın
düğmesi → altyazı + ses + duck aç/kapa, harita değişince önceki kesilip yenisi anlatıldı. Exe (hoparlörden ses
çıkarmadan): anlatım + iki sesin MP3'ü 200, kayıtlı piyano (ses düzeyi 0) Do5/Re5 üretti, EQ 2,5 dB, duck, hata 0.
**Duyarak test EDİLMEDİ** (kullanıcının hoparlöründe çalınmadı).
**⚠ Güncellenmesi gereken dokümanlar:** jüri dokümanı (Claude Docs) ve `araştırma.txt` hâlâ "seslendirme bağlı değil",
"enstrümanlar sentez" diyor — artık yanlış.

### 2026-11-15 — Seslendirme enstrümanları ve tarih aralığını söylüyor + müzik hızı çubuğu (0.25x–2x)

**İstek:** seslendirme çalan enstrümanları ve seçilen tarih aralığını da söylesin; oynat düğmesinin ALTINA müzik
hızı çubuğu (solda "0.25x", sağda "2x", açılışta 1x). Başka hiçbir şeye dokunulmasın.
**Yedek:** `Desktop\earth-jukebox-backend_YEDEK_2026-11-15_hiz-cubugu-oncesi\` (8 dosya).

**Seslendirme**
- `app/speech.py`: `INSTRUMENT_NAMES` (acoustic_guitar→akustik gitar, electric_guitar→elektro gitar, piano→piyano,
  flute→yan flüt, violin→keman), `instruments_phrase()` ("Çalan enstrüman: piyano." / "Çalan enstrümanlar: akustik
  gitar, piyano ve keman." arayüz sırasıyla). `narration(..., instruments=)` → her anlatımın SONUNA eklenir (tek tarih
  ve aralık anlatımında). instruments verilmezse eklenmez (eski çağrılar aynı).
- `GET /api/narration/{tema}`: `instruments=piano,violin` ve `instruments_only=true` (yalnız enstrüman cümlesi).
- Tarih aralığı: aralık uygulanınca "…X ile Y arası, N kare…" zaten okunuyordu; artık enstrümanlar da ekleniyor.
- `eratone-voice.js`: `activeInstruments()` (window.eratoneAudio.instruments), `say()` ortak çalıcı; her anlatıma
  `instruments` parametresi; enstrüman düğmesi ('eratone:audio' type=instrument) → 600 ms bekleyip yalnız güncel
  enstrüman cümlesi ("announceInstruments").

**Müzik hızı**
- `app/audio.py`: `BASE_SCAN_SPEED = 5` (1x = saniyede 5 sütun), `speed` (açılışta 1.0, kaydedilmez), `set_speed()`
  (0.25…2'ye kırpar; motor yoksa saklar, kurulunca `sonifier()` uygular), `state()["speed"]`.
  Tempo değişir, PERDE DEĞİŞMEZ (tarama adımı 0,8 sn @0.25x … 0,1 sn @2x).
- `app/main.py`: `POST /api/audio/speed {factor}` (pydantic 0.25…2, dışı 422).
- `eratone.html`: `.player-center` sütun oldu: üstte `.player-transport` (Oynat + Döngü, solda döngü genişliğinde
  görünmez boşluk → Oynat tam ortada), altta `#speed-control`: "0.25x" · `#speed-slider` (0.25–2, adım 0.25,
  value=1) · "2x"; 1x noktasında küçük işaret, üzerine gelince/sürüklerken değer baloncuğu, 1x dışındayken uç
  yazıları turuncu. Çift tıklama → 1x. Turuncu ses renkleri (mevcut değişkenler).
- `eratone-audio.js`: çubuk her açılışta 1x'e kurulur; ilk "Çal"da arm() ile gider, sonra sürüklerken en çok
  60 ms'de bir `/api/audio/speed`. Aralık oynatıcısının kare hızına (0.5–4 kare/sn) DOKUNULMADI.
- `eratone-data.js` test kancası: `vinst=<enstrüman>` (30 sn'de o enstrümana bas).

**Doğrulama:** pytest **109 passed** (+4: enstrüman cümlesi, anlatım sonu + aralık, instruments_only uç noktası, hız
sınırları/tempo/motoru açmama). Headless (sessiz): Kadın düğmesi → giriş anlatımı `instruments=acoustic_guitar`;
aralık uygulanınca aralık anlatımı (range_start/end/frames + enstrüman); piyanoya basınca
`instruments_only … acoustic_guitar,piano`. Ekran görüntüsü: çubuk Oynat'ın tam altında, 0.25x solda, 2x sağda,
başparmak 1x'te. Exe yeniden derlendi (160,1 MB): anlatım metinleri doğru, hız 1.5x/2x kabul, hata 0.
Test sırasında açık pencerede kullanıcı Oynat'a bastı (log: arayüzün ilk-Çal paketi) → arayüz hızı 1x gönderdi:
beklenen davranış (hızın kaynağı çubuk).

### 2026-11-15 — Açılış ipucu yazısı, açılış/varış/takvim/ekolayzer seslendirmesi, BÖLGE HATASI düzeltildi, hazır sürüm

**İstek:** "Sistemi Başlat" yerine dünyanın altında küçük-soluk "Devam etmek için herhangi bir yere tıklayın"; seslendirme
açılışta da olsun; uygulamaya geçince tıklamadan konuşsun; ekolayzere seslendirme; takvimde tarih seçerken (Görüntüle'den
önce) seslendirme; bölge seçince ses oynatmadaki hatayı düzelt; uygulamayı hazır hâle getir.
**Yedek:** `Desktop\earth-jukebox-backend_YEDEK_2026-11-15_hazirlik-oncesi\` (11 dosya).

**1. Bölge hatası (kök neden ÖLÇÜLDÜ)** — test düzeneği: uygulama süreç içinde, ses kartı yerine motor gerçek zamanlı
render edilip WAV'a yazıldı, AudioBridge komutları zaman damgalı; headless Edge Oynat (5 sn) → Türkiye (15 sn).
Bulgu: 3D'de bölge seçilince kaynak dünya kalıyor, yalnız GÖRÜNÜM değişiyor; tarama kaldığı yerden (%86) sürüyordu.
Döngü kapalı (varsayılan) → tur ~2 sn sonra bitip müzik KESİLİYORDU, yeni bölge hiç baştan çalınmıyordu.
Düzeltme: `POST /api/audio/view {…, restart}` → `bridge.set_view(…, restart)` → `sequencer.restart()`.
`eratone-audio.js`: bölge değişince 1,5 sn boyunca gelen görünümler restart=true (küre ~1,2 sn döner; tarama
SON görünümün başından başlar). Zoom/kaydırma: kaldığı yerden. Doğrulama: aynı düzenekte bölge sonrası tarama %7'den
başlayıp yeni bölgeyi 13 sn tam çaldı (önce 2 sn). Test: `test_region_change_restarts_scan_and_keeps_playing`.
Ayrıca: seslendirme müzik kısma düzeyi 0.25 → **0.4 (−8 dB)** (`DUCK_LEVEL`); bölge anlatımı ~20 sn müziği
"kesilmiş" gibi gösteriyordu.

**2. Tıklamasız seslendirme (kök neden ÖLÇÜLDÜ)** — WebView2 varsayılanında kullanıcı etkileşimi olmadan
`audio.play()` → NotAllowedError (gizli ve görünür pencerede ölçüldü). `eratone_app.py`: pencere açılmadan
`WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS="--disable-features=ElasticOverscroll --autoplay-policy=no-user-gesture-required"`
(ortam değişkeni pywebview'in AdditionalBrowserArguments'ının YERİNE geçer → onun argümanı da eklendi). Ölçüm:
ayarla İZİNLİ. Not: tarayıcı modunda (start.py) tarayıcının kendi kuralı geçerli.

**3. Açılış ekranı** (`eratone.html`): `#startBtn` → `.start-btn.start-hint` "Devam etmek için herhangi bir yere
tıklayın" (13 px, rgba(203,213,225,.72), nefes alma .6–1; çerçeve/arka plan/hale yok). `#intro` üzerinde tıklama
(6 px'ten az hareket = tıklama; sürükleme dünyayı döndürür), Enter/Boşluk başlatır; "Atla" ayrı. Olaylar:
`eratone:intro-launch` (startLaunch), `eratone:app-ready` (leave).

**4. Seslendirme tetikleyicileri** (`eratone-voice.js`): açılışta hoş geldin (1,5 sn sonra; tıklayınca kesilir);
`eratone:app-ready` → tıklamadan harita anlatımı (intro=true); açılış kapalıysa (?intro=0) ilk görünümde. Takvim:
`eratone.html` `pickDate()` (silindirler, oklar, seçici; kareler/sınırlar setDate'i doğrudan çağırır → konuşmaz) →
`eratone:date-picked` → "Seçilen tarih: … Görüntüle'ye basın." (1,1 sn bekleyip son durum). Aralık alanları
(başlangıç/bitiş/kare, hazır sayılar, ±) → "Seçilen tarih aralığı: … arası, N gün, M kare…". Ekolayzer: panel açılınca
5 bant özeti; bant bırakılınca "Bas, artı 2,5 desibel."; enstrüman ses düzeyi "Piyano ses düzeyi yüzde 60.".
?ej=1 test kancasında açılış/varış konuşmaları kapalı. Test kancası: `vregion`, `vdate`, `veq`.

**Doğrulama:** pytest **110 passed**; satır içi 5 betik + tüm JS `node --check` temiz. Headless canlı: hoş geldin →
geçişte harita anlatımı (tıklamasız); tarih okuna basınca "Seçilen tarih: 13 Kasım 2026…"; ekolayzer açılış özeti;
"Bas, artı 3 desibel.". Exe (160,1 MB): log sırası duck(hoş geldin çalıyor, tıklamasız) → duck(kesildi) →
narration intro=true → duck(anlatım çalıyor, tıklamasız); hata 0. **Duyarak değerlendirme kullanıcıda.**

### 2026-11-15 — Ekolayzer ayarları kalıcı (uygulama kapanıp açılınca korunur)

**Şikâyet:** ekolayzerde seçilen ayarlar uygulama kapanıp açılınca varsayılana dönüyordu. Başka hiçbir şeye dokunulmadı.
**Yedek:** `Desktop\earth-jukebox-backend_YEDEK_2026-11-15_eq-kalici-oncesi\` (eratone.html, CONTEXT.md).
- `eratone.html` (ana betik): `localStorage['eratoneEqSettings'] = {bands: {data-target: dB}, mix: {inst: 0..100}}`.
  5 bant ve enstrüman ses düzeyi kaydırıcıları `change`te (bırakınca) kaydeder; açılışta kayıtlı değerler
  ses köprüsünden ÖNCE kaydırıcılara yazılır (etiketler + `window.eratoneAudio.instruments[…].volume` güncellenir) →
  ilk "Çal"da motora kayıtlı ayarlar gider. Sınır dışı/bozuk kayıt yok sayılır; depolama yoksa varsayılanlar.
  Geri yüklemede yalnız `input` olayı yayılır → seslendirme ("change") konuşmaz, köprü henüz bağlı değil.
- Depolama: WebView2 kalıcı profili `%LOCALAPPDATA%\Eratone\webview` (sabit port 38100 = aynı origin); açılışta
  silinen yalnız HTTP `Cache` klasörü, `Local Storage` korunur. Hız çubuğu bilinçli olarak kaydedilmez (her açılış 1x).
- Test kancası `veq`: piyano ses düzeyini 55 yapma eklendi.
**Doğrulama:** gerçek WebView2 (pywebview, kalıcı depolama), iki oturum: 1. oturumda bas +3 dB / piyano 55 →
2. oturumda kaydırıcı, etiket ("+3 dB", "55") ve köprü durumu (0.55) geri geldi; değiştirilmeyen bant varsayılanda;
boş depolamada varsayılanlar. pytest 110 passed; JS sözdizimi temiz; exe yeniden derlendi.
