"""Пресети стилю (styles/*.yaml). Відсутні поля беруться з DEFAULT."""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

from .paths import styles_dirs

DEFAULT = {
    "name": "default",
    "font": "Montserrat",
    "title": {
        "size": 84, "bold": True, "color": "#FFFFFF", "outline_color": "#000000",
        "outline": 5, "shadow": 2, "position": "top", "margin_v": 240,
        "animation": "fade", "uppercase": False, "box": False, "box_color": "#000000",
    },
    "subtitles": {
        "size": 62, "bold": True, "color": "#FFFFFF", "highlight_color": "#FFD54F",
        "outline_color": "#000000", "outline": 4, "shadow": 1, "position": "bottom",
        "margin_v": 380, "words_per_line": 4, "karaoke": True, "uppercase": False,
    },
    "end_card": {"background": "#111111", "color": "#FFFFFF", "size": 78, "duration": 2.5},
    "video": {"fps": 30, "fade_between": 0.0},
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def list_styles() -> list[str]:
    names = set()
    for d in styles_dirs():
        if d.exists():
            names.update(p.stem for p in d.glob("*.yaml"))
    return sorted(names)


def load_style(name: str) -> dict:
    for d in styles_dirs():
        p = d / f"{name}.yaml"
        if p.exists():
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            st = _merge(DEFAULT, data)
            st["name"] = name
            return st
    raise FileNotFoundError(f"Стиль «{name}» не знайдено. Доступні: {', '.join(list_styles()) or 'немає'}")
