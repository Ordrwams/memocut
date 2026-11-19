"""Повний цикл: ТЗ -> аналіз -> N варіацій -> прев'ю. Його ж викликатиме GUI.

Структура результату:
  <out>/<назва>/var1/plan.json
                     preview.mp4
                     history/plan_r1.json
                     final.mp4           (після «Експорт»)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Optional

from ..analyze.catalog import analyze
from ..planner.base import get_planner
from ..render.engine import Renderer
from .brief import load_brief
from .edit import save_revision
from .models import Catalog, Plan

Progress = Callable[[str, float], None]


def safe_name(s: str) -> str:
    return re.sub(r'[<>:"/\\|?*]+', "_", s).strip() or "project"


def generate(brief_path: str | Path, out_dir: str | Path | None = None, *, preview: bool = True,
             transcripts: bool = True, planner: str = "rules",
             progress: Optional[Progress] = None) -> list[Path]:
    say = progress or (lambda m, f: None)
    brief = load_brief(brief_path)
    catalog = analyze(brief.source_path(), transcripts=transcripts,
                      progress=lambda m, f: say(m, f * 0.4))
    plans = get_planner(planner).make_plans(brief, catalog)
    root = Path(out_dir) if out_dir else Path(brief_path).parent / "output"
    root = root / safe_name(brief.name)
    results = []
    for i, plan in enumerate(plans):
        folder = root / f"var{plan.variation}"
        save_revision(plan, folder)
        r = Renderer(catalog, lambda m, f, i=i: say(f"Варіація {i + 1}: {m}",
                                                   0.4 + 0.6 * (i + f) / len(plans)))
        r.render(plan, folder / ("preview.mp4" if preview else "final.mp4"), preview=preview)
        results.append(folder)
    say("Готово", 1.0)
    return results


def load_variation(folder: Path) -> tuple[Plan, Catalog]:
    from ..analyze.catalog import CACHE_DIRNAME
    plan = Plan.load(folder / "plan.json")
    cat = Catalog.load(Path(plan.source_dir) / CACHE_DIRNAME / "catalog.json")
    return plan, cat


def rerender(folder: Path, preview: bool = True, progress: Optional[Progress] = None) -> Path:
    plan, cat = load_variation(folder)
    return Renderer(cat, progress).render(plan, folder / ("preview.mp4" if preview else "final.mp4"),
                                          preview=preview)
