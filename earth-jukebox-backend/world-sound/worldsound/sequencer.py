"""
Tarama sıralayıcısı (sequencer).

Tarama çizgisi görünen bölgenin soldan sağına, sütun sütun ilerler. Her yeni
sütunda NoteFilter ile "hangi notalar başlasın / sussun / devam etsin"
kararı verilir ve ses motoruna NoteEvent'ler iletilir.

KENDİ BAŞINA NOTA ÜRETMEZ
    Sabit bir vuruş, metronom, ritim kalıbı veya arka plan melodisi yoktur.
    Taranacak harita yoksa, sütun sessizse (siyah / ölçüm yok) hiçbir olay
    üretilmez. Duraklatılınca tüm notalar susturulur.

GÖRÜNÜM DEĞİŞİNCE
    set_grid() ile yeni tarama gelince (kullanıcı yakınlaştırdı/kaydırdı),
    bir sonraki adımı beklemeden mevcut sütun YENİ piksellere göre hemen
    yeniden değerlendirilir; eski bölgenin notaları susar, yenileri başlar.
"""

import threading
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .note_filter import FilteredNote, FilterStats, NoteFilter
from .scanner import ScanGrid


@dataclass
class NoteEvent:
    kind: str            # "on" | "off"
    midi: int
    velocity: float = 0.0
    offset: int = 0      # blok içindeki örnek konumu


@dataclass
class StepInfo:
    """Bir tarama adımının özeti (arayüz / dış uygulama için)."""
    column: int
    cols: int
    sounding: Dict[int, FilteredNote] = field(default_factory=dict)
    started: List[int] = field(default_factory=list)
    stopped: List[int] = field(default_factory=list)
    stats: FilterStats = field(default_factory=FilterStats)


class ScanSequencer:
    MIN_STEP_SEC = 0.05

    def __init__(self, note_filter: NoteFilter, sample_rate: int = 44100,
                 step_seconds: float = 0.20, loop: bool = True):
        self.filter = note_filter
        self.sr = int(sample_rate)
        self.step_seconds = max(self.MIN_STEP_SEC, float(step_seconds))
        self.loop = loop

        self.grid: Optional[ScanGrid] = None
        self._pending_grid: Optional[ScanGrid] = None
        self._grid_dirty = False
        self._lock = threading.Lock()

        self.column = -1                 # henüz başlamadı
        self._samples_to_step = 0
        self.sounding: Dict[int, FilteredNote] = {}
        self.playing = False
        self.last_step: Optional[StepInfo] = None
        self._listeners: List[Callable[[StepInfo], None]] = []
        self._stop_requested = False
        self._force_eval = False
        self._restart_requested = False

    # ------------------------------------------------------------------ kontrol
    def set_grid(self, grid: Optional[ScanGrid]):
        """Thread-safe: başka bir iş parçacığından yeni tarama verilebilir."""
        with self._lock:
            self._pending_grid = grid
            self._grid_dirty = True

    def set_step_seconds(self, seconds: float):
        self.step_seconds = max(self.MIN_STEP_SEC, float(seconds))

    def play(self):
        self.playing = True
        self._force_eval = True          # kaldığı sütunu hemen yeniden çal

    def pause(self):
        """Durdurur; çalan tüm notalar bir sonraki blokta susturulur."""
        self.playing = False
        self._stop_requested = True

    def restart(self):
        """Taramayı görünür bölgenin başına alır (ses iş parçacığında uygulanır)."""
        with self._lock:
            self._restart_requested = True

    def add_listener(self, fn: Callable[[StepInfo], None]):
        self._listeners.append(fn)

    @property
    def position(self) -> float:
        """Tarama çizgisinin görünür bölgedeki konumu (0..1), çizim için."""
        g = self.grid
        if g is None or self.column < 0:
            return 0.0
        step = max(1, int(self.step_seconds * self.sr))
        frac = 1.0 - self._samples_to_step / step
        return min(1.0, (self.column + max(0.0, min(1.0, frac))) / g.cols)

    # ------------------------------------------------------------------ ses iş parçacığı
    def advance(self, frames: int) -> List[NoteEvent]:
        """Ses bloğu kadar ilerler, bu blokta olan nota olaylarını döndürür."""
        events: List[NoteEvent] = []

        with self._lock:
            if self._grid_dirty:
                self.grid = self._pending_grid
                self._grid_dirty = False
                grid_changed = True
            else:
                grid_changed = False
            restart = self._restart_requested
            self._restart_requested = False

        if restart:
            events += self._release_all(0)
            self.column = -1
            self._samples_to_step = 0

        if not self.playing or self.grid is None:
            if self._stop_requested or self.grid is None:
                events += self._release_all(0)
                self._stop_requested = False
            return events
        self._stop_requested = False

        g = self.grid
        if self.column >= g.cols:
            self.column = g.cols - 1

        # Görünüm değişti: bulunduğumuz sütunu yeni piksellerle hemen yeniden değerlendir
        if (grid_changed or self._force_eval) and self.column >= 0:
            events += self._evaluate(self.column, 0)
        self._force_eval = False

        step = max(1, int(self.step_seconds * self.sr))
        pos = 0
        while pos < frames:
            if self._samples_to_step <= 0:
                nxt = self.column + 1
                if nxt >= g.cols:
                    if not self.loop:
                        events += self._release_all(pos)
                        self.playing = False
                        self.column = -1
                        return events
                    nxt = 0
                self.column = nxt
                events += self._evaluate(nxt, pos)
                self._samples_to_step = step
            take = min(frames - pos, self._samples_to_step)
            pos += take
            self._samples_to_step -= take
        return events

    def _evaluate(self, j: int, offset: int) -> List[NoteEvent]:
        d = self.filter.diff(self.sounding, self.grid, j)
        ev = [NoteEvent("off", m, 0.0, offset) for m in d.stop]
        ev += [NoteEvent("on", m, n.velocity, offset) for m, n in d.start.items()]
        for m in d.stop:
            self.sounding.pop(m, None)
        self.sounding.update(d.start)
        self.sounding.update(d.hold)     # satır bilgisi güncellensin (görselleştirme)

        info = StepInfo(j, self.grid.cols, dict(self.sounding), list(d.start), list(d.stop), d.stats)
        self.last_step = info
        for fn in self._listeners:
            try:
                fn(info)
            except Exception:
                pass
        return ev

    def _release_all(self, offset: int) -> List[NoteEvent]:
        ev = [NoteEvent("off", m, 0.0, offset) for m in self.sounding]
        self.sounding.clear()
        return ev
