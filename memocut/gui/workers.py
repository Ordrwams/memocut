"""Фонові задачі для GUI: усе важке (аналіз, рендер) іде в окремому потоці,
щоб вікно не зависало. Прогрес і результат повертаються сигналами Qt.

Скасування: прапорець перевіряється в колбеку прогресу, тож задача зупиняється
на найближчому кроці (після поточного сегмента/файлу).
"""
from __future__ import annotations

import logging
import traceback
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QThread, Signal

log = logging.getLogger("memocut.gui")


class Cancelled(BaseException):
    """BaseException, щоб її не «з'їли» блоки `except Exception` усередині аналізу."""


class Job(QObject):
    progress = Signal(str, float)   # повідомлення, 0..1
    finished = Signal(object)       # результат fn
    failed = Signal(str, str)       # коротко, повний traceback
    cancelled = Signal()

    def __init__(self, fn: Callable, *args, **kwargs):
        super().__init__()
        self._fn, self._args, self._kwargs = fn, args, kwargs
        self._stop = False

    def cancel(self) -> None:
        self._stop = True

    def _say(self, msg: str, frac: float) -> None:
        if self._stop:
            raise Cancelled()
        self.progress.emit(msg, float(frac))

    def run(self) -> None:
        try:
            res = self._fn(*self._args, progress=self._say, **self._kwargs)
        except Cancelled:
            self.cancelled.emit()
        except Exception as e:  # показуємо користувачу, а не падаємо
            log.exception("Помилка задачі")
            self.failed.emit(str(e) or e.__class__.__name__, traceback.format_exc())
        else:
            self.finished.emit(res)


def start_job(parent: QObject, job: Job) -> QThread:
    """Запустити Job у новому потоці. Потік сам прибирається після завершення."""
    th = QThread(parent)
    job.moveToThread(th)
    th.started.connect(job.run)
    for sig in (job.finished, job.failed, job.cancelled):
        sig.connect(th.quit)
    th.finished.connect(job.deleteLater)
    th.finished.connect(th.deleteLater)
    job._thread = th  # тримаємо посилання, щоб Python не прибрав об'єкти
    th.start()
    return th


# ---- готові задачі ----

def generate_job(brief: Path, *, out_dir: Path | None = None, transcripts: bool = True, tts=None) -> Job:
    from ..core import project
    return Job(project.generate, brief, out_dir, transcripts=transcripts, tts=tts)


def final_job(folder: Path) -> Job:
    from ..core import project
    return Job(project.rerender, folder, preview=False)
