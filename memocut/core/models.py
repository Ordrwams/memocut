"""Структури даних, спільні для всіх шарів.

Контракт між шарами:
  Brief (ТЗ)  ->  Catalog (аналіз)  ->  Plan (планувальник)  ->  MP4 (рендер)

Plan — головний формат. Його читає рендер і змінює редактор.
Будь-який планувальник (правила зараз, ШІ потім) мусить повертати Plan.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional
import json
from pathlib import Path

PLAN_VERSION = 3  # 2: + Plan.overlay; 3: + озвучка


# ---------- Каталог (результат аналізу) ----------

@dataclass
class Word:
    w: str
    s: float  # початок, сек
    e: float  # кінець, сек


@dataclass
class ClipInfo:
    file: str                 # шлях відносно source_dir
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool
    mtime: float
    size: int
    scenes: list[float] = field(default_factory=list)          # таймкоди склейок
    silences: list[list[float]] = field(default_factory=list)  # [[s, e], ...]
    brightness: list[float] = field(default_factory=list)      # середня яскравість 0..255, 1 значення/сек
    words: list[Word] = field(default_factory=list)            # транскрипт по словах
    thumb: Optional[str] = None                                # прев'ю-кадр (шлях у кеші)
    desc: str = ""                                             # опис з КАТАЛОГ.csv гри (що в кадрі)

    @staticmethod
    def from_dict(d: dict) -> "ClipInfo":
        d = dict(d)
        d["words"] = [Word(**w) for w in d.get("words", [])]
        return ClipInfo(**d)


@dataclass
class Catalog:
    source_dir: str
    clips: list[ClipInfo] = field(default_factory=list)

    def get(self, file: str) -> Optional[ClipInfo]:
        for c in self.clips:
            if c.file == file:
                return c
        return None

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=1), encoding="utf-8")

    @staticmethod
    def load(path: Path) -> "Catalog":
        d = json.loads(path.read_text(encoding="utf-8"))
        return Catalog(source_dir=d["source_dir"], clips=[ClipInfo.from_dict(c) for c in d["clips"]])


# ---------- План монтажу ----------

@dataclass
class Shot:
    """Конкретний шматок відео: файл + вхід/вихід."""
    file: str
    start: float
    end: float
    score: float = 0.0
    reason: str = ""   # чому вибрано (для показу в редакторі)

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class Segment:
    id: str
    shot: Shot
    title: Optional[str] = None
    subtitles: bool = True
    alternatives: list[Shot] = field(default_factory=list)  # кандидати на заміну для редактора
    slot: int = 0  # номер пункту в ТЗ, з якого виник сегмент


@dataclass
class Plan:
    name: str
    source_dir: str
    format: str            # "9x16" | "1x1" | "16x9"
    style: str
    segments: list[Segment]
    variation: int = 1
    cta: Optional[str] = None
    music: Optional[str] = None
    music_volume: float = 0.15
    overlay: Optional[str] = None  # текст поверх усього відео (v2)
    voiceover: Optional[str] = None          # mp3 озвучки (v3)
    voiceover_words: list[Word] = field(default_factory=list)  # таймкоди слів озвучки (від її початку)
    voice_volume: float = 1.0
    voice_subtitles: bool = True
    original_volume: float = 1.0             # гучність звуку з відео
    planner: str = "rules"
    version: int = PLAN_VERSION
    revision: int = 1      # номер правки; редактор збільшує

    @property
    def duration(self) -> float:
        return sum(s.shot.duration for s in self.segments)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Plan":
        d = dict(d)
        segs = []
        for s in d.pop("segments"):
            s = dict(s)
            s["shot"] = Shot(**s["shot"])
            s["alternatives"] = [Shot(**a) for a in s.get("alternatives", [])]
            segs.append(Segment(**s))
        d.setdefault("overlay", None)  # міграція v1 -> v2
        d["voiceover_words"] = [Word(**w) for w in d.get("voiceover_words", [])]  # v3
        d["version"] = PLAN_VERSION
        return Plan(segments=segs, **d)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")

    @staticmethod
    def load(path: Path) -> "Plan":
        return Plan.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
