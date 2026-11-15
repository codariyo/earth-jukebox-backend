# World Sound

NASA harita verisini (sıcaklık, okyanus akıntıları, bitki örtüsü, yağış…) **kullanıcının o an
gördüğü piksellere göre** müziğe çeviren kütüphane ve test uygulaması.

> **Eratone kopyası (2026-11-15):** Bu klasör `C:\Users\EXCALIBUR\Desktop\world-sound`'un Eratone projesine
> alınmış kopyasıdır. Kopyada `baslat.bat`, `samples/*.png` ve örnek WhatsApp görselleri kaldırıldı (orijinalde duruyor).
> Eratone'da veri bu kütüphanenin kendi `NasaGibsSource`'u ile DEĞİL, uygulamanın backend'inden gelir:
> `app/audio.py` (Eratone) NASA katmanını kendi önbellekli GIBS istemcisiyle çeker ve `MapData` olarak
> `MapSonifier.load()`'a verir. Bkz. projedeki `CONTEXT.md` → "Faz 5".

## Çalıştırma

```
python test_app.py              ← test uygulaması (bağımsız; NASA'dan kendisi çeker)
python tests/test_worldsound.py ← otomatik testler (ses kartı gerekmez)
python ornek_entegrasyon.py     ← arayüzsüz entegrasyon örneği
```

Gereksinimler: Python 3.10+, `numpy scipy sounddevice pillow` (`pip install -r requirements.txt`).

---

## Çalışma mantığı

```
 Veri kaynağı ──► MapData ──► Viewport ──► ViewportScanner ──► NoteFilter ──► ScanSequencer ──► AudioEngine
 (NASA / PNG)    (RGBA +      (görünen    (her piksel bir     (tekrar eden    (tarama çizgisi:   (her nota açık
                  coğrafya)    bölge)      nota verir, hücre   notayı eler)    nota aç / kapat)   TÜM enstrümanlarda
                                           oy çokluğuyla                                          → EQ → yankı → çıkış)
                                           nota alır)
```

### 1. Veri okunur
- **NASA GIBS** (`NasaGibsSource`), **dosya** (`ImageFileSource`) ya da **bellekteki görüntü** (`ArraySource`).
- NASA PNG'lerindeki **şeffaf pikseller (alpha = 0) "ölçüm yok"** demektir ve asla nota üretmez.
- Tarih boş bırakılırsa NASA her katmanın **en son mevcut verisini** verir. (Katmanların son
  tarihleri farklıdır; örneğin OSCAR akıntıları 2024-07'de bitiyor. Sabit bir tarih çoğu
  katmanda boş görüntü döndürürdü.)

Hazır NASA katmanları (adları GIBS GetCapabilities belgesinden doğrulandı, hepsi test edildi):

| Konu | Katman |
|---|---|
| Dünya renkleri | `MODIS_Terra_CorrectedReflectance_TrueColor` |
| Kara sıcaklığı | `MODIS_Terra_L3_Land_Surface_Temp_8Day_Day` |
| Deniz sıcaklığı | `GHRSST_L4_MUR_Sea_Surface_Temperature` |
| Sıcaklık değişimi (anomali) | `GHRSST_L4_MUR_Sea_Surface_Temperature_Anomalies` |
| Okyanus akıntıları | `OSCAR_Sea_Surface_Currents_Zonal` / `_Meridional` |
| Bitki örtüsü | `MODIS_Terra_L3_NDVI_16Day` |
| Yağış | `IMERG_Precipitation_Rate` |
| Küresel sıcaklık | `MERRA2_2m_Air_Temperature_Monthly` |

