"""Головне вікно: три сторінки (ТЗ → прогрес → галерея) у QStackedWidget."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMainWindow, QMessageBox, QStackedWidget, QWidget

from .. import __version__
from ..core import paths
from .gallery import GalleryPage, load_results
from .progress_page import ProgressPage
from .brief_page import BriefPage
from .workers import Job, generate_job, start_job


def show_error(parent: QWidget, title: str, msg: str, details: str = "") -> None:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Critical)
    box.setWindowTitle("MemoCut")
    box.setText(title)
    box.setInformativeText(msg)
    if details:
        box.setDetailedText(details)
    box.exec()


def _wait(job: Job, ms: int) -> bool:
    """Дочекатися потоку задачі; True — якщо він уже завершився."""
    try:
        return job._thread.wait(ms)
    except (AttributeError, RuntimeError):  # потік уже прибрано
        return True


class MainWindow(QMainWindow):
    def __init__(self, brief: Path | None = None):
        super().__init__()
        self.setWindowTitle(f"MemoCut {__version__}")
        self.resize(1180, 860)
        self.settings = QSettings("MemoGames", "MemoCut")
        self.job: Job | None = None
        self._brief: Path | None = None

        self.start = BriefPage(self.settings)
        self.progress = ProgressPage()
        self.gallery = GalleryPage()
        self.stack = QStackedWidget()
        for w in (self.start, self.progress, self.gallery):
            self.stack.addWidget(w)
        self.setCentralWidget(self.stack)

        self.start.start_requested.connect(self.run_brief)
        self.start.open_results.connect(self.open_results)
        self.progress.cancel_requested.connect(self._cancel)
        self.gallery.back_requested.connect(lambda: self.stack.setCurrentWidget(self.start))

        if geo := self.settings.value("geometry"):
            self.restoreGeometry(geo)
        if brief:
            self.start.open_path(Path(brief))

    def check_ffmpeg(self) -> bool:
        try:
            paths.ffmpeg()
            paths.ffprobe()
            return True
        except RuntimeError as e:
            show_error(self, "Не знайдено FFmpeg", str(e))
            return False

    # ---- монтаж ----
    def run_brief(self, brief: Path, opts: dict) -> None:
        if self.job or not self.check_ffmpeg():
            return
        self._brief = brief
        self.progress.begin(f"Монтаж: {self.start.current_name()}")
        self.stack.setCurrentWidget(self.progress)
        job = generate_job(brief, **opts)
        job.progress.connect(self.progress.update_progress)
        job.finished.connect(self._generated)
        job.failed.connect(self._failed)
        job.cancelled.connect(self._cancelled)
        self.job = job
        start_job(self, job)

    def _generated(self, folders: list[Path]) -> None:
        self.job = None
        self.gallery.show_results([Path(f) for f in folders], self.start.current_name())
        self.stack.setCurrentWidget(self.gallery)

    def _failed(self, msg: str, tb: str) -> None:
        self.job = None
        self.stack.setCurrentWidget(self.start)
        show_error(self, "Не вдалося змонтувати відео", msg, tb)

    def _cancelled(self) -> None:
        self.job = None
        self.stack.setCurrentWidget(self.start)

    def _cancel(self) -> None:
        if self.job:
            self.job.cancel()

    # ---- готові результати ----
    def open_results(self, root: Path) -> None:
        folders, name = load_results(root)
        if not folders:
            QMessageBox.information(self, "MemoCut",
                                    f"У папці {root} немає варіацій (var1, var2… з plan.json).")
            return
        self.gallery.show_results(folders, name)
        self.stack.setCurrentWidget(self.gallery)

    # ---- закриття ----
    def closeEvent(self, e):  # noqa: N802 (Qt API)
        if (self.job or self.gallery.busy()) and QMessageBox.question(
                self, "MemoCut", "Монтаж ще триває. Закрити програму?") != QMessageBox.Yes:
            e.ignore()
            return
        jobs = [j for j in (self.job, self.gallery.job) if j]
        if self.job:
            self.job.cancel()
        self.gallery.stop_all()
        self.gallery.clear()
        self.start.save_draft()
        self.settings.setValue("geometry", self.saveGeometry())
        # Даємо фоновим задачам кілька секунд зупинитися; ffmpeg, що працює, не чекаємо.
        if any(not _wait(j, 3000) for j in jobs):
            import os
            self.settings.sync()
            os._exit(0)
        super().closeEvent(e)
