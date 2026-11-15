"""
MapSonifier — dış uygulamalar için TEK giriş noktası.

Diğer uygulamanız yalnızca bu sınıfla konuşur:

    from worldsound import MapSonifier, NasaGibsSource

    son = MapSonifier()
    son.load(NasaGibsSource("GHRSST_L4_MUR_Sea_Surface_Temperature"))   # ya da "harita.png"
    son.start_audio()
    son.play()

    # Kullanıcı kendi harita bileşeninde yakınlaştırdı / kaydırdı:
    son.set_view_lonlat(west=20, south=30, east=50, north=50)   # coğrafi kutu
    # veya
    son.set_viewport(0.55, 0.20, 0.70, 0.35)                     # normalize kutu

    son.set_instrument("bass", enabled=True, volume=0.8)
    son.set_eq("treble", +4.0)

Görünüm her değiştiğinde yalnız GÖRÜNEN pikseller yeniden taranır (arka plan
iş parçacığında, arayüzü kilitlemeden) ve müzik hemen yeni bölgeye geçer.
"""

import threading
from typing import Callable, Optional, Union

import numpy as np
from PIL import Image

from .color_pitch import ColorPitchMapper, Scale
from .engine import AudioEngine, SoundDeviceOutput
from .instruments import InstrumentRack
from .map_data import GeoBounds, MapData
from .note_filter import NoteFilter
from .scanner import ScanGrid, ViewportScanner
from .sequencer import ScanSequencer, StepInfo
from .sources import ArraySource, ImageFileSource, MapSource, NasaGibsSource
from .viewport import Viewport


