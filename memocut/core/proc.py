"""Запуск ffmpeg/ffprobe без вікон консолі на Windows."""
from __future__ import annotations

import os
import subprocess
from typing import Optional

_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class FFmpegError(RuntimeError):
    pass


def run(args: list[str], cwd: Optional[str] = None, check: bool = True) -> subprocess.CompletedProcess:
    p = subprocess.run(
        args, cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", creationflags=_NO_WINDOW,
    )
    if check and p.returncode != 0:
        tail = "\n".join(p.stderr.strip().splitlines()[-15:])
        raise FFmpegError(f"Помилка {os.path.basename(args[0])}:\n{tail}")
    return p
