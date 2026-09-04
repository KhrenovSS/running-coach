# Монотонность и страйн нагрузки по Фостеру (Foster training monotony & strain) — P0 #308, 04.09.2026
#
# monotony = средняя дневная нагрузка / SD дневных нагрузок за окно (дни отдыха = 0);
# strain = суммарная нагрузка окна × monotony. Высокая монотонность (> MONOTONY_HIGH) при
# 5+ тренировочных днях — маркер риска болезни/травмы: нужен день отдыха, не интенсив.
# Нагрузка дня — баллы Дэниелса (минуты в зонах × POINTS_PER_MIN) из разборов; без зон — 0.
# (Daily Daniels points → Foster monotony/strain; used by week_report and safety rule 20.)

from __future__ import annotations

from datetime import date, timedelta
from statistics import mean, pstdev

from sqlalchemy.orm import Session

from src.coach.config import MONOTONY_HIGH, MONOTONY_MIN_TRAIN_DAYS, POINTS_PER_MIN


def monotony_from_daily(daily: list[float]) -> dict:
    """Чистый расчёт по списку дневных нагрузок (pure Foster math)."""
    if not daily:
        return {"monotony": None, "strain": None, "trained_days": 0, "total": 0.0}
    total = sum(daily)
    trained = sum(1 for d in daily if d > 0)
    sd = pstdev(daily) if len(daily) > 1 else 0.0
    if total <= 0:
        return {"monotony": None, "strain": None, "trained_days": trained, "total": 0.0}
    monotony = round(mean(daily) / sd, 2) if sd > 0 else None   # SD=0 → все дни равны: не определено
    strain = round(total * monotony, 1) if monotony is not None else None
    return {"monotony": monotony, "strain": strain, "trained_days": trained,
            "total": round(total, 1)}


def daily_load_points(user_id: int, *, db: Session, start: date, days: int,
                      user=None, max_hr=None, lthr=None) -> list[float]:
    """Баллы нагрузки по дням [start, start+days): из зон разборов (fallback — сегменты)."""
    from src.coach.week_report import _bucket_sessions, _insights_by_session, _session_zone_minutes
    from src.models import User
    from src.services.repositories import latest_lthr
    from src.utils.timeutils import session_local_dt

    user = user or db.query(User).filter(User.id == user_id).first()
    max_hr = max_hr or getattr(user, "max_hr", None)
    lthr = lthr if lthr is not None else latest_lthr(user_id, db=db)
    end = start + timedelta(days=days - 1)
    buckets = _bucket_sessions(user_id, db=db, user=user,
                               first_monday=start - timedelta(days=start.weekday()), last_day=end)
    insights = _insights_by_session(user_id, db=db, buckets=buckets)
    daily = [0.0] * days
    for items in buckets.values():
        for s in items:
            d = session_local_dt(s.begin_ts, s, user).date()
            if not start <= d <= end:
                continue
            zm = _session_zone_minutes(s, insights.get(s.id) or {}, max_hr=max_hr, lthr=lthr)
            if zm:
                daily[(d - start).days] += sum(zm[z] * POINTS_PER_MIN.get(z, 0.0) for z in zm)
    return daily


def monotony_window(user_id: int, *, db: Session, today: date, days: int = 7,
                    user=None, max_hr=None, lthr=None) -> dict:
    """Монотонность/страйн за последние `days` дней до today включительно."""
    start = today - timedelta(days=days - 1)
    out = monotony_from_daily(daily_load_points(user_id, db=db, start=start, days=days,
                                                user=user, max_hr=max_hr, lthr=lthr))
    out["high"] = (out["monotony"] is not None and out["monotony"] > MONOTONY_HIGH
                   and out["trained_days"] >= MONOTONY_MIN_TRAIN_DAYS)
    return out
