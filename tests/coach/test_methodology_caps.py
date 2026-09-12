# Правки методики 07.09.2026 по итогам оценки рекомендаций: допуск лёгкой пробежки, доля
# длительной при малом объёме, частота при плоском объёме, «покажи план» ≠ пересборка.
from src.analysis.session_metrics import easy_discipline
from src.coach.config import (
    LONG_RUN_LOW_VOLUME_KM,
    LONG_RUN_MAX_PCT_LOW_VOLUME,
    LONG_RUN_MAX_PCT_WEEK,
    long_run_max_pct,
)
from src.telegram.handlers.coach import is_replan_request


def _zones(easy_pct: float, total_min: float = 35.0) -> dict:
    return {"available": True, "easy_time_pct": easy_pct, "total_min": total_min,
            "minutes": {}}


def test_easy_discipline_tolerates_short_z3_excursion():
    """02.09.2026: avg 133 при потолке 138, 13.7 % выше Z2 — образцовая лёгкая, флага нет."""
    d = easy_discipline(_zones(1 - 0.137), "easy", tolerance=0.20, avg_hr=133,
                        easy_ceiling_hr=138)
    assert d["applicable"] is True and d["flag"] is False
    assert d["avg_hr_above_easy"] is False


def test_easy_discipline_flags_large_share_or_avg_above_ceiling():
    over = easy_discipline(_zones(1 - 0.25), "easy", tolerance=0.20, avg_hr=134,
                           easy_ceiling_hr=138)
    assert over["flag"] is True
    avg_over = easy_discipline(_zones(1 - 0.15), "easy", tolerance=0.20, avg_hr=141,
                               easy_ceiling_hr=138)
    assert avg_over["flag"] is True and avg_over["avg_hr_above_easy"] is True
    # Нет потолка/пульса → критерий среднего не применяется (нет данных → нет флага)
    assert easy_discipline(_zones(1 - 0.15), "easy", tolerance=0.20)["flag"] is False


def test_long_run_max_pct_by_volume_and_frequency():
    assert long_run_max_pct(25.4, 5) == LONG_RUN_MAX_PCT_LOW_VOLUME     # < 40 км
    assert long_run_max_pct(35.0, 5) == LONG_RUN_MAX_PCT_LOW_VOLUME     # 12.09.2026: порог 30 → 40 км
    assert long_run_max_pct(40.0, 5) == LONG_RUN_MAX_PCT_WEEK           # ровно 40 — уже 30 %
    assert long_run_max_pct(45.0, 4) == LONG_RUN_MAX_PCT_LOW_VOLUME     # ≤ 4 пробежек
    assert long_run_max_pct(45.0, 5) == LONG_RUN_MAX_PCT_WEEK
    assert long_run_max_pct(LONG_RUN_LOW_VOLUME_KM, None) == LONG_RUN_MAX_PCT_WEEK
    assert long_run_max_pct(None, None) == LONG_RUN_MAX_PCT_WEEK


def test_enforce_run_days_keeps_structured_day():
    """Ускорения — каркас: при урезании дней первыми уходят ровные лёгкие, не структурный."""
    from src.coach.contracts import RecoverySpec, WorkoutProposal, WorkoutSegment
    from src.coach.planning import enforce_run_days

    strides = WorkoutProposal(workout_type="easy", target_zone=2, duration_min=42, for_days_ahead=3,
                              segments=[WorkoutSegment(role="warmup", amount_kind="min", amount_value=15),
                                        WorkoutSegment(role="work", amount_kind="sec", amount_value=20,
                                                       repeat=5, target_zone=3,
                                                       recovery=RecoverySpec(duration_min=2.0)),
                                        WorkoutSegment(role="cooldown", amount_kind="min", amount_value=15)])
    plain = [WorkoutProposal(workout_type="easy", target_zone=2, duration_min=60, for_days_ahead=d)
             for d in (1, 5)]
    long = WorkoutProposal(workout_type="long", target_zone=2, duration_min=70, for_days_ahead=7)
    kept, dropped = enforce_run_days([plain[0], strides, plain[1], long], 3)
    assert dropped == 1 and strides in kept and long in kept


def test_show_plan_is_not_replan():
    assert is_replan_request("нужен новый план на неделю")
    assert is_replan_request("Переделай план: сегодня не смогу")
    assert not is_replan_request("покажи новый план на неделю")
    assert not is_replan_request("какой у меня новый план на неделю?")
