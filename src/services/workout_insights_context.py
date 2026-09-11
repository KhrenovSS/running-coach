# Контекст сессии для разбора (Workout-insights session context) — вынос из
# services/workout_insights.py (#329, 11.09.2026): что окружает тренировку — план дня
# (`_plan_for_session`, линкует Recommendation ↔ факт), краткая история и даты для
# week_structure/detraining, RPE-история, max_hr пользователя, и ярлык «план — назначение,
# факт — интенсивность» (`apply_type_resolution`, 04.09.2026). Чистая математика метрик —
# в workout_insights.compute_workout_metrics. (Session surroundings + plan-aware relabel.)

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from src.coach.config import RPE_HISTORY_DAYS
from src.coach.util import effective_training_type
from src.config import settings
from src.config.constants import DETRAINING_LOOKBACK_DAYS
from src.models import TrainingSession, User
from src.services.repositories import FeedbackRepository
from src.utils.logger import get_logger

logger = get_logger("services.workout_insights")


def _session_day(session: TrainingSession):
    """Локальная дата сессии для недельных правил (local session date)."""
    if session.begin_ts is None:
        return None
    from src.utils.timeutils import session_local_dt
    return session_local_dt(session.begin_ts, session, None).date()


def _history_briefs(user_id: int, session: TrainingSession, *,
                    db: Session, days: int = 15) -> list[dict]:
    """Краткая история за окно до сессии — вход week_structure/detraining (M4.1/M4.3).
    (Compact session history for the weekly-structure and detraining blocks.)"""
    if session.begin_ts is None:
        return []
    since = session.begin_ts - timedelta(days=days)
    rows = db.query(TrainingSession).filter(
        TrainingSession.user_id == user_id,
        TrainingSession.begin_ts >= since,
        TrainingSession.begin_ts <= session.begin_ts,
    ).all()
    return [{"date": _session_day(r), "type": effective_training_type(r),
             "km": r.total_distance_km, "avg_hr": r.avg_heart_rate} for r in rows]


def _session_dates(user_id: int, session: TrainingSession, *, db: Session,
                   days: int = DETRAINING_LOOKBACK_DAYS) -> list[dict]:
    """Даты тренировок за окно до сессии — вход detraining (#289): пауза и возврат ищутся
    в 90 днях, а не в 15-дневных briefs. Лёгкая выборка: только begin_ts.
    (Session dates over the detraining lookback — pause/return detection.)"""
    if session.begin_ts is None:
        return []
    since = session.begin_ts - timedelta(days=days)
    rows = db.query(TrainingSession.begin_ts, TrainingSession.user_id, TrainingSession.id).filter(
        TrainingSession.user_id == user_id,
        TrainingSession.begin_ts >= since,
        TrainingSession.begin_ts <= session.begin_ts,
    ).all()
    from src.utils.timeutils import session_local_dt
    return [{"date": session_local_dt(r.begin_ts, session, None).date()} for r in rows]


def apply_type_resolution(user_id: int, session: TrainingSession, *, db: Session,
                          plan: dict | None = None, max_hr: int | None = None,
                          lthr: int | None = None) -> tuple[str, str, str | None]:
    """Ярлык «план — назначение, факт — интенсивность» (04.09.2026): пишет training_type/
    training_type_source от сырого training_type_auto; ручной override не трогает.
    Возврат (type, source, plan_type). Идемпотентно. (Apply the plan-aware label.)"""
    from src.analysis.type_resolution import resolve_training_type
    from src.config.constants import TYPE_SOURCE_MANUAL

    if session.training_type is None and session.training_type_auto is None:
        return session.training_type, session.training_type_source, (plan or {}).get("type")
    if session.training_type_auto is None:
        session.training_type_auto = session.training_type      # legacy-строка до миграции
    if session.training_type_override:
        if session.training_type_source != TYPE_SOURCE_MANUAL:
            session.training_type_source = TYPE_SOURCE_MANUAL
            db.commit()
        return session.training_type_override, TYPE_SOURCE_MANUAL, (plan or {}).get("type")
    if plan is None:
        plan = _plan_for_session(user_id, session, db=db)
    if max_hr is None:
        max_hr = _user_max_hr(user_id, db=db)
    if lthr is None:
        from src.services.repositories import latest_lthr
        lthr = latest_lthr(user_id, db=db)
    new_type, source = resolve_training_type(
        session.training_type_auto, (plan or {}).get("type"),
        avg_hr=session.avg_heart_rate, max_hr=max_hr, lthr=lthr,
        duration_min=session.duration_minutes,
        plan_duration_min=(plan or {}).get("duration_min"))
    if new_type != session.training_type or source != session.training_type_source:
        logger.info("Relabel session=%s: %s → %s (%s, plan=%s)", session.id,
                    session.training_type, new_type, source, (plan or {}).get("type"))
        session.training_type = new_type
        session.training_type_source = source
        db.commit()
    return new_type, source, (plan or {}).get("type")


def _user_max_hr(user_id: int, *, db: Session) -> int:
    user = db.query(User).filter(User.id == user_id).first()
    return (user.max_hr if user and user.max_hr else settings.default_max_hr)


def _plan_for_session(user_id: int, session: TrainingSession, *,
                      db: Session) -> dict | None:
    """Назначение на локальную дату сессии — вход plan_vs_actual (M2.2).

    Заодно линкует Recommendation с тренировкой (linked_session_id — колонка
    задумана как связь «план ↔ факт», до M2.2 не писалась никогда).
    """
    from src.models import Recommendation
    from src.utils.timeutils import session_local_dt

    if session.begin_ts is None:
        return None
    user = db.query(User).filter(User.id == user_id).first()
    day = session_local_dt(session.begin_ts, session, user).date()
    from src.config.constants import RECOMMENDATION_STATUS_SUPERSEDED

    # Погашенные перепланированием строки не линкуем к факту (02.09.2026)
    rec = db.query(Recommendation).filter(
        Recommendation.user_id == user_id,
        Recommendation.for_date == day,
        Recommendation.status != RECOMMENDATION_STATUS_SUPERSEDED,
    ).order_by(Recommendation.id.desc()).first()
    if rec is None:
        return None
    if rec.linked_session_id is None:
        rec.linked_session_id = session.id
        db.commit()
    target, volume = rec.target_json or {}, rec.volume_json or {}
    return {
        "type": rec.workout_type,
        "max_zone": target.get("max_zone"),
        "pace_min_km": target.get("pace_min_km"),
        "duration_min": volume.get("duration_min"),
        "distance_km": volume.get("distance_km"),
        "for_date": rec.for_date.isoformat(),
        "source": rec.source, "clamped": rec.clamped,
    }


def _rpe_history(user_id: int, session: TrainingSession, *,
                 db: Session) -> dict | None:
    """RPE сессии + оценки того же типа за окно — вход для rpe_block (M1.8)."""
    rpe = FeedbackRepository.rating_for_session(session.id, db=db)
    if rpe is None:
        return None
    ttype = effective_training_type(session)
    rows = FeedbackRepository.ratings_with_sessions(
        user_id, days=RPE_HISTORY_DAYS, db=db)
    peers = [r["rating"] for r in rows
             if r.get("rating") is not None and r["session_id"] != session.id
             and (r.get("training_type_override") or r.get("training_type")) == ttype]
    return {"rpe": rpe, "peers": peers}
