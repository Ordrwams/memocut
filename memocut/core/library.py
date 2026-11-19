"""Папка гри MemoGames після каталогізатора:

  <Гра>/01_Готові | 02_Сирі | 03_Фото | 04_СММ | 05_З текстом… | 06_Не перевірено
  <Гра>/_для монтажу/{превю, proxy, тексти}   + КАТАЛОГ.csv (id;type;…;dest;proxy;text;…)

MemoCut бере відео з вибраних підпапок, готові транскрипти з `тексти/<ID>.txt`
(`[хв:сек-хв:сек] текст`), а для швидкого аналізу — 480p-проксі з тими самими таймкодами.
Звичайна папка з відео (без цієї структури) теж працює — тоді все це просто не використовується.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

CATALOG_CSV = "КАТАЛОГ.csv"
WORK_DIR = "_для монтажу"
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".mts"}
# Підпапки, які ніколи не беремо: відео з текстом, неперевірені, службові.
NEVER = re.compile(r"^(05|06)[_ .]|^_|^\.|фото", re.IGNORECASE)
DEFAULT_ON = re.compile(r"^(02|04)[_ .]")  # Сирі, СММ


@dataclass
class Entry:
    id: str
    rel: str            # шлях від кореня гри (posix)
    desc: str = ""
    duration: float = 0.0
    proxy: Optional[str] = None
    text: Optional[str] = None
    note: str = ""


@dataclass
class GameFolder:
    root: Path
    entries: dict[str, Entry] = field(default_factory=dict)   # rel -> Entry
    by_id: dict[str, Entry] = field(default_factory=dict)

    # ---- пошук ----
    @staticmethod
    def detect(path: str | Path) -> Optional["GameFolder"]:
        """Знайти корінь гри для вибраної папки (саму гру або одну з її підпапок)."""
        p = Path(path).resolve()
        for cand in (p, p.parent):
            if (cand / CATALOG_CSV).is_file() or any(
                    (cand / n).is_dir() for n in ("02_Сирі", "01_Готові", WORK_DIR)):
                g = GameFolder(cand)
                g._read_catalog()
                return g
        return None

    def _read_catalog(self) -> None:
        f = self.root / CATALOG_CSV
        if not f.is_file():
            return
        with f.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh, delimiter=";"):
                rel = (row.get("dest") or "").replace("\\", "/").strip()
                if not rel:
                    continue
                try:
                    dur = float(row.get("dur") or 0)
                except ValueError:
                    dur = 0.0
                e = Entry(id=(row.get("id") or "").strip(), rel=rel, desc=row.get("desc") or "",
                          duration=dur, proxy=(row.get("proxy") or None), text=(row.get("text") or None),
                          note=row.get("note") or "")
                self.entries[rel] = e
                if e.id:
                    self.by_id[e.id.upper()] = e

    # ---- підпапки ----
    def subfolders(self) -> list[tuple[str, int, bool]]:
        """(назва, кількість відео, увімкнена за замовчуванням) для підпапок гри, які можна брати."""
        out = []
        for d in sorted(p for p in self.root.iterdir() if p.is_dir()):
            if NEVER.search(d.name):
                continue
            n = sum(1 for f in d.rglob("*") if f.suffix.lower() in VIDEO_EXT)
            if n:
                out.append((d.name, n, bool(DEFAULT_ON.search(d.name))))
        return out

    def default_folders(self) -> list[str]:
        return [n for n, _c, on in self.subfolders() if on]

    # ---- дані для аналізу ----
    def _file(self, rel_value: Optional[str]) -> Optional[Path]:
        if not rel_value:
            return None
        p = self.root / rel_value.replace("\\", "/")
        return p if p.is_file() else None

    def transcript(self, rel: str) -> Optional[Path]:
        e = self.entries.get(rel)
        p = self._file(e.text) if e else None
        return p if p and p.stat().st_size > 0 else None

    def has_transcript_file(self, rel: str) -> bool:
        """Транскрипт уже робили (файл є, навіть порожній = мови немає) — Whisper не потрібен."""
        e = self.entries.get(rel)
        return bool(e and self._file(e.text))

    def proxy(self, rel: str) -> Optional[Path]:
        e = self.entries.get(rel)
        return self._file(e.proxy) if e else None

    def resolve_clip(self, value: str) -> str:
        """ID з каталогу (LUB-UA-041) -> шлях файлу від кореня гри; інше повертається як є."""
        e = self.by_id.get(str(value).strip().upper())
        return e.rel if e else value


def skip_dir(name: str) -> bool:
    return bool(NEVER.search(name))


_TIMED = re.compile(r"^\s*\[(\d+):(\d+(?:\.\d+)?)\s*-\s*(\d+):(\d+(?:\.\d+)?)\]\s*(.*)$")


def words_from_timed_txt(p: Path) -> list[dict]:
    """`[00:02.1-00:04.1] Текст репліки` -> слова, рівномірно розкладені в межах репліки."""
    out = []
    for line in p.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        m = _TIMED.match(line)
        if not m:
            continue
        s = int(m.group(1)) * 60 + float(m.group(2))
        e = int(m.group(3)) * 60 + float(m.group(4))
        words = m.group(5).split()
        if not words or e <= s:
            continue
        step = (e - s) / len(words)
        out += [{"w": w, "s": round(s + k * step, 3), "e": round(s + (k + 1) * step, 3)}
                for k, w in enumerate(words)]
    return out
