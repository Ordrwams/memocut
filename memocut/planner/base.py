"""Інтерфейс планувальника. Сюди пізніше додається planner_ai (рівень 3).

Будь-який планувальник: (Brief, Catalog) -> list[Plan] (по одному на варіацію).
"""
from __future__ import annotations

from typing import Protocol

from ..core.brief import Brief
from ..core.models import Catalog, Plan


class Planner(Protocol):
    name: str

    def make_plans(self, brief: Brief, catalog: Catalog) -> list[Plan]: ...


def get_planner(name: str = "rules") -> Planner:
    if name == "rules":
        from .rules import RulesPlanner
        return RulesPlanner()
    # if name == "ai": from .ai import AIPlanner; return AIPlanner()
    raise ValueError(f"Невідомий планувальник: {name}")
