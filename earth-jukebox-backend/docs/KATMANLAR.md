# Veri Kaynakları — Ekip için özet

> **2026-11-14 güncellemesi:** API artık her isteğe görsel dönüyor (bkz. `README.md`).
> Aşağıda geçen `/api/sonify`, `/api/compose`, `/api/colormap` ve JSON dönen `/api/compare`
> uç noktaları kaldırıldı; seslendirme kodu (`app/sonify.py`, `app/compare.py`) duruyor ama
> API'ye bağlı değil. Görsel karşılaştırma: `/api/map/{tema}/compare?start=&end=`.
> Tarih aralıkları artık çalışma anında GIBS WMTS GetCapabilities'ten okunuyor.

## API anahtarı gerekmiyor

NASA GIBS herkese açık bir servis. Kayıt, anahtar, ücret veya istek limiti yok.
İhtiyacımız olan tek şey **katman adı** (layer identifier). Örnek:

```
https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi
  ?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap
  &LAYERS=MODIS_Terra_NDVI_8Day      <-- katman adı
  &SRS=EPSG:4326&BBOX=25,35,45,43
  &WIDTH=512&HEIGHT=205&FORMAT=image/png
  &TIME=2026-07-04                   <-- tarih
```

Bu adresi tarayıcıya yapıştırırsan görüntüyü doğrudan görürsün.

## Kullandığımız katmanlar (check_layers.py ile DOĞRULANDI)