### 2. Renk → nota
**Kırmızı = en tiz, mavi = en pes.** Ara renkler aradaki konumlarına göre orantılı yerleşir ve
dizideki **en yakın notaya** oturtulur (Do ile Si arasında Fa'ya yakınsa Fa).

| Renk | Mavi | Camgöbeği | Yeşil | Sarı | Turuncu | Kırmızı |
|---|---|---|---|---|---|---|
| Nota (Do majör) | **Do2** | Re3 | Fa4 | La5 | Mi6 | **Si6** |

Mor/macenta tonları maviden kırmızıya renk çemberinin öbür yolundan geri sarar, böylece hiçbir
yerde ani sıçrama olmaz. Aralık (Do2–Si6) ve dizi (majör, minör, pentatonik, kromatik) ayarlanabilir.

### 3. Sessizlik — uygulama kendi kendine çalmaz
Sabit ritim, metronom, arka plan melodisi **yoktur**. Şu pikseller nota üretmez:

| Piksel | Neden |
|---|---|
| Şeffaf (alpha = 0) | NASA: ölçüm yok |
| Siyah / çok karanlık | parlaklık < %12 (ayarlanabilir) |
| Beyaz / gri | rengi yok, kırmızı-mavi ekseninde yeri yok (doygunluk < %20) |

Harita yüklü değilse, çalma durdurulmuşsa veya görünen bölge tamamen siyahsa çıkış **tam 0.0**'dır
(testlerle doğrulandı).

### 4. Görünen bölge (yakınlaştırma)
Müzik **görüntünün tamamından değil, kullanıcının o an gördüğü bölgeden** üretilir. Görünen bölge
36 satır × 64 sütunluk bir ızgaraya bölünür (ayarlanabilir). Her hücrenin notası, hücreye düşen
**her pikselin ayrı ayrı** notaya çevrilip en çok tekrarlanan notanın seçilmesiyle bulunur.

- **Neden renk ortalaması değil?** Yarısı kırmızı yarısı mavi bir hücrenin ortalaması mor olur ve
  haritada olmayan bir nota üretir. Piksel oylamasında hücre, haritada gerçekten bulunan rengin notasını alır.
- Yakınlaştıkça hücre başına düşen piksel azalır; yeterince yakınlaşınca **bir hücre = bir piksel**.
- Görünüm değiştiğinde yeni bölge arka planda taranır ve tarama çizgisi **bir sonraki adımı
  beklemeden** yeni piksellere geçer.
- NASA haritalarında **"Görünen Bölgeyi Detaylı Çek"** görünen boylam/enlem kutusunu NASA'dan
  yüksek çözünürlükte yeniden indirir.

### 5. Tekrar filtresi
- **Dikey:** taranan sütunda aynı notayı veren hücreler notayı **bir kez** çalar. Kapladığı alan
  büyüdükçe nota daha gür olur.
- **Yatay:** önceki sütunda çalan nota bu sütunda da varsa **yeniden çalınmaz**, uzar. Nota yalnız
  renk değişince başlar, renk bitince susar.
- Bir anda en çok 6 farklı nota çalar (ayarlanabilir); fazlası olursa en geniş alanı kaplayanlar seçilir.

### 6. Enstrümanlar
Piyano, Keman, Yan Flüt, Akustik Gitar, Elektro Gitar, Bas, Synth Pad. **Her nota, açık olan
tüm enstrümanlarda aynı anda çalar.** Her enstrümanın ses düzeyi ve oktav kaydırması ayrı
ayarlanır (bas varsayılan olarak 1 oktav aşağıda). Çalarken açılan bir enstrüman o an çalan
notalara hemen katılır.

### 7. Ekolayzer
| Bant | Tür | Frekans |
|---|---|---|
| Bas | alçak raf | 100 Hz |
| Düşük Mid | tepe | 300 Hz |
| Orta | tepe | 1 kHz |
| Yüksek Mid | tepe | 3 kHz |
| Tiz | yüksek raf | 8 kHz |

Her bant −12 / +12 dB. Ölçülen etki (test): her bantta +12 → +11.1…+12.0 dB, −12 → −11.1…−12.0 dB,
0 dB'de tam etkisiz; tiz ayarı 100 Hz'i etkilemiyor. Test uygulamasında frekans eğrisi ve canlı
spektrum gösterilir.

### 8. Iraksak haritalar (akıntı, anomali)
Okyanus akıntısı ve sıcaklık anomalisi haritaları **mavi–beyaz–kırmızı** skala kullanır: renk
tonu yönü (doğu/batı, sıcak/soğuk), **solukluk ise şiddeti** gösterir. Yalnız renk tonuna bakılırsa
akıntı haritası sadece 2 nota verir (her mavi en pes, her kırmızı en tiz). Bu kip açıkken soluk renk
orta notalara, koyu renk uçlara gider (akıntı haritası: 2 → 20 farklı nota). NASA'nın bu katmanlarında
kendiliğinden açılır; diğer haritalarda kapalıdır ve kural yalnız renk tonudur.

---

## Entegrasyon (diğer uygulamanız için)

Tek sınıf yeterli: `worldsound.MapSonifier`.

```python
from worldsound import MapSonifier, NasaGibsSource

son = MapSonifier()
son.load(NasaGibsSource("GHRSST_L4_MUR_Sea_Surface_Temperature"))   # veya "harita.png", numpy, PIL
son.start_audio()
son.play()

# Kullanıcı kendi haritanızda yakınlaştırdı / kaydırdı:
son.set_view_lonlat(west=-6, south=30, east=36, north=46)   # coğrafi kutu
son.set_viewport(0.4, 0.3, 0.6, 0.5)                         # ya da normalize kutu (0..1)
son.zoom(2.0, cx, cy); son.pan(dx, dy); son.reset_view()
```

| Amaç | Çağrı |
|---|---|
| Veri yükle | `load(kaynak)`, `fetch_visible_region_from_nasa()` |
| Görünüm | `set_view_lonlat()`, `set_viewport()`, `zoom()`, `pan()`, `reset_view()` |
| Çal / durdur | `start_audio()`, `play()`, `pause()`, `close()` |
| Enstrüman | `set_instrument("bass", enabled=True, volume=0.8, octave=-1)` |
| Ekolayzer | `set_eq("bass" \| "low_mid" \| "mid" \| "high_mid" \| "treble", dB)` |
| Nota kuralları | `set_scale()`, `set_pitch_range()`, `set_silence()`, `set_diverging()`, `set_grid_size()`, `set_max_voices()` |
| Tarama | `set_scan_speed(sütun/sn)`, `scan_position` |
| Olaylar | `add_step_listener(fn)` → her adımda çalan notalar; `add_grid_listener(fn)` |
| Kendi ses sisteminiz | `render(frames)` → (frames, 2) float32 blok (ses kartı açmadan) |

Notlar:
- `add_step_listener` ses iş parçacığından, `add_grid_listener` tarama iş parçacığından çağrılır.
  Arayüz güncellerken kendi ana iş parçacığınıza aktarın.
- Coğrafi dönüşüm haritanın **equirectangular (EPSG:4326)** olduğunu varsayar (NASA GIBS çıktısı böyle).
  Başka bir projeksiyonda `set_viewport()` ile normalize koordinat verin.
- Yeni veri kaynağı: `MapSource`'tan türetip `load()` yazın. Yeni enstrüman: `Instrument`'tan türetip
  `InstrumentRack.default()`'a ekleyin.

## Dosyalar

```
worldsound/
  map_data.py      MapData, GeoBounds              okunmuş harita
  sources.py       MapSource ve alt sınıfları, GIBS_LAYERS
  viewport.py      Viewport                        görünen bölge
  color_pitch.py   ColorPitchMapper, Scale         renk → nota
  scanner.py       ViewportScanner, ScanGrid       görünen pikselleri tarama
  note_filter.py   NoteFilter                      tekrar filtresi
  sequencer.py     ScanSequencer                   tarama çizgisi, nota aç/kapat
  instruments.py   Instrument + 7 enstrüman, Voice
  equalizer.py     FiveBandEqualizer
  effects.py       Reverb, SoftLimiter
  engine.py        AudioEngine, SoundDeviceOutput
  sonifier.py      MapSonifier                     tek giriş noktası
test_app.py        test arayüzü (görsel seçimi ya da NASA'dan çekme; örnek görseller bu kopyada yok)
ornek_entegrasyon.py
tests/test_worldsound.py
```
