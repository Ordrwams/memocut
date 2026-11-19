"""Спільне для тестів GUI: один QApplication на весь прогін, який ніколи не знищується раніше за віджети.

На Windows Qt падає при виході, якщо QApplication прибрано раніше за плеєри/віджети.
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_APP = None


@pytest.fixture(scope="session")
def app():
    global _APP
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield _APP
    _APP.closeAllWindows()
    _APP.processEvents()


@pytest.fixture
def cleanup(app):
    """Віджети, додані в список, видаляються одразу після тесту (до виходу з Python)."""
    widgets = []
    yield widgets
    for w in widgets:
        w.deleteLater()
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()
