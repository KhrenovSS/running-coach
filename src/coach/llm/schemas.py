# Структурированный выход хода коуча (Structured coach-turn output) — DEV_PLAN §4.2
#
# Единственная форма, в которой предложение тренировки существует у LLM, —
# распарсенный CoachTurn. Числа прозой не принимаются. (The only shape a
# proposal can take; prose numbers are never trusted.)

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, Field, field_validator

from src.coach.config import PACE_TARGET_MAX_PER_KM, PACE_TARGET_MIN_PER_KM


class RecoverySpecIn(BaseModel):
    """Критерий восстановления между повторами (recovery criterion)."""
    until_hr: int | None = Field(default=None, ge=60, le=220)
    duration_min: float | None = Field(default=None, ge=0.1, le=30)
    distance_km: float | None = Field(default=None, ge=0.05, le=10)
    target_zone: int | None = Field(default=None, ge=1, le=5)


class WorkoutSegmentIn(BaseModel):
    """Сегмент тренировки от LLM — качественная структура, числа проставит система."""
    role: Literal["warmup", "work", "recovery", "cooldown", "steady"] = "steady"
    repeat: int = Field(default=1, ge=1, le=30)
    amount_kind: Literal["min", "sec", "km", "m", "open"] = "min"
    amount_value: float | None = Field(default=None, ge=0, le=180)
    target_zone: int | None = Field(default=None, ge=1, le=5)
    pace_target_min_km: float | None = Field(default=None, ge=PACE_TARGET_MIN_PER_KM,
                                             le=PACE_TARGET_MAX_PER_KM)
    effort: str | None = Field(default=None, max_length=80)
    recovery: RecoverySpecIn | None = None


class WorkoutProposalIn(BaseModel):
    """Предложение тренировки от LLM — до границы safety (LLM proposal, pre-clamp)."""
    workout_type: Literal["rest", "recovery", "easy", "long", "tempo", "interval", "race"]
    target_zone: int = Field(default=1, ge=1, le=5)
    duration_min: int | None = Field(default=None, ge=10, le=240)
    distance_km: float | None = Field(default=None, ge=1, le=60)
    target_pace_min_km: float | None = Field(default=None, ge=PACE_TARGET_MIN_PER_KM,
                                             le=PACE_TARGET_MAX_PER_KM)
    structure: str | None = Field(default=None, max_length=200)   # legacy (совместимость)
    segments: list[WorkoutSegmentIn] = Field(default_factory=list, max_length=12)
    rationale: list[str] = Field(default_factory=list, max_length=5)
    # На какой день назначение: 0 = сегодня, 1 = завтра, максимум неделя.
    # Относительный день, не ISO-дата — симметрично days_ago (инцидент 29.08:
    # воскресный план записался «на сегодня»). (Target day offset, not a date.)
    for_days_ahead: int = Field(default=0, ge=0, le=7)

    @field_validator("target_zone", mode="before")
    @classmethod
    def _zone_null_is_one(cls, v):
        """null/0 → 1: для rest модели шлют null-зону — семантически Z1 (инцидент 23.08)."""
        return 1 if v in (None, 0, "0") else v

    @field_validator("for_days_ahead", mode="before")
    @classmethod
    def _days_null_is_today(cls, v):
        """null → 0: не указан день — назначение на сегодня (null means today)."""
        return 0 if v is None else v

    @field_validator("duration_min", "distance_km", "target_pace_min_km", mode="before")
    @classmethod
    def _zero_is_none(cls, v):
        """0 → None: модели заполняют нули для rest — семантически «нет объёма».

        (Zero means no volume — models emit zeros for rest proposals; incident 23.08.)
        """
        if v in (0, 0.0, "0"):
            return None
        return v


class LogSuggestion(BaseModel):
    """Предложение записать данные — подтверждается тапом пользователя (log via tap)."""
    kind: Literal["pain"]
    value: int = Field(ge=0, le=10)


# Enum'ы оценки (D3): фиксированные значения — по ним считаются агрегации в
# weekly/monthly; менять значения задним числом нельзя, расширять — можно.
# (Fixed enums: aggregations depend on them; append-only.)
CauseValue = Literal["heat", "cold", "wind", "elevation", "terrain", "poor_sleep",
                     "fatigue", "pace_too_fast", "illness", "recovery_good", "other"]
