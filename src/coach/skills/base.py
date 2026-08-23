# Базовый контракт скилла (Skill base contract) — DEV_PLAN §3
#
# Скилл — МОДУЛЬНАЯ ЧИСТАЯ ФУНКЦИЯ (не класс): evaluate(user_id, *, db) -> SkillResult.
# `db` — обязательный keyword-only параметр, сессию владеет вызывающий код (§8 CLAUDE.md).
# (A skill is a module-level pure function; db is a required keyword-only parameter.)

from __future__ import annotations

from datetime import date
from typing import Final, Protocol

from sqlalchemy.orm import Session

from src.coach.contracts import STATUS_UNKNOWN, SkillResult


class SkillFn(Protocol):
    """Сигнатура скилла (skill signature)."""

    def __call__(self, user_id: int, *, db: Session) -> SkillResult: ...


# State-скиллы, входящие в AthleteState.skills. Порядок стабилен (детерминированный
# вывод для LLM). (State skills aggregated into AthleteState; stable order.)
SKILL_KEYS: Final[tuple[str, ...]] = ("fatigue", "recovery", "load", "distribution",
                                      "progress", "pain")


def unknown_result(key: str, reason: str = "no data") -> SkillResult:
    """Единый вырожденный результат «нет данных» — без исключений (uniform no-data result)."""
    return SkillResult(key=key, status=STATUS_UNKNOWN, value=None,
                       confidence=0.0, message=reason, evidence=reason)


def combined_confidence(parts: list[dict]) -> float:
    """Средняя уверенность по присутствующим компонентам (mean confidence of present parts)."""
    present = [p["confidence"] for p in parts if p.get("value") is not None]
    return round(sum(present) / len(present), 2) if present else 0.0


def worst_status(statuses: list[str], *, danger: set[str], warning: set[str]) -> str:
    """Худший статус из доменных компонентов → светофор ok/warning/danger/unknown.

    (Map domain component statuses to the closed traffic-light set, worst wins.)
    """
    known = [s for s in statuses if s and s != STATUS_UNKNOWN]
    if not known:
        return STATUS_UNKNOWN
    if any(s in danger for s in known):
        return "danger"
    if any(s in warning for s in known):
        return "warning"
    return "ok"


def freshest_date(*dates: date | None) -> date | None:
    """Самая свежая из дат (freshest of the given dates)."""
    present = [d for d in dates if d is not None]
    return max(present) if present else None
