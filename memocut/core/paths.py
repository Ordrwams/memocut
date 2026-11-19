"""Де лежать ffmpeg, шрифти, стилі — і в режимі розробки, і в зібраному .exe."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def app_root() -> Path:
    """Папка з ресурсами (assets, styles). У .exe — тимчасова папка PyInstaller."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def exe_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return app_root()


def _find_tool(name: str) -> str:
    exe = name + (".exe" if os.name == "nt" else "")
    for d in (exe_dir() / "ffmpeg", exe_dir(), app_root() / "ffmpeg"):
        if (d / exe).exists():
            return str(d / exe)
    found = shutil.which(name)
    if not found:
        raise RuntimeError(f"Не знайдено {name}. Покладіть {exe} у папку ffmpeg поруч із програмою.")
    return found


def ffmpeg() -> str:
    return _find_tool("ffmpeg")


def ffprobe() -> str:
    return _find_tool("ffprobe")


def fonts_dir() -> Path:
    return app_root() / "assets" / "fonts"


def styles_dirs() -> list[Path]:
    """Користувацькі стилі (поруч із програмою) мають пріоритет над вбудованими."""
    return [exe_dir() / "styles", app_root() / "styles"]


def user_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.local/share")
    p = Path(base) / "MemoCut"
    p.mkdir(parents=True, exist_ok=True)
    return p
