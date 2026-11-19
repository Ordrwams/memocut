"""Тести GUI без екрана (QT_QPA_PLATFORM=offscreen) і без ffmpeg: сторінки, картки, пошук результатів."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from memocut.core import project  # noqa: E402
from memocut.core.models import Plan, Segment, Shot  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)


def _plan(i):
    return Plan(name="Тест", source_dir="/src", format="9x16", style="couples_warm", variation=i,
                segments=[Segment("s1", Shot("A.mp4", 0, 2), title="Привіт")])


def test_start_page(app, settings, tmp_path):
    from memocut.gui.start_page import StartPage
    page = StartPage(settings)
    (tmp_path / "raw").mkdir()
    good = tmp_path / "b.yaml"
    good.write_text("name: Промо\nsource_dir: raw\nstyle: minimal_box\nvariations: 2\n"
                    "segments:\n - find: привіт\n   title: Хук\n - any: true\n", encoding="utf-8")
    assert page.load(good)
    assert page.b_name.text() == "Промо" and page.go.isEnabled()
    assert page.style_box.currentText() == "minimal_box" and page.var_box.value() == 2
    assert "«привіт»" in page.b_slots.text()
    got = []
    page.start_requested.connect(lambda p, o: got.append((p, o)))
    page.go.click()
    assert got[0][1] == {"style": "minimal_box", "variations": 2, "transcripts": True}
    assert page.recent.count() == 1

    bad = tmp_path / "bad.yaml"
    bad.write_text("segments: []\n", encoding="utf-8")
    assert not page.load(bad) and "source_dir" in page.err.text()

    nodir = tmp_path / "nodir.yaml"
    nodir.write_text("source_dir: nope\nsegments:\n - any: true\n", encoding="utf-8")
    assert page.load(nodir) and not page.go.isEnabled()


def test_list_variations(tmp_path):
    for i in (2, 1, 10):
        _plan(i).save(tmp_path / f"var{i}" / "plan.json")
    (tmp_path / "var5").mkdir()  # без plan.json — ігнорується
    names = [p.name for p in project.list_variations(tmp_path)]
    assert names == ["var1", "var2", "var10"]
    assert project.list_variations(tmp_path / "var2") == [tmp_path / "var2"]


def test_gallery_cards(app, tmp_path):
    from memocut.gui.gallery import GalleryPage, load_results, video_size
    for i in (1, 2, 3):
        _plan(i).save(tmp_path / "out" / f"var{i}" / "plan.json")
    folders, title = load_results(tmp_path / "out")
    assert len(folders) == 3 and title == "Тест"
    g = GalleryPage()
    g.show_results(folders, title)
    assert [c.head.text() for c in g.cards] == ["Варіація 1", "Варіація 2", "Варіація 3"]
    assert "s1: A.mp4 0.0–2.0 «Привіт»" in g.cards[0].segs.text()
    assert "Прев'ю немає" in g.cards[0].note.text()
    v = video_size("9x16")
    assert v.height() > v.width()
    g.clear()
    assert g.cards == []
