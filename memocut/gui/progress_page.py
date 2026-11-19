"""Крок 2: прогрес монтажу (аналіз → варіації) з журналом і кнопкою «Скасувати»."""
from __future__ import annotations

import time

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QPushButton,
                               QVBoxLayout, QWidget)


class ProgressPage(QWidget):
    cancel_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.title = QLabel()
        self.title.setObjectName("h2")
        self.status = QLabel()
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.eta = QLabel()
        self.eta.setObjectName("muted")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        self.cancel = QPushButton("Скасувати")
        self.cancel.clicked.connect(self._cancel)

        row = QHBoxLayout()
        row.addWidget(self.eta)
        row.addStretch()
        row.addWidget(self.cancel)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 28)
        lay.addWidget(self.title)
        lay.addWidget(self.status)
        lay.addWidget(self.bar)
        lay.addLayout(row)
        lay.addWidget(self.log, 1)
        self._t0 = 0.0
        self._last = ""

    def begin(self, title: str) -> None:
        self.title.setText(title)
        self.status.setText("Підготовка…")
        self.bar.setValue(0)
        self.eta.clear()
        self.log.clear()
        self.cancel.setEnabled(True)
        self.cancel.setText("Скасувати")
        self._t0 = time.monotonic()
        self._last = ""

    def update_progress(self, msg: str, frac: float) -> None:
        frac = max(0.0, min(1.0, frac))
        self.status.setText(msg)
        self.bar.setValue(int(frac * 1000))
        if msg != self._last:
            self.log.appendPlainText(f"[{int(frac * 100):3d}%] {msg}")
            self._last = msg
        spent = time.monotonic() - self._t0
        if 0.05 < frac < 1 and spent > 5:
            left = spent * (1 - frac) / frac
            self.eta.setText(f"Залишилось приблизно {_fmt(left)}")
        else:
            self.eta.setText(f"Минуло {_fmt(spent)}")

    def _cancel(self) -> None:
        self.cancel.setEnabled(False)
        self.cancel.setText("Зупиняю…")
        self.status.setText("Зупиняю після поточного кроку…")
        self.cancel_requested.emit()


def _fmt(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 60} хв {sec % 60:02d} с" if sec >= 60 else f"{sec} с"
