"""GUI MemoCut (етап 2, PySide6). Запуск: `python app.py` або `python -m memocut.gui`.

Сторінки: start_page (ТЗ) → progress_page (монтаж) → gallery (прев'ю варіацій).
Уся логіка — у core/project.py та core/edit.py; GUI лише викликає їх у фоновому потоці.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

STYLE = """
QWidget { font-size: 10pt; color: #1d1b19; }
QMainWindow, QStackedWidget > QWidget { background: #f6f3ef; }
QLabel#h1 { font-size: 20pt; font-weight: 700; }
QLabel#h2 { font-size: 13pt; font-weight: 600; }
QLabel#muted { color: #6f6861; }
QLabel#small { color: #4a4540; font-size: 9pt; }
QLabel#error { color: #b3261e; }
QFrame#card { background: #ffffff; border: 1px solid #e4ddd5; border-radius: 10px; }
QPushButton { background: #ffffff; border: 1px solid #d6cec5; border-radius: 6px; padding: 7px 14px; }
QPushButton:hover { background: #f1ece6; }
QPushButton:disabled { color: #a59d95; background: #f4f1ed; }
QPushButton#primary { background: #c2572e; color: #ffffff; border: none; font-weight: 600; }
QPushButton#primary:hover { background: #a94822; }
QPushButton#primary:disabled { background: #e0b9a8; }
QListWidget, QPlainTextEdit, QComboBox, QSpinBox {
    background: #ffffff; border: 1px solid #d6cec5; border-radius: 6px; padding: 4px; }
QListWidget::item { padding: 5px; }
QListWidget::item:hover { background: #f6efe8; }
QProgressBar { background: #e9e2da; border: none; border-radius: 4px; height: 8px; }
QProgressBar::chunk { background: #c2572e; border-radius: 4px; }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }
"""


def _setup_logging() -> Path:
    from ..core.paths import user_data_dir
    log_path = user_data_dir() / "memocut.log"
    logging.basicConfig(
        filename=log_path, level=logging.INFO, encoding="utf-8",
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return log_path


def run(argv: list[str] | None = None) -> int:
    """Відкрити вікно. Необов'язковий аргумент — шлях до ТЗ (напр. файл перетягнули на .exe)."""
    argv = list(sys.argv[1:] if argv is None else argv)
    _setup_logging()

    from PySide6.QtWidgets import QApplication
    from .main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("MemoCut")
    app.setOrganizationName("MemoGames")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)

    brief = next((Path(a) for a in argv if a.lower().endswith((".yaml", ".yml"))), None)
    win = MainWindow(brief)
    win.show()
    return app.exec()
