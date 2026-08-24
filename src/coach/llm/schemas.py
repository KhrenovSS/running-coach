# Структурированный выход хода коуча (Structured coach-turn output) — DEV_PLAN §4.2
#
# Единственная форма, в которой предложение тренировки существует у LLM, —
# распарсенный CoachTurn. Числа прозой не принимаются. (The only shape a
# proposal can take; prose numbers are never trusted.)

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class WorkoutProposalIn(BaseModel):
    """Предложение тренировки от LLM — до границы safety (LLM proposal, pre-clamp)."""
    workout_type: Literal["rest", "recovery", "easy", "long", "tempo", "interval", "race"]
    target_zone: int = Field(default=1, ge=1, le=5)
    duration_min: int | None = Field(default=None, ge=10, le=240)
    distance_km: float | None = Field(default=None, ge=1, le=60)
    structure: str | None = Field(default=None, max_length=200)
    rationale: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("target_zone", mode="before")
    @classmethod
    def _zone_null_is_one(cls, v):
        """null/0 → 1: для rest модели шлют null-зону — семантически Z1 (инцидент 23.08)."""
        return 1 if v in (None, 0, "0") else v

    @field_validator("duration_min", "distance_km", mode="before")
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
                    "overreaching_sign", "great_session"]


class ReviewAssessment(BaseModel):
    """Структурированная оценка разбора (structured review outcome) — только kind=review.

    carry_forward — одна фраза «себе на завтра»: её читает утренний вердикт.
    """
    effort_match: Literal["ok", "harder", "easier", "unknown"] = "unknown"
    causes: list[CauseValue] = Field(default_factory=list, max_length=4)
    flags: list[FlagValue] = Field(default_factory=list, max_length=4)
    carry_forward: str | None = Field(default=None, max_length=300)


class CoachTurn(BaseModel):
    """Полный ход коуча: проза + опциональное предложение (full coach turn)."""
    message: str = Field(max_length=1500)
    proposal: WorkoutProposalIn | None = None
    followup_question: str | None = Field(default=None, max_length=200)
    log_suggestion: LogSuggestion | None = None
    assessment: ReviewAssessment | None = None   # D3: заполняется только в разборе


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