| Tema (id) | Katman adı | Tarih aralığı | Enstrüman |
|---|---|---|---|
| `dunya_renkleri` | `MODIS_Terra_CorrectedReflectance_TrueColor` | Günlük, 2000-02-24'ten | pad |
| `sicaklik` | `MODIS_Terra_Land_Surface_Temp_Day` | Günlük, 2000-02-24'ten | lead |
| `okyanus` | `GHRSST_L4_MUR25_Sea_Surface_Temperature` | Günlük, 2002'den | yaylılar |
| `okyanus_akinti` | `OSCAR_Sea_Surface_Currents_Zonal` | **5 günlük, 2014-10-22 → 2024-07-17** (GIBS'te bundan yenisi yok) | pad |
| `bitki` | `MODIS_Terra_NDVI_8Day` | 8 günde bir, **sadece 2025-02-12'den** | çan |
| `yagis` | `IMERG_Precipitation_Rate` | Günlük, 2000-06-01'den | pluck |
| `kuresel_isinma` | `MERRA2_2m_Air_Temperature_Monthly` | **Aylık, 1980-01'den 2026-08'e** | bas |
| `isinma_anomali` | `GHRSST_L4_MUR25_Sea_Surface_Temperature_Anomalies` | Günlük, 2002'den | lead |

### Dikkat edilecek noktalar

- **Bitki örtüsü sadece son ~2 yılı tutuyor.** 2020 tarihi verirsen hata alırsın.
  Mevsim değişimini göstermek için 2025 Şubat ile 2025 Temmuz'u karşılaştır.
- **Küresel ısınma aylık** ve son verisi 2026-08. Daha yeni tarih istersen
  backend otomatik olarak 2026-08-01'e çeker.
- MERRA2'de birkaç ay eksik (2023-12, 2024-01, 2024-05). O aylar boş döner.
- `GHRSST_L4_MUR25_...` yerine `GHRSST_L4_MUR_...` kullanırsan 1 km çözünürlük
  alırsın: çok daha detaylı ama çok daha yavaş. Demo için MUR25 yeterli.

## Okyanus akıntıları

GIBS'te gerçek akıntı verisi **var**, ama ikiye bölünmüş:

- `OSCAR_Sea_Surface_Currents_Zonal` — doğu-batı yönündeki hız
- `OSCAR_Sea_Surface_Currents_Meridional` — kuzey-güney yönündeki hız

Biz Zonal'ı kullanıyoruz. Bu veri iki yönlü: negatif değer batıya, pozitif değer
doğuya akışı gösterir. Yani renk haritasının ortası "durgun su", iki uç da
"hızlı akıntı" demek. Müzikte bu güzel çalışıyor: durgun bölgeler orta notalar,
güçlü akıntılar uç notalar veriyor.

İkisini birleştirip gerçek akıntı hızını (karekök(u²+v²)) hesaplamak da mümkün.
Vakit kalırsa yaparız.

## Örnek bbox değerleri

| Bölge | bbox |
|---|---|
| Şanlıurfa çevresi | `36,36,41,39` |
| Türkiye | `25,35,45,43` |
| Avrupa | `-10,35,40,70` |
| Dünya | `-180,-90,180,90` |
| Amazon | `-75,-15,-45,5` |
| Kuzey Kutbu | `-180,60,180,90` |

Okyanus ve küresel ısınma temaları için geniş bbox kullan; Türkiye kutusunda
okyanus yok, o yüzden parça sessiz kalır.

## normalize parametresi (önemli karar)

`/api/sonify` ve `/api/compose` artık `normalize` parametresi alıyor.

**`normalize=false` (varsayılan, bilimsel olarak dürüst):**
Değerler mutlak ölçekte. Mavi hep aynı notayı, kırmızı hep aynı notayı verir.
**1980 ile 2026'yı karşılaştırmak istiyorsan bu şart.** Isınma ancak böyle duyulur.

**`normalize=true` (müzikal):**
Her görüntünün kendi değer aralığı 0–1'e yayılır. Melodi zenginleşir, tek düze
olmaktan çıkar. Ama iki farklı tarih ayrı ayrı gerildiği için ikisi de aynı
aralığa oturur ve **aradaki fark kaybolur.**

Kural: Tek bir anın güzel sesi için `true`, tarihler arası karşılaştırma için `false`.
`dunya_renkleri` teması varsayılan olarak `true` kullanıyor, çünkü gerçek renkli
görüntü bir ölçüm değil, sadece manzara.

## Solgun piksel koruması

Beyaz, gri ve siyah piksellerin "renk tonu" yoktur. HSV bunlara rastgele bir ton
verir, genelde 0 yani kırmızı. Bu yüzden bulutlar ve veri-yok alanları
"en yüksek değer" sanılıyordu. Artık doygunluğu %18'in altındaki pikseller
geçersiz sayılıp sus olarak çalınıyor.

## /api/compare — iki tarihi karşılaştırma

```
/api/compare/kuresel_isinma?date_a=1985-07-01&date_b=2025-07-01&bbox=-100,0,20,60
```

**Neden gerekli:** 1985 ile 2025 arasındaki fark 0.007 çıkıyor. Bir sonraki
notaya atlamak için 0.111 gerekiyor. Yani mutlak ölçekte iki tarih de aynı
notayı çalıyor, ısınma duyulmuyor.

**Nasıl çözüyor:** İki görüntüyü ayrı ayrı değil, **ortak** bir aralığa göre
ölçekliyor. Ortak aralık ikisinin birleşik min-max'i olduğu için fark büyüyor
ama iki görüntü aynı cetveli kullandığından karşılaştırma bozulmuyor.
Bu, `normalize=true`'dan farklı: o her görüntüyü kendi aralığına gerdiği için
farkı yok ederdi.

Cevapta ne var:
- `verdict` — kaç şeritte artış var, yön tutarlı mı
- `tracks` — iki tarihin melodileri (ortak ölçekte, karşılaştırılabilir)
- `difference_track` — farkın kendisi melodi olarak; orta nota "değişim yok"
- `caution` — sunumda söylenmesi gereken sınırlar

**Sunumda mutlaka söyleyin:** İki tarihe bakmak bir iklim eğilimi kanıtlamaz.
Bu bir seslendirme gösterimidir, bilimsel ölçüm değil. Jüri sınırlarını bilen
ekibi dürüst bulur.

## Renk haritası ile gerçek değer okuma (GIBS Python örneklerindeki yöntem)

GIBS'in resmî Python örnekleri sayfası (örnek 27 ve 28) piksellerden veri
okumanın doğru yolunu gösteriyor: katmanın **renk haritası XML'ini** indirip
her pikselin rengini tablodan bakmak.

```
https://gibs.earthdata.nasa.gov/colormaps/v1.3/<RenkHaritasıAdı>.xml
```

**Dikkat:** Renk haritası adı katman adıyla aynı olmayabilir
(`MODIS_Terra_NDVI_8Day` → `MODIS_NDVI.xml`, `IMERG_Precipitation_Rate` →
`GPM_Precipitation_Rate.xml`, `MODIS_Terra_Land_Surface_Temp_Day` → `MODIS_Land_Surface_Temp.xml`).
Doğru link WMTS GetCapabilities'te `ows:Metadata role=".../colormap/1.3"` alanında; backend artık
oradan okuyor.

İçinde her renk bir değer aralığına bağlı:

```xml
<ColorMap title="Surface Air Temperature" units="K">
  <ColorMapEntry rgb="255,150,50" transparent="false" value="[280.0,290.0)" .../>
```

Backend artık bunu yapıyor. Sonuç:

| Önce | Şimdi |
|---|---|
| "mavi düşük, kırmızı yüksek" tahmini | Gerçek değer: Kelvin, °C, mm/saat... |
| `mean_value: 0.94` (anlamsız sayı) | `mean_real: 24.3`, `units: "°C"` |
| Isınma: "+0.007" | Isınma: "+0.8 °C" gibi gerçek birim |

Nasıl çalışıyor:
1. Renk tabloda birebir varsa o değer alınır.
2. Birebir yoksa ama çok yakınsa (kenar yumuşatması) en yakın renk alınır.
3. Hiç yoksa ya da şeffafsa: veri yok, sus.
4. Renk haritası indirilemezse eski renk tonu tahminine geri düşülür;
   cevapta `value_source: "renk_tonu_tahmini"` yazar, böylece fark edersin.

Kontrol etmek için: `GET /api/legend/kuresel_isinma` (lejant görseli) veya
`python scripts/check_layers.py` (birim, aralık, hassasiyet).

**Hassasiyet uyarısı:** Renk haritasındaki her renk bir aralığı temsil eder
(örneğin 1 K). Bundan küçük farklar için yön güvenilir ama büyüklük kaba tahmindir.
`/api/compare` bu durumda otomatik uyarı ekler.

**Sayfanın kendi uyarısı:** Bu analizler resmî bilimsel çalışma için değildir;
görüntüler orijinal veriden daha düşük hassasiyettedir. Sunumda söyleyin.
