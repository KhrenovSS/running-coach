# Скилл прогресса: тренды VO2max, веса и темпа лёгких пробежек (Progress skill)
# Философия продукта: прогресс = темп растёт, пульс/вес снижаются (DEV_PLAN §0).

from __future__ import annotations

from sqlalchemy.orm import Session

from src.coach.config import EASY_TYPES
from src.coach.contracts import SkillResult
from src.coach.skills.base import unknown_result
from src.coach.util import effective_training_type
from src.services.analytics_helpers import compute_slope, compute_trend_direction
from src.services.repositories_coach import CoachRepository


def evaluate(user_id: int, *, db: Session) -> SkillResult:
    """Тренды за 90 дней: VO2max (вверх = прогресс), вес (вниз = прогресс для цели),
    темп лёгких пробежек в мин/км (вниз = быстрее = прогресс).

    (90-day trends: VO2max up, weight down, easy-run pace down = progress.)
    """
    vo2_raw = CoachRepository.metrics_series(user_id, "vo2max", 90, db=db)
    weight_raw = CoachRepository.weight_series(user_id, days=90, db=db)
    vo2_series = [v for _, v in vo2_raw]
    weight_series = [v for _, v in weight_raw]
    easy_sessions = [
        s for s in reversed(CoachRepository.last_sessions(user_id, n=30, db=db))
        if effective_training_type(s) in EASY_TYPES and s.avg_pace
    ]
    easy_paces = [s.avg_pace for s in easy_sessions]

    # #221: тренды по календарным дням — пропуски синка/редкие взвешивания не сжимают время
    vo2_dir = compute_trend_direction(vo2_series, dates=[d for d, _ in vo2_raw])
    weight_dir = compute_trend_direction(weight_series, dates=[d for d, _ in weight_raw])
    pace_dir = compute_trend_direction(easy_paces, dates=[s.begin_ts for s in easy_sessions])
    vo2_slope = compute_slope(vo2_series, dates=[d for d, _ in vo2_raw])

    has_any = bool(vo2_series or weight_series or easy_paces)
    if not has_any:
        return unknown_result("progress", "no trend data")

    # Прогресс: VO2max растёт ИЛИ темп лёгких падает (быстрее). Регресс — наоборот.
    if vo2_dir == "up" or pace_dir == "down":
        status = "ok"
    elif vo2_dir == "down" and pace_dir == "up":
        status = "warning"
    else:
        status = "ok"  # stable — для «медленного, но устойчивого» это норма

    n_points = len(vo2_series) + len(weight_series) + len(easy_paces)
    return SkillResult(
        key="progress",
        status=status,
        value=round(vo2_slope, 4) if vo2_slope is not None else None,
        confidence=min(0.9, round(n_points / 60, 2)),
        message=f"vo2max={vo2_dir}; weight={weight_dir}; easy_pace={pace_dir}",
        evidence=(f"vo2max: n={len(vo2_series)}, slope={vo2_slope}; "
                  f"weight: n={len(weight_series)}, dir={weight_dir}; "
                  f"easy_pace: n={len(easy_paces)}, dir={pace_dir}"),
        unit="vo2max/day",
        as_of=None,
    )
