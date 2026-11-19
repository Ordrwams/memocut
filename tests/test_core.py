"""Швидкі тести без ffmpeg: ТЗ, планувальник, правки, ASS."""
from pathlib import Path

import pytest

from memocut.core import edit
from memocut.core.brief import BriefError, load_brief
from memocut.core.models import Catalog, ClipInfo, Plan, Word
from memocut.core.style import load_style
from memocut.planner.rules import RulesPlanner, stem_eq
from memocut.render.ass import segment_ass


def words(text, start, step=0.4):
    out, t = [], start
    for w in text.split():
        out.append(Word(w, round(t, 2), round(t + step - 0.05, 2)))
        t += step
    return out


@pytest.fixture
def catalog():
    def clip(name, dur, ws=(), scenes=(), bright=120):
        return ClipInfo(file=name, duration=dur, width=720, height=1280, fps=30, has_audio=True,
                        mtime=1, size=1, scenes=list(scenes), brightness=[bright] * int(dur),
                        words=list(ws))
    return Catalog("/src", [
        clip("A.mp4", 12, words("ми так сміялися що аж сльози", 1.0), scenes=[4, 8]),
        clip("B.mp4", 10, words("чесно ми сміялись до ночі", 2.0)),
        clip("C.mp4", 8),
        clip("D.mp4", 6, bright=10),
    ])


def write_brief(tmp_path, body):
    p = tmp_path / "b.yaml"
    p.write_text(body, encoding="utf-8")
    return load_brief(p)


def test_brief_validation(tmp_path):
    with pytest.raises(BriefError):
        write_brief(tmp_path, "source_dir: x\nsegments: [{title: a}]")
    b = write_brief(tmp_path, "source_dir: x\nsegments:\n - any: true\n   from: 'IMG*'\n")
    assert b.slots[0].from_ == "IMG*" and b.variations == 3


def test_stem():
    assert stem_eq("сміялися", "сміялись")
    assert not stem_eq("гра", "сміх")


def test_planner_variations(tmp_path, catalog):
    b = write_brief(tmp_path, """source_dir: x
segments:
 - find: "так сміялися"
   duration: 3
 - any: true
   duration: 2
 - clip: C.mp4
   start: 1
   end: 3
""")
    plans = RulesPlanner().make_plans(b, catalog)
    assert len(plans) == 3
    assert plans[0].segments[0].shot.file == "A.mp4"          # найкращий збіг
    assert all(p.segments[2].shot.start == 1 for p in plans)   # точний шматок однаковий
    s2 = {(p.segments[1].shot.file, p.segments[1].shot.start) for p in plans}
    assert len(s2) == 3                                        # варіації різні
    assert all(p.segments[1].shot.file != "D.mp4" for p in plans)  # темний кліп не береться
    assert plans[0].segments[1].alternatives


def test_edit_ops(tmp_path, catalog):
    b = write_brief(tmp_path, "source_dir: x\nsegments:\n - any: true\n   duration: 2\n")
    plan = RulesPlanner().make_plans(b, catalog)[0]
    old = plan.segments[0].shot
    p2 = edit.use_alternative(plan, "s1", 0)
    assert p2.revision == 2 and p2.segments[0].alternatives[0] == old
    assert plan.segments[0].shot == old                        # оригінал не змінено
    p3 = edit.trim(p2, "s1", 0.5, 1.5, catalog)
    assert p3.segments[0].shot.duration == pytest.approx(1.0)
    with pytest.raises(edit.EditError):
        edit.trim(p3, "s1", 1.0, 1.1)
    p4 = edit.replace_with_file(p3, "s1", catalog, "C.mp4")
    assert p4.segments[0].shot.file == "C.mp4"
    path = edit.save_revision(p4, tmp_path / "v")
    assert Plan.load(path).revision == p4.revision


def test_ass(catalog):
    from memocut.core.models import Segment, Shot
    seg = Segment("s1", Shot("A.mp4", 0.8, 3.5), title="Привіт {світ}")
    text = segment_ass(seg, catalog.get("A.mp4"), load_style("couples_warm"), 1080, 1920)
    assert "Style: Title,Montserrat,82" in text
    assert "Привіт (світ)" in text
    assert text.count(",Sub,") >= 3
