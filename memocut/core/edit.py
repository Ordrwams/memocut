"""Операції редактора над планом. GUI викликає тільки ці функції.

Кожна операція повертає новий Plan (старий не змінюється) з revision + 1,
тому історію правок і «Відмінити» реалізувати просто: зберігати список планів.
"""
from __future__ import annotations

import copy
from pathlib import Path

from .models import Catalog, Plan, Segment, Shot


class EditError(ValueError):
    pass


def _clone(plan: Plan) -> Plan:
    p = copy.deepcopy(plan)
    p.revision += 1
    return p


def _seg(plan: Plan, seg_id: str) -> Segment:
    for s in plan.segments:
        if s.id == seg_id:
            return s
    raise EditError(f"Сегмент {seg_id} не знайдено")


def use_alternative(plan: Plan, seg_id: str, index: int) -> Plan:
    """Замінити шматок на альтернативу №index; поточний іде в альтернативи."""
    p = _clone(plan)
    s = _seg(p, seg_id)
    if not 0 <= index < len(s.alternatives):
        raise EditError("Немає такої альтернативи")
    new = s.alternatives.pop(index)
    s.alternatives.insert(0, s.shot)
    s.shot = new
    return p


def replace_with_file(plan: Plan, seg_id: str, catalog: Catalog, file: str,
                      start: float | None = None, end: float | None = None) -> Plan:
    """«Вибрати файл»: підставити інший кліп. Без таймкодів — найкращий шматок тієї ж тривалості."""
    from ..planner.rules import window_candidates
    clip = catalog.get(file)
    if clip is None:
        raise EditError(f"Файл {file} не проаналізовано")
    p = _clone(plan)
    s = _seg(p, seg_id)
    if start is None:
        dur = s.shot.duration
        cands = sorted(window_candidates(clip, dur), key=lambda x: -x.score)
        new = cands[0] if cands else Shot(file, 0.0, min(dur, clip.duration))
        new.reason = "вибрано вручну"
    else:
        e = clip.duration if end is None else end
        new = Shot(file, max(0.0, start), min(clip.duration, e), 1.0, "вибрано вручну")
    s.alternatives.insert(0, s.shot)
    s.shot = new
    return p


def trim(plan: Plan, seg_id: str, start: float, end: float, catalog: Catalog | None = None) -> Plan:
    """Обрізка: нові вхід/вихід у межах того ж файлу."""
    p = _clone(plan)
    s = _seg(p, seg_id)
    limit = catalog.get(s.shot.file).duration if catalog and catalog.get(s.shot.file) else None
    start = max(0.0, start)
    if limit is not None:
        end = min(end, limit)
    if end - start < 0.3:
        raise EditError("Шматок закороткий (менше 0.3 с)")
    s.shot = Shot(s.shot.file, round(start, 3), round(end, 3), s.shot.score, s.shot.reason)
    return p


def set_title(plan: Plan, seg_id: str, title: str | None) -> Plan:
    p = _clone(plan)
    _seg(p, seg_id).title = title or None
    return p


def set_subtitles(plan: Plan, seg_id: str, on: bool) -> Plan:
    p = _clone(plan)
    _seg(p, seg_id).subtitles = on
    return p


def move(plan: Plan, seg_id: str, new_index: int) -> Plan:
    p = _clone(plan)
    s = _seg(p, seg_id)
    p.segments.remove(s)
    p.segments.insert(max(0, min(new_index, len(p.segments))), s)
    return p


def remove(plan: Plan, seg_id: str) -> Plan:
    p = _clone(plan)
    if len(p.segments) <= 1:
        raise EditError("Не можна видалити останній сегмент")
    p.segments.remove(_seg(p, seg_id))
    return p


def save_revision(plan: Plan, folder: Path) -> Path:
    """Зберегти як plan.json (поточний) + history/plan_rN.json (історія)."""
    folder.mkdir(parents=True, exist_ok=True)
    plan.save(folder / "history" / f"plan_r{plan.revision}.json")
    plan.save(folder / "plan.json")
    return folder / "plan.json"
