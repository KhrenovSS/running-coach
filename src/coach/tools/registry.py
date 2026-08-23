# Реестр tools — долгосрочный контракт LLM-поверхности (Tool registry) — DEV_PLAN §5
#
# TOOLS — ЯВНЫЙ КОРТЕЖ: порядок фиксирован (tools рендерятся первыми в запросе,
# перестановка обнуляет prompt cache). Имена и семантика v1 не меняются; входные
# схемы расширяются только опциональными полями. Все tools READ-ONLY —
# LLM не может изменить состояние БД (source-гвард test_tools_readonly).
# (Explicit tuple: fixed order; v1 names frozen; all tools are read-only.)

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from src.coach.tools import history_tools, knowledge_tools, state_tools
from src.coach.tools.context import ToolContext
from src.exceptions import ToolExecutionError
from src.utils.logger import get_logger

logger = get_logger("coach.tools")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str            # читает LLM; НИЧЕГО волатильного (кэш!)
    input_schema: dict          # JSON Schema: additionalProperties false + required
    fn: Callable[[ToolContext, dict], dict]


def _schema(properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="get_athlete_state",
        description=(
            "Полный снимок состояния бегуна: скиллы (усталость, восстановление, "
            "нагрузка, распределение 80/20, прогресс, боль), интегральные скоры, "
            "последняя тренировка, список missing — чего система не знает. "
            "Вызывай первым в каждом разговоре."),
        input_schema=_schema({}),
        fn=state_tools.get_athlete_state,
    ),
    ToolSpec(
        name="get_safety_verdict",
        description=(
            "Границы безопасности на сегодня: разрешена ли тренировка, потолок "
            "зоны и длительности, запрещённые типы, не-раньше-чем для интенсива, "
            "причины. Смотри ДО того, как предлагать тренировку — предложение "
            "за границами будет урезано."),
        input_schema=_schema({}),
        fn=state_tools.get_safety_verdict,
    ),
    ToolSpec(
        name="get_recent_workouts",
        description="Последние тренировки: тип, объём, темп, пульс, RPE, боль.",
        input_schema=_schema({
            "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
        }),
        fn=history_tools.get_recent_workouts,
    ),
    ToolSpec(
        name="get_workout_detail",
        description=("Детали одной тренировки: минуты по зонам, сегменты, погода, "
                     "боль и её фаза, заметки."),
        input_schema=_schema({"session_id": {"type": "integer"}}, ["session_id"]),
        fn=history_tools.get_workout_detail,
    ),
    ToolSpec(
        name="get_metrics_series",
        description=("Ряд метрики за период + среднее, наклон тренда и направление. "
                     "Метрики: hrv, rhr, tired_rate, recovery_pct, training_load, "
                     "vo2max, weight, pain."),
        input_schema=_schema({
            "metric": {"type": "string",
                       "enum": ["hrv", "rhr", "tired_rate", "recovery_pct",
                                "training_load", "vo2max", "weight", "pain"]},
            "days": {"type": "integer", "minimum": 7, "maximum": 180, "default": 30},
        }, ["metric"]),
        fn=history_tools.get_metrics_series,
    ),
    ToolSpec(
        name="get_weekly_summary",
        description=("Недельные объёмы: км, минуты, типы тренировок, доля лёгкого "
                     "против цели 80/20, изменение к прошлой неделе и допустимый "
                     "потолок роста объёма."),
        input_schema=_schema({
            "weeks": {"type": "integer", "minimum": 1, "maximum": 16, "default": 4},
        }),
        fn=history_tools.get_weekly_summary,
    ),
    ToolSpec(
        name="search_guides",
        description=("Поиск по методическим руководствам (база Лидьярда, 80/20 "
                     "Фицджеральда, прогрессия Дэниелса, правила боли в колене). "
                     "Возвращает цитаты-фрагменты."),
        input_schema=_schema({
            "query": {"type": "string", "maxLength": 200},
            "top_k": {"type": "integer", "minimum": 1, "maximum": 5, "default": 3},
        }, ["query"]),
        fn=knowledge_tools.search_guides,
    ),
)

_BY_NAME = {t.name: t for t in TOOLS}


def anthropic_tools() -> list[dict]:
    """Определения tools для Anthropic API (strict schemas)."""
    return [{
        "name": t.name,
        "description": t.description,
        "input_schema": t.input_schema,
        "strict": True,
    } for t in TOOLS]


def run_tool(name: str, args: dict, *, user_id: int, db) -> dict:
    """Выполнить tool по имени (execute tool by name).

    NotFoundError (ownership) пробрасывается — агент вернёт её как tool-ошибку;
    прочие сбои заворачиваются в ToolExecutionError.
    """
    spec = _BY_NAME.get(name)
    if spec is None:
        raise ToolExecutionError(f"unknown tool: {name!r}")
    ctx = ToolContext(user_id=user_id, db=db)
    try:
        return spec.fn(ctx, args or {})
    except (KeyError, ValueError, TypeError) as e:
        raise ToolExecutionError(f"tool {name} failed: {e}") from e
