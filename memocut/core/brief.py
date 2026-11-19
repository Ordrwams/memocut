"""Читання ТЗ (brief.yaml) і перевірка полів.

Приклад — briefs/example.yaml. Кожен пункт у `segments` — це «слот»:
  - clip: "IMG_01.mp4" + start/end     -> точний шматок
  - find: "фраза"                      -> шукати фразу в транскрипті
  - any: true                          -> будь-який якісний фрагмент
Додатково: title, duration, subtitles, from (обмежити пошук файлами за маскою).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import yaml


@dataclass
class Slot:
    clip: Optional[str] = None
    start: Optional[float] = None
    end: Optional[float] = None
    find: Optional[str] = None
    any: bool = False
    duration: Optional[float] = None
    title: Optional[str] = None
    subtitles: bool = True
    from_: Optional[str] = None  # glob-маска файлів, напр. "IMG_04*"


@dataclass
class Brief:
    name: str
    source_dir: str
    format: str = "9x16"
    style: str = "couples_warm"
    variations: int = 3
    slots: list[Slot] = field(default_factory=list)
    cta: Optional[str] = None
    music: Optional[str] = None
    music_volume: float = 0.15
    notes: Optional[str] = None  # вільний текст ТЗ (поки ігнорується; для ШІ-планувальника)
    base_dir: Path = Path(".")

    def source_path(self) -> Path:
        p = Path(self.source_dir)
        return p if p.is_absolute() else (self.base_dir / p).resolve()


class BriefError(ValueError):
    pass


FORMATS = {"9x16", "1x1", "16x9", "4x5"}


def load_brief(path: str | Path) -> Brief:
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if "source_dir" not in data:
        raise BriefError("У ТЗ немає поля source_dir (папка з сирими відео)")
    slots = []
    for i, raw in enumerate(data.get("segments") or [], 1):
        if not isinstance(raw, dict):
            raise BriefError(f"Сегмент {i}: очікується набір полів, отримано {raw!r}")
        raw = dict(raw)
        if "from" in raw:
            raw["from_"] = raw.pop("from")
        unknown = set(raw) - set(Slot.__dataclass_fields__)
        if unknown:
            raise BriefError(f"Сегмент {i}: невідомі поля {sorted(unknown)}")
        s = Slot(**raw)
        if not (s.clip or s.find or s.any):
            raise BriefError(f"Сегмент {i}: вкажіть clip, find або any: true")
        slots.append(s)
    if not slots:
        raise BriefError("У ТЗ немає жодного сегмента (segments)")
    fmt = str(data.get("format", "9x16"))
    if fmt not in FORMATS:
        raise BriefError(f"Формат {fmt} не підтримується. Доступні: {sorted(FORMATS)}")
    return Brief(
        name=str(data.get("name") or path.stem),
        source_dir=str(data["source_dir"]),
        format=fmt,
        style=str(data.get("style", "couples_warm")),
        variations=int(data.get("variations", 3)),
        slots=slots,
        cta=data.get("cta"),
        music=data.get("music"),
        music_volume=float(data.get("music_volume", 0.15)),
        notes=data.get("notes"),
        base_dir=path.parent.resolve(),
    )
