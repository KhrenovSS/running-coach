# Контракты данных движка коуча (Coach engine data contracts) — Этап 0
# По decision_module_design.md §4/§5/§8. Дата-классы стабильны; логика — на этапах 1–2.

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class SkillResult:
    """Результат одного скилла (§4). Единый контракт для всех skills/*.

    key: идентификатор скилла; status: качественная оценка; value: числовое значение;
    confidence: 0..1 (падает при нехватке данных); evidence: объяснение источника.
    """
    key: str
    status: str = "unknown"
    value: Any = None
    confidence: float = 0.0
    message: str = ""
    evidence: str = ""


@dataclass
class AthleteState:
    """Снимок состояния спортсмена (§5) — вход для движка решений."""
    readiness_score: float | None = None
    fatigue_score: float | None = None
    injury_risk: float | None = None
    recovery_hours_left: float | None = None
    hrv_status: str | None = None
    ati_cti_ratio: float | None = None
    zone_balance: dict[str, float] = field(default_factory=dict)
    last_workout: dict[str, Any] | None = None
    progress: dict[str, Any] = field(default_factory=dict)
    skills: dict[str, SkillResult] = field(default_factory=dict)
    data_confidence: float = 0.0


@dataclass
class ReasoningStep:
    """Один шаг трассы рассуждений (audit-trail решения)."""
    rule: str
    decision: str
    reason: str


@dataclass
class Prescription:
    """Итоговое назначение тренировки (§8) — результат каскада правил."""
    when: date | None = None
    workout_type: str | None = None            # interval/tempo/long/recovery/easy/rest
    target: dict[str, Any] = field(default_factory=dict)     # темп/пульс/зоны
    volume: dict[str, Any] = field(default_factory=dict)     # км/время/повторы
    rationale: list[ReasoningStep] = field(default_factory=list)
    confidence: float = 0.0
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    predicted: dict[str, Any] = field(default_factory=dict)  # прогноз effort/HR/load
