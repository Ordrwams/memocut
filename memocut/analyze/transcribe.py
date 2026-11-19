"""Транскрипт по словах.

Порядок пошуку:
  1. Готовий файл поруч із відео: <name>.words.json  ([{"w","s","e"}, ...])
  2. Готовий <name>.srt — слова рівномірно розкладаються в межах репліки
  3. faster-whisper локально (модель качається один раз у %LOCALAPPDATA%/MemoCut/models)
Якщо нічого немає — порожній список (пошук фраз просто не знаходитиме цей кліп).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from ..core.paths import user_data_dir

MODEL = os.environ.get("MEMOCUT_WHISPER_MODEL", "small")
LANG = os.environ.get("MEMOCUT_LANG", "uk")
_model = None


def _from_srt(p: Path) -> list[dict]:
    def t(s: str) -> float:
        h, m, rest = s.replace(",", ".").split(":")
        return int(h) * 3600 + int(m) * 60 + float(rest)

    out = []
    for block in re.split(r"\n\s*\n", p.read_text(encoding="utf-8", errors="replace")):
        lines = [l for l in block.strip().splitlines() if l.strip()]
        tl = next((l for l in lines if "-->" in l), None)
        if not tl:
            continue
        a, b = [x.strip() for x in tl.split("-->")]
        s, e = t(a), t(b.split()[0])
        text = " ".join(lines[lines.index(tl) + 1:])
        words = text.split()
        if not words:
            continue
        step = (e - s) / len(words)
        out += [{"w": w, "s": round(s + k * step, 3), "e": round(s + (k + 1) * step, 3)}
                for k, w in enumerate(words)]
    return out


def _whisper(path: Path) -> list[dict]:
    global _model
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return []
    if _model is None:
        _model = WhisperModel(MODEL, device="cpu", compute_type="int8",
                              download_root=str(user_data_dir() / "models"))
    segs, _ = _model.transcribe(str(path), language=LANG or None, word_timestamps=True, vad_filter=True)
    out = []
    for seg in segs:
        for w in seg.words or []:
            txt = w.word.strip()
            if txt:
                out.append({"w": txt, "s": round(w.start, 3), "e": round(w.end, 3)})
    return out


def words_for(video: Path, whisper: bool = True, timed_txt: Path | None = None,
              known_empty: bool = False) -> list[dict]:
    """timed_txt — транскрипт із папки гри (`тексти/<ID>.txt`); known_empty — транскрипт уже робили,
    мови немає (порожній файл), тож Whisper не запускаємо."""
    side = video.with_suffix(".words.json")
    if side.exists():
        return json.loads(side.read_text(encoding="utf-8"))
    srt = video.with_suffix(".srt")
    if srt.exists():
        return _from_srt(srt)
    if timed_txt is not None:
        from ..core.library import words_from_timed_txt
        return words_from_timed_txt(timed_txt)
    if not whisper or known_empty:
        return []
    try:
        return _whisper(video)
    except Exception:
        return []
