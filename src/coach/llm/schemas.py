# Структурированный выход хода коуча (Structured coach-turn output) — DEV_PLAN §4.2
#
# Единственная форма, в которой предложение тренировки существует у LLM, —
# распарсенный CoachTurn. Числа прозой не принимаются. (The only shape a
# proposal can take; prose numbers are never trusted.)

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class WorkoutProposalIn(BaseModel):
    """Предложение тренировки от LLM — до границы safety (LLM proposal, pre-clamp)."""
    workout_type: Literal["rest", "recovery", "easy", "long", "tempo", "interval", "race"]
    target_zone: int = Field(ge=1, le=5)
    duration_min: int | None = Field(default=None, ge=10, le=240)
    distance_km: float | None = Field(default=None, ge=1, le=60)
    structure: str | None = Field(default=None, max_length=200)
    rationale: list[str] = Field(default_factory=list, max_length=5)


class LogSuggestion(BaseModel):
    """Предложение записать данные — подтверждается тапом пользователя (log via tap)."""
    kind: Literal["pain"]
    value: int = Field(ge=0, le=10)


class CoachTurn(BaseModel):
    """Полный ход коуча: проза + опциональное предложение (full coach turn)."""
    message: str = Field(max_length=1500)
    proposal: WorkoutProposalIn | None = None
    followup_question: str | None = Field(default=None, max_length=200)
    log_suggestion: LogSuggestion | None = None


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