class MapSonifier:
    def __init__(self, sample_rate: int = 44100, block_size: int = 1024,
                 rows: int = 36, cols: int = 64):
        self.mapper = ColorPitchMapper()
        self.scanner = ViewportScanner(self.mapper, rows, cols)
        self.note_filter = NoteFilter(max_voices=6)
        self.sequencer = ScanSequencer(self.note_filter, sample_rate, step_seconds=0.20)
        self.engine = AudioEngine(self.sequencer, InstrumentRack.default(), sample_rate, block_size)
        self.output = SoundDeviceOutput(self.engine)

        self.map: Optional[MapData] = None
        self.viewport = Viewport()
        self.grid: Optional[ScanGrid] = None
        self._grid_listeners = []

        # arka plan tarayıcı (en son istek kazanır)
        self._version = 0
        self._state_lock = threading.Lock()
        self._wake = threading.Event()
        self._closing = False
        self._worker = threading.Thread(target=self._scan_worker, daemon=True)
        self._worker.start()

    # ================================================================== VERİ
    def load(self, source: Union[str, MapSource, MapData, Image.Image, np.ndarray],
             bounds: GeoBounds = GeoBounds()) -> MapData:
        """Haritayı okur. Dosya yolu, MapSource, MapData, PIL veya numpy kabul eder."""
        if isinstance(source, MapData):
            data = source
        elif isinstance(source, MapSource):
            data = source.load()
        elif isinstance(source, str):
            data = ImageFileSource(source, bounds).load()
        else:
            data = ArraySource(source, bounds).load()
        with self._state_lock:
            self.map = data
            self.viewport.reset()
        # NASA'nın ıraksak katmanlarında (akıntı, anomali) ıraksak kip kendiliğinden açılır
        self.mapper.diverging = bool(data.meta.get("diverging", False))
        self.sequencer.restart()
        self.rescan(sync=True)
        return data

    def fetch_visible_region_from_nasa(self, width: int = 2048) -> MapData:
        """
        NASA'dan yüklenmiş bir haritada: görünen bölgeyi NASA'dan YÜKSEK
        çözünürlükte yeniden çeker (yakınlaştırınca gerçek detay gelir).
        """
        if self.map is None or self.map.meta.get("source") != "gibs":
            raise RuntimeError("Bu işlem yalnız NASA GIBS'ten yüklenen haritalarda yapılabilir.")
        region = self.viewport.to_lonlat(self.map.bounds)
        src = NasaGibsSource(self.map.meta["layer"], self.map.meta.get("date"), region, width=width)
        return self.load(src)

    # ================================================================== GÖRÜNÜM
    def set_viewport(self, x0: float, y0: float, x1: float, y1: float):
        with self._state_lock:
            self.viewport.set(x0, y0, x1, y1)
        self.rescan()

    def set_view_lonlat(self, west: float, south: float, east: float, north: float):
        b = self.map.bounds if self.map else GeoBounds()
        v = Viewport.from_lonlat(b, west, south, east, north)
        self.set_viewport(*v.as_tuple())

    def zoom(self, factor: float, cx: float = None, cy: float = None):
        with self._state_lock:
            self.viewport.zoom(factor, cx, cy)
        self.rescan()

    def pan(self, dx: float, dy: float):
        with self._state_lock:
            self.viewport.pan(dx, dy)
        self.rescan()

    def reset_view(self):
        with self._state_lock:
            self.viewport.reset()
        self.rescan()

    # ================================================================== TARAMA
    def rescan(self, sync: bool = False):
        """Görünen bölgeyi yeniden tarar. sync=False: arka planda (arayüz donmaz)."""
        with self._state_lock:
            self._version += 1
        if sync:
            self._do_scan()
        else:
            self._wake.set()

    def _do_scan(self):
        with self._state_lock:
            data, view, ver = self.map, self.viewport.copy(), self._version
        grid = self.scanner.scan(data, view) if data is not None else None
        with self._state_lock:
            if ver != self._version:          # bu arada yeni istek geldi: eskisini atla
                return
            self.grid = grid
        self.sequencer.set_grid(grid)
        for fn in list(self._grid_listeners):
            try:
                fn(grid)
            except Exception:
                pass

    def _scan_worker(self):
        while not self._closing:
            self._wake.wait()
            self._wake.clear()
            if self._closing:
                break
            try:
                self._do_scan()
            except Exception as ex:
                print("Tarama hatası:", repr(ex))

    # ================================================================== MÜZİK AYARLARI
    def set_scale(self, preset_name: str, root: int = 0):
        self.mapper.set_scale(Scale.preset(preset_name, root))
        self.rescan()

    def set_pitch_range(self, low_midi: int, high_midi: int):
        """Mavi (low) ve kırmızı (high) uçlarının MIDI karşılığı."""
        self.mapper.set_range(low_midi, high_midi)
        self.rescan()

    def set_silence(self, min_value: float = None, min_saturation: float = None):
        """Siyah ve renksiz (beyaz/gri) eşikleri."""
        if min_value is not None:
            self.mapper.rules.min_value = float(min_value)
        if min_saturation is not None:
            self.mapper.rules.min_saturation = float(min_saturation)
        self.rescan()

    def set_diverging(self, enabled: bool):
        """Iraksak (mavi-beyaz-kırmızı) harita kipi: soluk renk = orta nota."""
        self.mapper.diverging = bool(enabled)
        self.rescan()

    def set_grid_size(self, rows: int, cols: int):
        self.scanner.set_grid(rows, cols)
        self.rescan()

    def set_max_voices(self, n: int):
        self.note_filter.max_voices = max(1, int(n))

    def set_scan_speed(self, columns_per_second: float):
        self.sequencer.set_step_seconds(1.0 / max(0.1, float(columns_per_second)))

    # ================================================================== SES
    def start_audio(self):
        self.output.start()

    def stop_audio(self):
        self.output.stop()

    def play(self):
        self.sequencer.play()

    def pause(self):
        self.sequencer.pause()

    @property
    def is_playing(self) -> bool:
        return self.sequencer.playing

    def set_instrument(self, key: str, enabled: bool = None, volume: float = None, octave: int = None):
        if enabled is not None:
            self.engine.set_instrument_enabled(key, enabled)
        if volume is not None:
            self.engine.set_instrument_volume(key, volume)
        if octave is not None:
            self.engine.set_instrument_octave(key, octave)

    @property
    def instruments(self):
        return self.engine.rack

    @property
    def equalizer(self):
        return self.engine.equalizer

    def set_eq(self, band: str, gain_db: float):
        self.engine.equalizer.set_gain(band, gain_db)

    def set_master(self, volume: float):
        self.engine.master = float(np.clip(volume, 0.0, 1.5))

    def set_reverb(self, mix: float):
        self.engine.reverb.mix = float(np.clip(mix, 0.0, 0.6))

    def render(self, frames: int = None) -> np.ndarray:
        """Ses kartı olmadan bir blok üretir (dış ses sistemi / test)."""
        return self.engine.render(frames)

    def render_offline(self, seconds: float) -> np.ndarray:
        blocks = int(np.ceil(seconds * self.engine.sr / self.engine.block))
        return np.concatenate([self.engine.render(self.engine.block) for _ in range(blocks)], axis=0)

    # ================================================================== DURUM / OLAYLAR
    @property
    def scan_position(self) -> float:
        """Tarama çizgisinin görünür bölgedeki yeri (0..1)."""
        return self.sequencer.position

    @property
    def last_step(self) -> Optional[StepInfo]:
        return self.sequencer.last_step

    def add_step_listener(self, fn: Callable[[StepInfo], None]):
        """Her tarama adımında çağrılır (ses iş parçacığından!)."""
        self.sequencer.add_listener(fn)

    def add_grid_listener(self, fn: Callable[[Optional[ScanGrid]], None]):
        """Görünüm yeniden tarandığında çağrılır (tarama iş parçacığından!)."""
        self._grid_listeners.append(fn)

    def close(self):
        self._closing = True
        self._wake.set()
        self.pause()
        self.stop_audio()
