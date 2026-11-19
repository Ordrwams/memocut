"""Папка гри MemoGames (КАТАЛОГ.csv, тексти/<ID>.txt) і запис ТЗ у YAML — без ffmpeg."""
from pathlib import Path

from memocut.analyze.catalog import list_videos
from memocut.core.brief import brief_from_text, brief_to_yaml
from memocut.core.library import GameFolder, words_from_timed_txt
from memocut.core.models import Plan, Segment, Shot
from memocut.core.style import load_style
from memocut.render.ass import segment_ass

CSV = ("\ufeffid;type;group;file;desc;dur;dest;proxy;text;note\n"
       "LUB-UA-001;02_Сирі;Анна;a.MOV;Пара грає;12.5;02_Сирі/Анна/a.MOV;_для монтажу/proxy/LUB-UA-001.mp4;"
       "_для монтажу/тексти/LUB-UA-001.txt;\n"
       "LUB-UA-002;04_СММ;;b.mp4;Коробка;5;04_СММ/b.mp4;;_для монтажу/тексти/LUB-UA-002.txt;\n")


def make_game(root: Path) -> Path:
    for f in ["02_Сирі/Анна/a.MOV", "04_СММ/b.mp4", "05_З текстом (не використовувати)/c.mp4",
              "01_Готові/Готове.MOV", "03_Фото/x.jpg", "_для монтажу/proxy/LUB-UA-001.mp4"]:
        (root / f).parent.mkdir(parents=True, exist_ok=True)
        (root / f).write_bytes(b"x")
    t = root / "_для монтажу/тексти"
    t.mkdir(parents=True)
    (t / "LUB-UA-001.txt").write_text("[00:00.1-00:02.1] Ти подивишся на мене?\n[01:02.0-01:03.0] Так\n",
                                      encoding="utf-8")
    (t / "LUB-UA-002.txt").write_text("", encoding="utf-8")
    (root / "КАТАЛОГ.csv").write_text(CSV, encoding="utf-8")
    return root


def test_game_folder(tmp_path):
    root = make_game(tmp_path / "02. Між Нами")
    g = GameFolder.detect(root)
    assert g and g.root == root.resolve()
    assert GameFolder.detect(root / "02_Сирі").root == root.resolve()   # вибрали підпапку
    assert GameFolder.detect(tmp_path) is None
    subs = {n: (c, on) for n, c, on in g.subfolders()}
    assert subs == {"01_Готові": (1, False), "02_Сирі": (1, True), "04_СММ": (1, True)}
    assert g.resolve_clip("lub-ua-002") == "04_СММ/b.mp4"
    assert g.resolve_clip("IMG_1.mp4") == "IMG_1.mp4"
    assert g.transcript("02_Сирі/Анна/a.MOV").name == "LUB-UA-001.txt"
    assert g.transcript("04_СММ/b.mp4") is None and g.has_transcript_file("04_СММ/b.mp4")
    assert g.proxy("02_Сирі/Анна/a.MOV").name == "LUB-UA-001.mp4"

    names = {p.name for p in list_videos(g.root, None, g)}
    assert names == {"a.MOV", "b.mp4", "Готове.MOV"}                    # без 05_, проксі, фото
    assert {p.name for p in list_videos(g.root, ["02_Сирі"], g)} == {"a.MOV"}


def test_timed_txt(tmp_path):
    root = make_game(tmp_path / "g")
    w = words_from_timed_txt(root / "_для монтажу/тексти/LUB-UA-001.txt")
    assert [x["w"] for x in w] == ["Ти", "подивишся", "на", "мене?", "Так"]
    assert w[0]["s"] == 0.1 and w[3]["e"] == 2.1 and w[4]["s"] == 62.0


def test_brief_yaml_roundtrip():
    d = {"name": "Промо 'пари'", "source_dir": r"E:\01. MemoGames\Україна\02. Між Нами",
         "folders": ["02_Сирі", "04_СММ"], "format": "9x16", "style": "couples_warm", "variations": 2,
         "segments": [{"find": "так сміялися", "title": "Хук", "duration": 3.0, "subtitles": False},
                      {"any": True, "duration": 2.5},
                      {"clip": "LUB-UA-001", "start": 1.5, "end": 4.0, "title": "Два\nрядки"}],
         "overlay": "memogames.ua", "cta": "Замовляй", "notes": "Тепле відео.\n\nЕмоції."}
    b = brief_from_text(brief_to_yaml(d), ".")
    assert b.source_dir == d["source_dir"] and b.folders == ["02_Сирі", "04_СММ"]
    assert b.name == "Промо 'пари'" and b.variations == 2 and b.overlay == "memogames.ua"
    assert [(s.find, s.any, s.clip) for s in b.slots] == [("так сміялися", False, None), (None, True, None),
                                                          (None, False, "LUB-UA-001")]
    assert b.slots[0].subtitles is False and b.slots[1].subtitles is True
    assert b.slots[2].title == "Два\nрядки" and b.notes.startswith("Тепле відео.\n\nЕмоції.")


def test_overlay_and_plan_migration(tmp_path):
    seg = Segment("s1", Shot("A.mp4", 0, 2))
    text = segment_ass(seg, None, load_style("couples_warm"), 1080, 1920, overlay="memogames.ua")
    assert "Style: Overlay," in text and ",Overlay,,0,0,0,,memogames.ua" in text
    p = Plan(name="x", source_dir="/s", format="9x16", style="couples_warm", segments=[seg])
    d = p.to_dict()
    d.pop("overlay")
    d["version"] = 1
    p2 = Plan.from_dict(d)                                  # старий plan.json відкривається
    assert p2.overlay is None and p2.version == 2
