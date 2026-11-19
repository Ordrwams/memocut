"""Крок 3: галерея варіацій — прев'ю кожної (QMediaPlayer), опис і дії.

Фінальний рендер у повній якості йде чергою: по одній варіації за раз,
щоб не перевантажувати комп'ютер.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea,
                               QSlider, QSizePolicy, QStyle, QVBoxLayout, QWidget)

from ..core import project
from ..core.models import Plan
from ..render.engine import SIZES
from .workers import Job, final_job, start_job

BOX = QSize(270, 440)  # максимальний розмір відео в картці


def video_size(fmt: str) -> QSize:
    w, h = SIZES.get(fmt, (1080, 1920))
    k = min(BOX.width() / w, BOX.height() / h)
    return QSize(int(w * k), int(h * k))


def open_path(p: Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))


def _t(ms: int) -> str:
    s = max(0, ms) // 1000
    return f"{s // 60}:{s % 60:02d}"


class ClickableVideo(QVideoWidget):
    clicked = Signal()

    def mousePressEvent(self, e):  # noqa: N802 (Qt API)
        self.clicked.emit()
        super().mousePressEvent(e)


class VariationCard(QFrame):
    play_started = Signal(object)        # self
    final_requested = Signal(Path)
    edit_requested = Signal(Path)

    def __init__(self, folder: Path, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.folder = folder
        self.plan: Plan = Plan.load(folder / "plan.json")

        self.head = QLabel()
        self.head.setObjectName("h2")

        self.video = ClickableVideo()
        self.video.setFixedSize(video_size(self.plan.format))
        self.video.setStyleSheet("background:#000")
        self.video.clicked.connect(self.toggle)

        self.audio: QAudioOutput | None = None  # створюється при першому Play (швидший старт)
        self.player = QMediaPlayer(self)
        self.player.setVideoOutput(self.video)
        self.player.positionChanged.connect(self._pos)
        self.player.durationChanged.connect(lambda d: self.slider.setRange(0, d))
        self.player.playbackStateChanged.connect(self._state)
        self.player.mediaStatusChanged.connect(self._media_status)
        self.player.errorOccurred.connect(lambda _e, msg: self.note.setText(f"Не вдалося відтворити: {msg}"))

        self.play_btn = QPushButton()
        self.play_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.play_btn.setFixedWidth(40)
        self.play_btn.clicked.connect(self.toggle)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.sliderMoved.connect(self.player.setPosition)
        self.time = QLabel("0:00")
        self.time.setObjectName("muted")
        ctl = QHBoxLayout()
        ctl.addWidget(self.play_btn)
        ctl.addWidget(self.slider, 1)
        ctl.addWidget(self.time)

        self.info = QLabel()
        self.info.setObjectName("muted")
        self.segs = QLabel()
        self.segs.setObjectName("small")
        self.segs.setWordWrap(True)
        self.segs.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.final_btn = QPushButton("Експорт MP4")
        self.final_btn.setObjectName("primary")
        self.final_btn.setToolTip("Відрендерити final.mp4 у повній якості (1080p)")
        self.final_btn.clicked.connect(lambda: self.final_requested.emit(self.folder))
        self.open_final_btn = QPushButton("Відкрити відео")
        self.open_final_btn.clicked.connect(lambda: open_path(self.folder / "final.mp4"))
        folder_btn = QPushButton("Папка")
        folder_btn.clicked.connect(lambda: open_path(self.folder))
        self.edit_btn = QPushButton("Редагувати")
        self.edit_btn.setEnabled(False)
        self.edit_btn.setToolTip("Редактор з'явиться на етапі 3")
        self.edit_btn.clicked.connect(lambda: self.edit_requested.emit(self.folder))
        self.note = QLabel()
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)

        r1 = QHBoxLayout()
        r1.addWidget(self.final_btn, 1)
        r1.addWidget(self.open_final_btn)
        r2 = QHBoxLayout()
        r2.addWidget(self.edit_btn, 1)
        r2.addWidget(folder_btn)

        lay = QVBoxLayout(self)
        lay.addWidget(self.head)
        lay.addWidget(self.video, 0, Qt.AlignHCenter)
        lay.addLayout(ctl)
        lay.addWidget(self.info)
        lay.addWidget(self.segs)
        lay.addStretch()
        lay.addLayout(r1)
        lay.addLayout(r2)
        lay.addWidget(self.note)
        self.setFixedWidth(max(BOX.width(), self.video.width()) + 32)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)

        self.refresh()

    # ---- дані ----
    def refresh(self) -> None:
        """Перечитати plan.json і прев'ю (знадобиться редактору після правок)."""
        self.plan = Plan.load(self.folder / "plan.json")
        p = self.plan
        rev = f" · правка {p.revision}" if p.revision > 1 else ""
        self.head.setText(f"Варіація {p.variation}{rev}")
        self.info.setText(f"{p.duration:.1f} с · сегментів {len(p.segments)} · {p.style}")
        lines = []
        for s in p.segments:
            t = f" «{s.title}»" if s.title else ""
            lines.append(f"{s.id}: {s.shot.file} {s.shot.start:.1f}–{s.shot.end:.1f}{t}")
        self.segs.setText("\n".join(lines))
        self.open_final_btn.setVisible((self.folder / "final.mp4").is_file())
        prev = self.folder / "preview.mp4"
        if prev.is_file():
            self.player.setSource(QUrl.fromLocalFile(str(prev)))
        else:
            self.note.setText("Прев'ю немає — натисніть «Експорт MP4».")

    def release(self) -> None:
        """Відпустити файл (Windows блокує відкритий файл — потрібно перед перерендером)."""
        self.player.stop()
        self.player.setSource(QUrl())

    # ---- плеєр ----
    def toggle(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            if self.audio is None:
                self.audio = QAudioOutput(self)
                self.player.setAudioOutput(self.audio)
            self.play_started.emit(self)
            self.player.play()

    def pause(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()

    def _pos(self, ms: int) -> None:
        if not self.slider.isSliderDown():
            self.slider.setValue(ms)
        self.time.setText(f"{_t(ms)} / {_t(self.player.duration())}")

    def _state(self, st) -> None:
        icon = QStyle.SP_MediaPause if st == QMediaPlayer.PlayingState else QStyle.SP_MediaPlay
        self.play_btn.setIcon(self.style().standardIcon(icon))

    def _media_status(self, st) -> None:
        if st == QMediaPlayer.EndOfMedia:
            self.player.setPosition(0)
            self.player.pause()

    # ---- стан фінального рендеру ----
    def set_final_state(self, text: str, busy: bool) -> None:
        self.note.setText(text)
        self.final_btn.setEnabled(not busy)
        self.open_final_btn.setVisible((self.folder / "final.mp4").is_file() and not busy)


class GalleryPage(QWidget):
    back_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.root: Path | None = None
        self.cards: list[VariationCard] = []
        self.queue: list[Path] = []
        self.job: Job | None = None
        self._cur: VariationCard | None = None

        self.title = QLabel()
        self.title.setObjectName("h1")
        self.sub = QLabel()
        self.sub.setObjectName("muted")
        back = QPushButton("← Нове ТЗ")
        back.clicked.connect(self._back)
        self.folder_btn = QPushButton("Відкрити папку результатів")
        self.folder_btn.clicked.connect(lambda: self.root and open_path(self.root))
        head = QHBoxLayout()
        tl = QVBoxLayout()
        tl.addWidget(self.title)
        tl.addWidget(self.sub)
        head.addLayout(tl, 1)
        head.addWidget(back)
        head.addWidget(self.folder_btn)

        self.row = QHBoxLayout()
        self.row.setSpacing(16)
        holder = QWidget()
        hl = QHBoxLayout(holder)
        hl.addStretch()
        hl.addLayout(self.row)
        hl.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(holder)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.addLayout(head)
        lay.addWidget(scroll, 1)

    def show_results(self, folders: list[Path], title: str) -> None:
        self.clear()
        self.root = folders[0].parent if folders else None
        self.title.setText(title)
        self.sub.setText("Клікніть на відео, щоб переглянути. Збережіть ту варіацію, яка подобається.")
        for f in folders:
            try:
                card = VariationCard(f)
            except Exception as e:
                QMessageBox.warning(self, "MemoCut", f"Не вдалося відкрити {f}:\n{e}")
                continue
            card.play_started.connect(self._only_one_plays)
            card.final_requested.connect(self.enqueue_final)
            self.row.addWidget(card)
            self.cards.append(card)

    def clear(self) -> None:
        for c in self.cards:
            c.release()
            c.setParent(None)
            c.deleteLater()
        self.cards = []

    def busy(self) -> bool:
        return self.job is not None or bool(self.queue)

    def _back(self) -> None:
        if self.busy() and QMessageBox.question(
                self, "MemoCut", "Ще йде збереження відео. Зупинити й повернутися?") != QMessageBox.Yes:
            return
        self.stop_all()
        self.clear()
        self.back_requested.emit()

    def _only_one_plays(self, who: VariationCard) -> None:
        for c in self.cards:
            if c is not who:
                c.pause()

    def _card(self, folder: Path) -> VariationCard | None:
        return next((c for c in self.cards if c.folder == folder), None)

    # ---- черга фінальних рендерів ----
    def enqueue_final(self, folder: Path) -> None:
        if folder in self.queue or (self.job and getattr(self.job, "folder", None) == folder):
            return
        self.queue.append(folder)
        if c := self._card(folder):
            c.set_final_state("У черзі…", True)
        self._next()

    def _next(self) -> None:
        if self.job or not self.queue:
            return
        folder = self.queue.pop(0)
        self._cur = self._card(folder)
        if self._cur:
            self._cur.set_final_state("Рендер у повній якості…", True)
        job = final_job(folder)
        job.folder = folder
        # Підключаємо методи віджета (не лямбди): так Qt виконає їх у головному потоці.
        job.progress.connect(self._on_progress)
        job.finished.connect(self._on_finished)
        job.failed.connect(self._on_failed)
        job.cancelled.connect(self._on_cancelled)
        self.job = job
        start_job(self, job)

    def _on_progress(self, msg: str, frac: float) -> None:
        if self._cur:
            self._cur.set_final_state(f"{msg} · {int(frac * 100)}%", True)

    def _on_finished(self, out) -> None:
        self._done(f"Готово: {Path(out).name}")

    def _on_cancelled(self) -> None:
        self._done("Скасовано")

    def _on_failed(self, msg: str, tb: str) -> None:
        self._done("Помилка рендеру")
        from .main_window import show_error
        show_error(self, "Не вдалося зберегти відео", msg, tb)

    def _done(self, text: str) -> None:
        self.job = None
        if self._cur:
            self._cur.set_final_state(text, False)
        self._cur = None
        self._next()

    def stop_all(self) -> None:
        for f in self.queue:
            if c := self._card(f):
                c.set_final_state("", False)
        self.queue.clear()
        if self.job:
            self.job.cancel()


def load_results(root: Path) -> tuple[list[Path], str]:
    """Знайти варіації в папці; повертає (папки, заголовок)."""
    folders = project.list_variations(root)
    name = root.name if folders and folders[0] != root else root.parent.name
    if folders:
        try:
            name = Plan.load(folders[0] / "plan.json").name
        except Exception:
            pass
    return folders, name
