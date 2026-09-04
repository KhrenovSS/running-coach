# Ярлык тренировки с учётом плана (plan-aware training type) — решение владельца 04.09.2026
#
# Принцип: ПЛАН решает назначение тренировки (recovery/easy/long, tempo/interval/race),
# ФАКТ решает интенсивность — пульс на ПАНО или интервальная структура всегда качество,
# без них ярлык никогда не tempo (классификатор ставил tempo как catch-all, #290).
# Чистая функция без БД: пороги — параметры/константы, вызывающий (workout_insights)
# резолвит план и пульсовые якоря. Сырой ответ классификатора хранится отдельно
# (training_type_auto) — резолвер идемпотентен и обратим.
# (Plan decides purpose, measured data decides intensity; pure, DB-free.)

from __future__ import annotations

from src.analysis.week_structure import is_quality_session
from src.config.constants import (
    LONG_RUN_MIN_MINUTES,
    LONG_RUN_PLAN_RATIO,
    RECOVERY_MAX_HR_PCT,
    RECOVERY_MAX_LTHR_PCT,
    TYPE_SOURCE_AUTO,
    TYPE_SOURCE_PLAN,
)

_PURPOSE_TYPES = ("recovery", "easy", "long")
_QUALITY_PLAN_TYPES = ("tempo", "interval", "race")


def _is_long(duration_min: float | None, plan_duration_min: float | None) -> bool:
    if not duration_min:
        return False
    if duration_min >= LONG_RUN_MIN_MINUTES:
        return True
    return bool(plan_duration_min) and duration_min >= LONG_RUN_PLAN_RATIO * plan_duration_min


def _is_recovery_hr(avg_hr: int | None, max_hr: int | None, lthr: int | None) -> bool:
    if avg_hr is None:
        return False
    if lthr:
        return avg_hr <= RECOVERY_MAX_LTHR_PCT * lthr
    if max_hr:
        return avg_hr <= RECOVERY_MAX_HR_PCT * max_hr
    return False


def resolve_training_type(auto_type: str | None, plan_type: str | None, *,
                          avg_hr: int | None, max_hr: int | None, lthr: int | None,
                          duration_min: float | None,
                          plan_duration_min: float | None = None) -> tuple[str, str]:
    """(type, source): ярлык по классификатору + плану дня; source — auto | plan.

    auto_type — сырой ответ classify_training (interval — единственный структурный
    факт, которому верим безусловно). plan_type None/rest — плана нет.
    (Resolve the label from the raw classifier output and the day's plan.)
    """
    auto = auto_type or "easy"
    interval_detected = auto == "interval"
    hr_known = avg_hr is not None
    hr_quality = hr_known and is_quality_session("tempo", avg_hr, max_hr, lthr)
    plan = plan_type if plan_type in _PURPOSE_TYPES + _QUALITY_PLAN_TYPES else None

    # Факт: структура интервалов — всегда интервалы (measured structure wins)
    if interval_detected:
        return "interval", TYPE_SOURCE_AUTO

    if plan is None:
        # Без плана: качество — только по пульсу; иначе long по длительности, иначе easy/recovery
        if hr_quality:
            return (auto if auto in _QUALITY_PLAN_TYPES else "tempo"), TYPE_SOURCE_AUTO
        if hr_known and (auto == "long" or _is_long(duration_min, None)):
            return "long", TYPE_SOURCE_AUTO
        if auto == "recovery":
            return "recovery", TYPE_SOURCE_AUTO
        if not hr_known:
            return (auto if auto in _PURPOSE_TYPES else "easy"), TYPE_SOURCE_AUTO
        return "easy", TYPE_SOURCE_AUTO

    if plan in _PURPOSE_TYPES:
        if hr_quality:
            return "tempo", TYPE_SOURCE_AUTO        # лёгкая по плану, пробежанная как темповая
        if plan == "long":
            return ("long" if _is_long(duration_min, plan_duration_min) else "easy"), TYPE_SOURCE_PLAN
        if plan == "recovery":
            return ("recovery" if not hr_known or _is_recovery_hr(avg_hr, max_hr, lthr)
                    else "easy"), TYPE_SOURCE_PLAN
        return "easy", TYPE_SOURCE_PLAN

    # План — качественная: подтверждено пульсом → тип плана (race — единственный путь к ярлыку)
    if hr_quality:
        return plan, TYPE_SOURCE_PLAN
    if not hr_known:
        return (auto if auto in _PURPOSE_TYPES + _QUALITY_PLAN_TYPES else "easy"), TYPE_SOURCE_AUTO
    return "easy", TYPE_SOURCE_AUTO                  # план темповая, пробежал спокойно — факт
