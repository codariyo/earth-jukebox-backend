"""
Tekrar filtresi: yan yana aynı notayı veren pikseller notayı İKİ KEZ çaldırmaz.

İki yönde çalışır:

  DİKEY (aynı tarama sütunu içinde)
      Sütunda alt alta duran hücreler aynı notayı veriyorsa nota bir kez
      çalınır. Aynı notayı veren hücre sayısı (kapladığı alan) arttıkça nota
      daha gür olur; tek hücrelik ince bir şerit daha kısık kalır.

  YATAY (ardışık tarama sütunları arasında)
      Önceki sütunda çalan nota bu sütunda da varsa YENİDEN TETİKLENMEZ,
      çalmaya devam eder (uzar). Nota yalnızca renk değiştiğinde başlar,
      renk bittiğinde susar.
"""

from dataclasses import dataclass, field
from typing import Dict, List

from .scanner import ScanGrid


@dataclass
class FilteredNote:
    midi: int
    velocity: float          # 0..1
    rows: List[int]          # bu notayı veren hücrelerin satırları (görselleştirme)


@dataclass
class FilterStats:
    cells: int = 0           # sütundaki sesli hücre sayısı
    unique: int = 0          # dikey filtreden sonra kalan farklı nota
    played: int = 0          # sınırdan sonra çalınan nota
    vertical_merged: int = 0 # dikey filtrede elenen tekrar
    held: int = 0            # yatay filtrede yeniden çalınmayıp uzatılan nota
    started: int = 0         # bu sütunda yeni başlayan nota
    stopped: int = 0         # bu sütunda susan nota


@dataclass
class ColumnDiff:
    start: Dict[int, FilteredNote] = field(default_factory=dict)   # yeni başlayacaklar
    stop: List[int] = field(default_factory=list)                  # susacaklar
    hold: Dict[int, FilteredNote] = field(default_factory=dict)    # çalmaya devam edenler
    stats: FilterStats = field(default_factory=FilterStats)


class NoteFilter:
    def __init__(self, max_voices: int = 6, min_velocity: float = 0.20):
        self.max_voices = int(max_voices)       # bir anda en çok kaç farklı nota
        self.min_velocity = float(min_velocity)

    # ------------------------------------------------------------------ dikey
    def column_notes(self, grid: ScanGrid, j: int):
        """Bir sütunun notalarını tekilleştirir. Döner: ({midi: FilteredNote}, stats)."""
        cells = grid.column(j)
        stats = FilterStats(cells=len(cells))
        groups: Dict[int, list] = {}
        for row, midi, strength in cells:
            groups.setdefault(midi, []).append((row, strength))

        notes = {}
        for midi, items in groups.items():
            count = len(items)
            peak = max(s for _, s in items)
            area = min(1.0, 0.55 + 0.09 * count)     # 1 hücre %64, 5+ hücre tam gür
            vel = self.min_velocity + (1.0 - self.min_velocity) * peak * area
            notes[midi] = FilteredNote(midi, float(min(1.0, vel)), [r for r, _ in items])

        stats.unique = len(notes)
        stats.vertical_merged = stats.cells - stats.unique
        if len(notes) > self.max_voices:
            keep = sorted(notes.values(), key=lambda n: (len(n.rows), n.velocity), reverse=True)
            notes = {n.midi: n for n in keep[: self.max_voices]}
        stats.played = len(notes)
        return notes, stats

    # ------------------------------------------------------------------ yatay
    def diff(self, sounding: Dict[int, FilteredNote], grid: ScanGrid, j: int) -> ColumnDiff:
        """Şu an çalan notalarla yeni sütunu karşılaştırır."""
        current, stats = self.column_notes(grid, j)
        d = ColumnDiff(stats=stats)
        for midi, note in current.items():
            if midi in sounding:
                d.hold[midi] = note          # aynı nota: tekrar çalma, uzat
            else:
                d.start[midi] = note         # yeni renk: yeni nota
        d.stop = [m for m in sounding if m not in current]
        stats.held, stats.started, stats.stopped = len(d.hold), len(d.start), len(d.stop)
        return d
