"""Тести GUI без екрана (QT_QPA_PLATFORM=offscreen) і без ffmpeg: сторінки, картки, пошук результатів."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings  # noqa: E402

from memocut.core import project  # noqa: E402
from memocut.core.models import Plan, Segment, Shot  # noqa: E402


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)


def _plan(i):
    return Plan(name="Тест", source_dir="/src", format="9x16", style="couples_warm", variation=i,
                segments=[Segment("s1", Shot("A.mp4", 0, 2), title="Привіт")])


def test_brief_page(app, cleanup, settings, tmp_path):
    from test_library import make_game
    from memocut.core.brief import load_brief
    from memocut.gui.brief_page import BriefPage
    page = BriefPage(settings)
    cleanup.append(page)
    assert len(page.scenes) == 3 and page.validate() == "Виберіть папку з відео (розділ 1)."

    game = make_game(tmp_path / "02. Між Нами")
    page._set_source(game / "02_Сирі", None)            # вибрали підпапку — знайде корінь гри
    assert page.source_path() == game.resolve()
    assert [cb.property("folder") for cb in page.folder_checks if cb.isChecked()] == ["02_Сирі", "04_СММ"]
    assert "готових транскриптів 1" in page.src_info.text()

    page.name.setText("Промо 1")
    page.overlay.setText("memogames.ua")
    h = page.scenes[0]
    h.kind.setCurrentIndex(1)
    h.value.setText("подивишся на мене")
    h.title.setText("Гра | для пар")
    h.subs.setChecked(False)
    c = page.scenes[2]
    c.kind.setCurrentIndex(2)
    c.value.setText("LUB-UA-999")
    assert "LUB-UA-999" in page.validate()
    c.value.setText("lub-ua-001")
    c.start.setValue(1)
    c.end.setValue(3)
    assert page.validate() is None

    d = page.form_data()
    assert d["segments"][0] == {"find": "подивишся на мене", "title": "Гра\nдля пар", "duration": 3.0,
                                "subtitles": False}
    assert d["segments"][2] == {"clip": "lub-ua-001", "start": 1.0, "end": 3.0}

    # вкладка YAML: згенерувати, поправити руками, застосувати до форми
    page.tabs.setCurrentIndex(1)
    text = page.yaml.toPlainText()
    assert "name: 'Промо 1'" in text and "overlay: 'memogames.ua'" in text
    page.yaml.setPlainText(text.replace("'Промо 1'", "'Промо 2'"))
    assert page._apply_yaml() and page.name.text() == "Промо 2"
    page.yaml.setPlainText("segments: [")
    assert not page._apply_yaml() and "рядок" in page.yaml_status.text()
    page._yaml_dirty = False
    page.tabs.setCurrentIndex(0)

    got = []
    page.start_requested.connect(lambda p, o: got.append((p, o)))
    page._start()
    path, opts = got[0]
    assert path == game.resolve() / "MemoCut" / "ТЗ" / "Промо 2.yaml" and path.is_file()
    assert opts["out_dir"] == game.resolve() / "MemoCut" / "Результати"
    b = load_brief(path)
    assert b.folders == ["02_Сирі", "04_СММ"] and b.overlay == "memogames.ua" and len(b.slots) == 3

    page2 = BriefPage(settings)                          # відкрити той самий файл у новій сторінці
    cleanup.append(page2)
    assert page2.open_path(path) and page2.form_data()["segments"] == page.form_data()["segments"]


def test_list_variations(tmp_path):
    for i in (2, 1, 10):
        _plan(i).save(tmp_path / f"var{i}" / "plan.json")
    (tmp_path / "var5").mkdir()  # без plan.json — ігнорується
    names = [p.name for p in project.list_variations(tmp_path)]
    assert names == ["var1", "var2", "var10"]
    assert project.list_variations(tmp_path / "var2") == [tmp_path / "var2"]


def test_gallery_cards(app, cleanup, tmp_path):
    from memocut.gui.gallery import GalleryPage, load_results, video_size
    for i in (1, 2, 3):
        _plan(i).save(tmp_path / "out" / f"var{i}" / "plan.json")
    folders, title = load_results(tmp_path / "out")
    assert len(folders) == 3 and title == "Тест"
    g = GalleryPage()
    cleanup.append(g)
    g.show_results(folders, title)
    assert [c.head.text() for c in g.cards] == ["Варіація 1", "Варіація 2", "Варіація 3"]
    assert "s1: A.mp4 0.0–2.0 «Привіт»" in g.cards[0].segs.text()
    assert "Прев'ю немає" in g.cards[0].note.text()
    v = video_size("9x16")
    assert v.height() > v.width()
    g.clear()
    assert g.cards == []