FlagValue = Literal["hr_drift_high", "pain", "pace_hr_mismatch", "suspect_data",
                    "overreaching_sign", "great_session",
                    # M1 (METRICS_GUIDE §4/§6, append-only): детерминированные
                    # флаги из computed.flags — LLM не выставляет их сама
                    "easy_run_too_hard", "pace_unstable", "quality_volume_exceeded",
                    "interval_segment_too_long", "long_run_share_high",
                    "low_cadence", "rpe_elevated", "no_warmup",
                    # M2.2: соответствие назначению (plan_vs_actual)
                    "plan_intensity_exceeded", "plan_volume_exceeded",
                    # F3 (M2.1 разбора): восстановление между интервалами
                    "poor_interval_recovery"]

# §6 METRICS_GUIDE: только эти флаги LLM ставит сама (субъективные);
# остальные приходят из computed.flags и сливаются кодом оркестратора.
SUBJECTIVE_FLAGS = ("pain", "great_session")


class ReviewAssessment(BaseModel):
    """Структурированная оценка разбора (structured review outcome) — только kind=review.

    carry_forward — одна фраза «себе на завтра»: её читает утренний вердикт.
    """
    effort_match: Literal["ok", "harder", "easier", "unknown"] = "unknown"
    causes: list[CauseValue] = Field(default_factory=list, max_length=4)
    flags: list[FlagValue] = Field(default_factory=list, max_length=4)
    carry_forward: str | None = Field(default=None, max_length=300)

    @field_validator("flags", mode="before")
    @classmethod
    def _drop_unknown_flags(cls, v):
        """Невалидные флаги от LLM — выкинуть, не ронять весь ход разбора.

        На жаре/холмах LLM зеркалит контекст-имена из computed.flags (heat, hilly,
        decoupling_*), которых нет в enum FlagValue → строгая валидация раньше
        роняла CoachTurn целиком, и разбор уходил в деградированный fallback
        (инцидент 30.08.2026). Реальные детерминированные флаги всё равно пересобирает
        orchestrator._merged_flags из computed; у LLM значимы лишь субъективные
        pain/great_session. Дедуп + cap 4 — чтобы длина не роняла ход повторно.
        (Drop unknown LLM flags instead of failing the whole review turn.)
        """
        if v is None:
            return []
        if not isinstance(v, list):
            return v  # не список — пусть падает штатной ошибкой типа
        allowed = set(get_args(FlagValue))
        out: list = []
        for f in v:
            if f in allowed and f not in out:
                out.append(f)
        return out[:4]


class CoachTurn(BaseModel):
    """Полный ход коуча: проза + опциональное предложение (full coach turn)."""
    message: str = Field(max_length=1500)
    proposal: WorkoutProposalIn | None = None
    followup_question: str | None = Field(default=None, max_length=200)
    log_suggestion: LogSuggestion | None = None
    assessment: ReviewAssessment | None = None   # D3: заполняется только в разборе
    # Недельный план (решение владельца 29.08.2026): только для kind='plan',
    # for_days_ahead элемента = день; дубли/rest/день-0 чистит weekly_plan.py
    weekly_plan: list[WorkoutProposalIn] | None = Field(default=None, max_length=8)


def _strictify(schema: dict) -> dict:
    """additionalProperties: false на всех объектах (strict-совместимая схема)."""
    if schema.get("type") == "object":
        schema["additionalProperties"] = False
    for sub in schema.get("properties", {}).values():
        _strictify(sub)
    for sub in schema.get("$defs", {}).values():
        _strictify(sub)
    for key in ("anyOf", "allOf", "oneOf"):
        for sub in schema.get(key, []):
            _strictify(sub)
    items = schema.get("items")
    if isinstance(items, dict):
        _strictify(items)
    return schema


def coach_turn_json_schema() -> dict:
    """JSON Schema для output_config.format (schema for structured output)."""
    return _strictify(CoachTurn.model_json_schema())
