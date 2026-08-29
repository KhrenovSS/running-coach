# Контракты данных гибридного коуча (Hybrid coach data contracts) — DEV_PLAN §3
#
# Ключевой инвариант: `Prescription` создаётся ТОЛЬКО в safety.py::clamp() —
# единственный конструктор; source-гвард tests/coach/test_no_prescription_bypass.py.
# (Key invariant: Prescription is constructed only inside safety.clamp().)

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from src.coach.config import SAFETY_MAX_ZONE_DEFAULT

# Закрытый набор статусов скилла (closed status set) — светофор для LLM и карточек.
# Доменная детализация ('low', 'critical_elevated', …) живёт в message/evidence.
STATUS_OK = "ok"
STATUS_WARNING = "warning"
STATUS_DANGER = "danger"
STATUS_UNKNOWN = "unknown"


@dataclass
class SkillResult:
    """Результат одного скилла — единый контракт для всех skills/*.

    status: ok/warning/danger/unknown; value: числовое значение; unit: единица
    измерения (иначе LLM домыслит: HRV в мс легко спутать с пульсом); confidence:
    0..1 (падает при нехватке данных); as_of: дата данных (синк мог не пройти
    2 дня — «сегодня» по позавчерашним данным = враньё); evidence: сырые числа
    строкой для трассировки.
    """
    key: str
    status: str = STATUS_UNKNOWN
    value: Any = None
    confidence: float = 0.0
    message: str = ""
    evidence: str = ""
    unit: str | None = None
    as_of: date | None = None


@dataclass
class AthleteState:
    """Снимок состояния спортсмена — вход для LLM (tool get_athlete_state) и safety."""
    user_id: int | None = None
    as_of: date | None = None                 # дата свежайшей метрики (freshest metric date)
    readiness_score: float | None = None      # 0..100
    fatigue_score: float | None = None        # 0..100
    injury_risk: float | None = None          # 0..1
    recovery_hours_left: float | None = None
    hrv_status: str | None = None             # elevated/normal/low/very_low
    ati_cti_ratio: float | None = None
    zone_balance: dict[str, float] = field(default_factory=dict)   # {"z1_z2": .78, "z3_plus": .22}
    last_workout: dict[str, Any] | None = None
    progress: dict[str, Any] = field(default_factory=dict)
    skills: dict[str, SkillResult] = field(default_factory=dict)
    data_confidence: float = 0.0
    missing: list[str] = field(default_factory=list)  # чего система НЕ знает ('sleep', 'rpe', …)
    # Сырьё для evaluate_safety(state) — чистая функция без db, реплеябельна по снимку.
    # (Raw signals for the pure safety function — replayable from the snapshot alone.)
    signals: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReasoningStep:
    """Один шаг трассы рассуждений (audit-trail решения)."""
    rule: str        # "p1_safety" / "llm" / "fallback"
    decision: str
    reason: str


@dataclass
class SafetyVerdict:
    """Границы безопасности — вычисляются детерминированно из AthleteState (P1).

    LLM видит вердикт (tool get_safety_verdict), но гарантия — безусловный clamp():
    предложение может быть только сужено, никогда расширено. (DEV_PLAN §4)
    """
    allow_training: bool = True
    max_zone: int = SAFETY_MAX_ZONE_DEFAULT
    max_duration_min: int | None = None
    allowed_types: tuple[str, ...] = ()       # пусто = все разрешены (empty = all allowed)
    earliest_next_hard: datetime | None = None
    triggered: list[str] = field(default_factory=list)   # ключи сработавших под-правил
    reasons: list[ReasoningStep] = field(default_factory=list)


@dataclass
class WorkoutProposal:
    """Предложение тренировки ДО границы безопасности (от LLM или fallback).

    Существует отдельно от Prescription, чтобы «LLM не пробьёт safety» гарантировал
    тип, а не дисциплина. (Proposal BEFORE the safety boundary.)
    """
    workout_type: str                          # rest/recovery/easy/long/tempo/interval/race
    target_zone: int = 2
    duration_min: int | None = None
    distance_km: float | None = None
    target_pace_min_km: float | None = None    # задан → ведём по темпу (pace-lead mode)
    structure: str | None = None               # «10×400/400» и т.п.
    rationale: list[str] = field(default_factory=list)
    for_days_ahead: int = 0                    # 0 = сегодня, 1 = завтра (target day offset)


@dataclass
class PaceClampContext:
    """Прекомпьют оценок для safety-ветки темпа (pace clamp precompute).

    clamp() — чистая функция без БД; оценки «пульс на темпе» и «безопасный темп
    на потолке зоны» считает finalize() и передаёт сюда. Все поля могут быть
    None — мало данных. (Computed in finalize(); clamp stays DB-free.)
    """
    expected_hr: int | None = None             # прогноз пульса на целевом темпе
    safe_pace_min_km: float | None = None      # эмпирический темп на потолке зоны
    zone_ceiling_bpm: int | None = None        # потолок разрешённой зоны, уд/мин


@dataclass(kw_only=True)
class Prescription:
    """Итоговое назначение — ТОЛЬКО результат safety.clamp().

    kw_only + обязательное поле `safety` без дефолта: назначение невозможно собрать,
    не предъявив вердикт безопасности. proposal хранит исходное предложение ДО
    урезания — метрика дрейфа LLM. (Only clamp() output; `safety` is mandatory.)
    """
    safety: SafetyVerdict                      # ОБЯЗАТЕЛЬНОЕ — это и есть гарантия
    workout_type: str | None = None
    when: date | None = None
    earliest: datetime | None = None           # «не раньше 18:00» (recovery timing)
    target: dict[str, Any] = field(default_factory=dict)      # темп/пульс/зоны
    volume: dict[str, Any] = field(default_factory=dict)      # км/время/повторы
    rationale: list[ReasoningStep] = field(default_factory=list)
    confidence: float = 0.0
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    predicted: dict[str, Any] = field(default_factory=dict)   # прогноз effort/HR/load
    clamped: bool = False                      # safety урезал предложение
    source: str = "fallback"                   # llm | fallback
    proposal: WorkoutProposal | None = None    # что предлагали ДО урезания
