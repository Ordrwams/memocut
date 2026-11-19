"""Читання ТЗ (brief.yaml) і перевірка полів.

Приклад — briefs/example.yaml. Кожен пункт у `segments` — це «слот»:
  - clip: "IMG_01.mp4" + start/end     -> точний шматок
  - find: "фраза"                      -> шукати фразу в транскрипті
  - any: true                          -> будь-який якісний фрагмент
Додатково: look (що в кадрі — пошук в описах КАТАЛОГу), title (напис на екрані), duration, subtitles,
from (обмежити пошук файлами за маскою).
clip може бути ID з КАТАЛОГ.csv папки гри (напр. "LUB-UA-041").

Верхній рівень: name, source_dir, folders (підпапки гри), format, style, variations,
overlay (текст на весь ролик), cta, music, music_volume, notes.
ТЗ можна зібрати у формі програми: brief_to_yaml() пише файл, parse_brief() читає дані.
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
    look: Optional[str] = None   # що має бути в кадрі — шукається в описах КАТАЛОГу гри


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
    overlay: Optional[str] = None  # текст поверх усього відео
    folders: Optional[list[str]] = None  # підпапки source_dir, з яких брати відео (None = усі)
    voiceover: Optional[str] = None      # текст озвучки (ElevenLabs)
    voice: Optional[str] = None          # voice_id ElevenLabs (None = голос з Налаштувань)
    voice_volume: float = 1.0
    voice_subtitles: bool = True         # субтитри з озвучки (замість субтитрів з мови відео)
    fit_voiceover: bool = True           # підігнати тривалість сцен під довжину озвучки
    original_volume: Optional[float] = None  # гучність звуку з відео (None: 0.2 з озвучкою, 1.0 без)
    base_dir: Path = Path(".")

    def source_path(self) -> Path:
        p = Path(self.source_dir)
        return p if p.is_absolute() else (self.base_dir / p).resolve()


class BriefError(ValueError):
    pass


FORMATS = {"9x16", "1x1", "16x9", "4x5"}


def load_brief(path: str | Path) -> Brief:
    path = Path(path)
    return parse_brief(_load_yaml(path.read_text(encoding="utf-8-sig")), path.parent, path.stem)


def brief_from_text(text: str, base_dir: str | Path = ".", default_name: str = "Відео") -> Brief:
    """Те саме, що load_brief, але з тексту (вкладка YAML у програмі)."""
    return parse_brief(_load_yaml(text), Path(base_dir), default_name)


def _load_yaml(text: str) -> dict:
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" (рядок {mark.line + 1})" if mark else ""
        raise BriefError(f"Помилка у файлі ТЗ{where}: {getattr(e, 'problem', None) or e}") from None
    if not isinstance(data, dict):
        raise BriefError("ТЗ має бути набором полів (name:, source_dir:, segments: …)")
    return data


def parse_brief(data: dict, base_dir: Path, default_name: str = "Відео") -> Brief:
    if not data.get("source_dir"):
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
        name=str(data.get("name") or default_name),
        source_dir=str(data["source_dir"]),
        format=fmt,
        style=str(data.get("style", "couples_warm")),
        variations=int(data.get("variations", 3)),
        slots=slots,
        cta=data.get("cta"),
        music=data.get("music"),
        music_volume=float(data.get("music_volume", 0.15)),
        notes=data.get("notes"),
        overlay=(str(data["overlay"]).strip() or None) if data.get("overlay") else None,
        folders=[str(f) for f in data["folders"]] if data.get("folders") else None,
        voiceover=(str(data["voiceover"]).strip() or None) if data.get("voiceover") else None,
        voice=str(data["voice"]) if data.get("voice") else None,
        voice_volume=float(data.get("voice_volume", 1.0)),
        voice_subtitles=bool(data.get("voice_subtitles", True)),
        fit_voiceover=bool(data.get("fit_voiceover", True)),
        original_volume=float(data["original_volume"]) if data.get("original_volume") is not None else None,
        base_dir=Path(base_dir).resolve(),
    )


# ---- запис ТЗ у YAML (з форми програми) ----

def _q(v) -> str:
    """Одне значення YAML в один рядок (рядки в лапках, якщо треба)."""
    if isinstance(v, str):
        if "\n" in v:  # лише тут потрібні подвійні лапки з екрануванням
            return '"' + v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
        return "'" + v.replace("'", "''") + "'"  # одинарні: шляхи з \ читаються як є
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "null"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


SLOT_ORDER = ["find", "any", "clip", "start", "end", "look", "from", "title", "duration", "subtitles"]


def brief_to_yaml(d: dict) -> str:
    """Словник ТЗ (як у файлі) -> читабельний YAML з коментарями. Порожні поля пропускаються."""
    L = ["# ТЗ на відео для MemoCut. Можна редагувати в програмі (вкладка «Форма») або тут.", ""]

    def put(key, comment=""):
        v = d.get(key)
        if v is None or (isinstance(v, (str, list)) and not v):
            return
        L.append(f"{key}: {_q(v)}" + (f"    # {comment}" if comment else ""))

    put("name", "назва ролика")
    put("source_dir", "папка гри або папка з відео")
    if d.get("folders"):
        L.append("folders:                # з яких підпапок брати відео")
        L += [f"  - {_q(f)}" for f in d["folders"]]
    put("format", "9x16 | 1x1 | 4x5 | 16x9")
    put("style", "файл зі styles/")
    put("variations", "скільки різних варіантів змонтувати")
    L.append("")
    L.append("segments:               # сцени по порядку; перша — хук")
    for i, seg in enumerate(d.get("segments") or [], 1):
        keys = [k for k in SLOT_ORDER if k in seg] + [k for k in seg if k not in SLOT_ORDER]
        first = True
        for k in keys:
            v = seg[k]
            if v is None or (k == "subtitles" and v is True) or (k == "any" and not v):
                continue
            prefix = "  - " if first else "    "
            note = f"    # {i}. {'хук' if i == 1 else 'сцена'}" if first else ""
            L.append(f"{prefix}{k}: {_q(v)}{note}")
            first = False
        if first:  # порожня сцена
            L.append(f"  - any: true    # {i}")
    L.append("")
    if d.get("voiceover"):
        L.append("voiceover: |           # текст озвучки (ElevenLabs)")
        L += ["  " + ln if ln.strip() else "" for ln in str(d["voiceover"]).rstrip().splitlines()]
        put("voice", "голос ElevenLabs (voice_id); порожньо = з Налаштувань")
        for k, c in (("voice_subtitles", "субтитри з озвучки"), ("fit_voiceover", "підігнати сцени під озвучку"),
                     ("original_volume", "гучність звуку з відео, 0..1"), ("voice_volume", "гучність озвучки")):
            if k in d:
                put(k, c)
        L.append("")
    put("overlay", "текст поверх усього відео")
    put("cta", "фінальна картка")
    put("music", "файл музики")
    if d.get("music"):
        put("music_volume")
    if d.get("notes"):
        L.append("")
        L.append("notes: |               # вільний текст ТЗ (для довідки)")
        L += ["  " + ln if ln.strip() else "" for ln in str(d["notes"]).rstrip().splitlines()]
    return "\n".join(L).rstrip() + "\n"


def load_brief_data(path: str | Path) -> dict:
    """Сирі дані ТЗ з файлу (для заповнення форми)."""
    return _load_yaml(Path(path).read_text(encoding="utf-8-sig"))
