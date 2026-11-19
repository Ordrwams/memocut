"""Командний рядок (етап 1). GUI (етап 2) використовуватиме ті самі функції.

  memocut run briefs/example.yaml            # аналіз + 3 варіації прев'ю
  memocut analyze "D:/Відео/Сирі"            # тільки аналіз папки
  memocut render output/Назва/var2 --final   # фінальний рендер варіації
  memocut alt output/Назва/var2 s3 0         # замінити сегмент s3 на альтернативу №0
  memocut trim output/Назва/var2 s3 1.2 4.8  # обрізка сегмента
  memocut show output/Назва/var2             # показати план і альтернативи
  memocut styles                             # список стилів
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _progress(msg: str, frac: float) -> None:
    print(f"[{int(frac * 100):3d}%] {msg}", flush=True)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="memocut", description="MemoCut — монтаж відео за ТЗ")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="ТЗ -> варіації")
    p.add_argument("brief")
    p.add_argument("--out")
    p.add_argument("--final", action="store_true", help="одразу повна якість")
    p.add_argument("--no-transcripts", action="store_true")

    p = sub.add_parser("analyze")
    p.add_argument("folder")
    p.add_argument("--no-transcripts", action="store_true")

    p = sub.add_parser("render")
    p.add_argument("variation")
    p.add_argument("--final", action="store_true")

    p = sub.add_parser("show")
    p.add_argument("variation")

    p = sub.add_parser("alt")
    p.add_argument("variation")
    p.add_argument("segment")
    p.add_argument("index", type=int)

    p = sub.add_parser("trim")
    p.add_argument("variation")
    p.add_argument("segment")
    p.add_argument("start", type=float)
    p.add_argument("end", type=float)

    p = sub.add_parser("replace")
    p.add_argument("variation")
    p.add_argument("segment")
    p.add_argument("file")
    p.add_argument("--start", type=float)
    p.add_argument("--end", type=float)

    sub.add_parser("styles")

    a = ap.parse_args(argv)
    from .core import edit, project

    if a.cmd == "run":
        for f in project.generate(a.brief, a.out, preview=not a.final,
                                  transcripts=not a.no_transcripts, progress=_progress):
            print("  ->", f)
    elif a.cmd == "analyze":
        from .analyze.catalog import analyze
        cat = analyze(a.folder, transcripts=not a.no_transcripts, progress=_progress)
        for c in cat.clips:
            print(f"  {c.file}: {c.duration:.1f}с, сцен {len(c.scenes)}, слів {len(c.words)}")
    elif a.cmd == "render":
        print("  ->", project.rerender(Path(a.variation), preview=not a.final, progress=_progress))
    elif a.cmd == "show":
        plan, _ = project.load_variation(Path(a.variation))
        print(f"{plan.name} · варіація {plan.variation} · правка {plan.revision} · {plan.duration:.1f}с")
        for s in plan.segments:
            print(f"  {s.id}: {s.shot.file} {s.shot.start:.2f}-{s.shot.end:.2f}  {s.title or ''}")
            for i, alt in enumerate(s.alternatives):
                print(f"      [{i}] {alt.file} {alt.start:.2f}-{alt.end:.2f} ({alt.score:.2f}, {alt.reason})")
    elif a.cmd in ("alt", "trim", "replace"):
        folder = Path(a.variation)
        plan, cat = project.load_variation(folder)
        if a.cmd == "alt":
            plan = edit.use_alternative(plan, a.segment, a.index)
        elif a.cmd == "trim":
            plan = edit.trim(plan, a.segment, a.start, a.end, cat)
        else:
            plan = edit.replace_with_file(plan, a.segment, cat, a.file, a.start, a.end)
        edit.save_revision(plan, folder)
        print("  ->", project.rerender(folder, progress=_progress))
    elif a.cmd == "styles":
        from .core.style import list_styles
        print("\n".join(list_styles()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
