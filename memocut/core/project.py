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
from .brief import BriefError, load_brief
from .library import GameFolder
from .edit import save_revision
from .models import Catalog, Plan, Shot, Word
from .tts import VO_DELAY, VO_TAIL, TTSConfig, synthesize

Progress = Callable[[str, float], None]


def safe_name(s: str) -> str:
    return re.sub(r'[<>:"/\\|?*]+', "_", s).strip() or "project"


def audio_duration(path: Path) -> float:
    from .proc import run
    from . import paths
    p = run([paths.ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            check=False)
    try:
        return float(p.stdout.strip())
    except ValueError:
        return 0.0


def fit_slots(brief, target: float) -> None:
    """Розтягнути/стиснути гнучкі сцени (any/find), щоб ролик тривав приблизно target секунд."""
    from ..planner.rules import DEFAULT_ANY
    fixed = sum((s.end - (s.start or 0)) for s in brief.slots if s.clip and s.end is not None)
    flex = [s for s in brief.slots if not s.clip]
    if not flex:
        return
    have = sum(s.duration or DEFAULT_ANY for s in flex)
    k = max(target - fixed, 1.2 * len(flex)) / have
    for s in flex:
        s.duration = round(max(1.2, (s.duration or DEFAULT_ANY) * k), 2)


def extend_to(plan: Plan, catalog: Catalog, target: float) -> None:
    """Якщо кліпи коротші, ніж треба під озвучку, — дотягнути кінці сегментів у межах їхніх файлів."""
    need = target - plan.duration
    for seg in reversed(plan.segments):
        if need <= 0.05:
            break
        clip = catalog.get(seg.shot.file)
        if not clip:
            continue
        add = min(need, max(0.0, clip.duration - 0.05 - seg.shot.end))
        if add > 0:
            seg.shot = Shot(seg.shot.file, seg.shot.start, round(seg.shot.end + add, 3),
                            seg.shot.score, seg.shot.reason)
            need -= add


def resolve_game_clips(brief) -> None:
    """clip: LUB-UA-041 (ID з КАТАЛОГ.csv) -> шлях файлу відносно source_dir."""
    game = GameFolder.detect(brief.source_path())
    if not game:
        return
    src = brief.source_path()
    for s in brief.slots:
        if s.clip:
            rel = game.resolve_clip(s.clip)
            if rel != s.clip:
                full = game.root / rel
                try:
                    s.clip = full.relative_to(src).as_posix()
                except ValueError:
                    raise BriefError(f"Файл {s.clip} ({rel}) лежить поза папкою {src}") from None


def generate(brief_path: str | Path, out_dir: str | Path | None = None, *, preview: bool = True,
             transcripts: bool = True, planner: str = "rules", tts: Optional[TTSConfig] = None,
             style: str | None = None, variations: int | None = None,
             progress: Optional[Progress] = None) -> list[Path]:
    """style / variations — перевизначення з GUI (якщо None, береться з ТЗ)."""
    say = progress or (lambda m, f: None)
    brief = load_brief(brief_path)
    if style:
        brief.style = style
    if variations:
        brief.variations = int(variations)
    resolve_game_clips(brief)
    catalog = analyze(brief.source_path(), transcripts=transcripts, folders=brief.folders,
                      progress=lambda m, f: say(m, f * 0.4))
    base = Path(out_dir) if out_dir else Path(brief_path).parent / "output"
    vo = None
    if brief.voiceover:
        say("Озвучка (ElevenLabs)…", 0.4)
        mp3, words = synthesize(brief.voiceover, tts or TTSConfig.from_env(), base.parent / "озвучка", brief.voice)
        vo_dur = audio_duration(mp3) or (words[-1]["e"] if words else 0)
        target = VO_DELAY + vo_dur + VO_TAIL
        if brief.fit_voiceover:
            fit_slots(brief, target)
        vo = (mp3, words, target)
    plans = get_planner(planner).make_plans(brief, catalog)
    if vo:
        mp3, words, target = vo
        for plan in plans:
            if brief.fit_voiceover:
                extend_to(plan, catalog, target)
            plan.voiceover = str(mp3)
            plan.voiceover_words = [Word(**w) for w in words]
            plan.voice_volume = brief.voice_volume
            plan.voice_subtitles = brief.voice_subtitles
    for plan in plans:
        plan.original_volume = (brief.original_volume if brief.original_volume is not None
                                else (0.2 if vo else 1.0))
    root = base / safe_name(brief.name)
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


def output_root(brief_path: str | Path, out_dir: str | Path | None = None) -> Path:
    """Папка з результатами для ТЗ (там, де generate створить var1, var2, ...)."""
    brief = load_brief(brief_path)
    root = Path(out_dir) if out_dir else Path(brief_path).parent / "output"
    return root / safe_name(brief.name)


def list_variations(root: str | Path) -> list[Path]:
    """Готові варіації в папці результатів (var1, var2, ...), відсортовані за номером."""
    root = Path(root)
    found = [p for p in root.glob("var*") if (p / "plan.json").is_file()]
    if (root / "plan.json").is_file():  # вибрали саму папку варіації
        found = [root]
    return sorted(found, key=lambda p: int(re.sub(r"\D", "", p.name) or 0))


def load_variation(folder: Path) -> tuple[Plan, Catalog]:
    from ..analyze.catalog import CACHE_DIRNAME
    plan = Plan.load(folder / "plan.json")
    cat = Catalog.load(Path(plan.source_dir) / CACHE_DIRNAME / "catalog.json")
    return plan, cat


def rerender(folder: Path, preview: bool = True, progress: Optional[Progress] = None) -> Path:
    plan, cat = load_variation(folder)
    return Renderer(cat, progress).render(plan, folder / ("preview.mp4" if preview else "final.mp4"),
                                          preview=preview)
