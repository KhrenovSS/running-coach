# Tools состояния (State tools): get_athlete_state, get_safety_verdict — DEV_PLAN §5
#
# Скилл ≠ tool: все state-скиллы едут внутри get_athlete_state — добавление скилла
# не меняет схему и не рушит prompt cache. (Skills ride inside one tool.)

from __future__ import annotations

from src.coach.rules.p1_safety import evaluate_safety
from src.coach.state import assess_state
from src.coach.tools.context import ToolContext
from src.coach.tools.serialize import jsonable


def get_athlete_state(ctx: ToolContext, args: dict) -> dict:
    """Полный снимок состояния: скиллы, скоры, missing (full athlete state snapshot)."""
    state = assess_state(ctx.user_id, db=ctx.db)
    payload = jsonable(state)
    payload.pop("signals", None)   # внутреннее сырьё safety, LLM видит вердикт
    payload.pop("user_id", None)   # LLM не нуждается в идентификаторах
    return payload


def get_safety_verdict(ctx: ToolContext, args: dict) -> dict:
    """Границы безопасности ДО предложения тренировки (safety bounds up front)."""
    state = assess_state(ctx.user_id, db=ctx.db)
    return jsonable(evaluate_safety(state))
