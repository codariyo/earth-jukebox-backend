"""
Diğer uygulamanıza entegrasyon örneği (arayüzsüz).

Kendi harita bileşeniniz kullanıcı yakınlaştırdığında / kaydırdığında
yalnızca set_view_lonlat() (veya set_viewport()) çağırmanız yeterlidir;
müzik o anki görünür piksellere göre kendiliğinden değişir.

Çalıştırma:  python ornek_entegrasyon.py
"""

import time

from worldsound import MapSonifier, NasaGibsSource, note_name

son = MapSonifier()

# 1) Veriyi oku: NASA'dan en güncel deniz yüzeyi sıcaklığı
#    (ya da: son.load("harita.png")  /  son.load(numpy_dizisi)  /  son.load(PIL_görüntüsü))
son.load(NasaGibsSource("GHRSST_L4_MUR_Sea_Surface_Temperature", width=2048))

# 2) Ses ayarları
son.set_instrument("piano", enabled=True, volume=0.8)
son.set_instrument("violin", enabled=True)
son.set_instrument("bass", enabled=True, octave=-1)
son.set_eq("bass", +3)
son.set_eq("treble", -2)
son.set_scan_speed(6)                       # saniyede 6 sütun

# 3) Her adımda ne çaldığını dinle (ses iş parçacığından çağrılır)
son.add_step_listener(lambda s: print(
    f"sütun {s.column + 1:>2}/{s.cols}: {' '.join(note_name(m) for m in sorted(s.sounding)) or '-'}"))

son.start_audio()
son.play()

# 4) Kullanıcı haritada gezinir: her görünüm farklı piksel = farklı müzik
views = [
    ("Tüm dünya", None),
    ("Akdeniz", (-6, 30, 36, 46)),
    ("Ekvator Pasifik", (-170, -10, -100, 10)),
    ("Kuzey Atlantik / Gulf Stream", (-80, 30, -40, 50)),
]
for name, box in views:
    print(f"\n=== {name} ===")
    if box is None:
        son.reset_view()
    else:
        son.set_view_lonlat(*box)
    time.sleep(6)

son.close()
