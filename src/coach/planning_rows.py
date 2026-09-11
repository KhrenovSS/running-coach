# Строки недельного плана в recommendations (Weekly-plan rows) — вынос из coach/planning.py
# (#329, 11.09.2026). Статус-машина на существующей колонке: planned (вс-план) → confirmed
# (утро подтвердило) / adjusted (заменили); superseded — будущая строка прежнего плана,
# погашенная перепланированием (02.09.2026). Здесь — гашение строк, выбор последней действующей
# строки на дату, сверка план-vs-факт недели и утреннее подтверждение плана дня.
# (Supersede/select rows, week plan-vs-actual review, morning confirm-or-adjust.)

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from src.coach.contracts import AthleteState, Prescription, WorkoutProposal
from src.coach.prescriber import finalize, save_prescription
from src.coach.turn_context import is_athlete_unavailable, unchanged_today
from src.coach.util import effective_training_type
from src.config.constants import RECOMMENDATION_STATUS_SUPERSEDED
from src.models import Recommendation, TrainingSession, User
from src.utils.logger import get_logger
from src.utils.timeutils import user_now

logger = get_logger("coach.planning")

PLAN_STATUSES = ("planned", "confirmed", "adjusted")


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def supersede_rows_for_dates(user_id: int, *, db: Session, dates: list[date]) -> int:
    """Погасить назначения на КОНКРЕТНЫЕ даты (подопечный не сможет бегать, 03.09.2026).

    Строки без факта (linked_session_id IS NULL) → status='superseded'; возврат — число.
    (Supersede rows for the given dates; rows linked to a real workout stay.)
    """
    if not dates:
        return 0
    n = db.query(Recommendation).filter(
        Recommendation.user_id == user_id,
        Recommendation.for_date.in_(dates),
        Recommendation.status != RECOMMENDATION_STATUS_SUPERSEDED,
        Recommendation.linked_session_id.is_(None),
    ).update({Recommendation.status: RECOMMENDATION_STATUS_SUPERSEDED},
             synchronize_session="fetch")
    db.commit()
    return n


def latest_rows_for_dates(user_id: int, *, db: Session,
                          dates: list[date]) -> dict[date, Recommendation]:
    """Последняя действующая строка recommendations на каждую из дат
    (status != superseded; тот же принцип, что week_view._active_rows).
    (Latest non-superseded row per date.)"""
    if not dates:
        return {}
    rows = db.query(Recommendation).filter(
        Recommendation.user_id == user_id,
        Recommendation.for_date.in_(dates),
        Recommendation.status != RECOMMENDATION_STATUS_SUPERSEDED,
    ).order_by(Recommendation.id.asc()).all()
    return {r.for_date: r for r in rows}


def supersede_future_rows(user_id: int, *, db: Session, from_date: date) -> int:
    """Погасить будущие строки прежнего плана перед записью нового (02.09.2026).

    Строки с for_date >= from_date без факта (linked_session_id IS NULL) →
    status='superseded'; читатели их не видят. Возврат — число строк.
    (Mark future rows of the previous plan superseded; linked rows stay.)
    """
    rows = db.query(Recommendation).filter(
        Recommendation.user_id == user_id,
        Recommendation.for_date >= from_date,
        Recommendation.status != RECOMMENDATION_STATUS_SUPERSEDED,
        Recommendation.linked_session_id.is_(None),
    ).all()
    n = 0
    for r in rows:
        if is_athlete_unavailable(r):
            continue          # #294: отмены подопечного переживают перепланирование
        r.status = RECOMMENDATION_STATUS_SUPERSEDED
        n += 1
    db.commit()
    return int(n or 0)


def week_plan_review(user_id: int, *, db: Session, week_start: date | None = None,
                     include_today: bool = False) -> dict | None:
    """Сверка недели: план (строки planned/confirmed/adjusted) vs факт.

    Факт — через linked_session_id (проставляет план-vs-факт при разборе).
    None — плановых строк на неделе не было (фича только включилась).
    week_start — по умолчанию текущая неделя; include_today — считать сегодняшний
    невыполненный день пропущенным (недельный отчёт вс 19:00 — C8.1).
    """
    user = db.query(User).filter(User.id == user_id).first()
    today = user_now(user).date()
    week_start = week_start or _monday_of(today)
    recs = db.query(Recommendation).filter(
        Recommendation.user_id == user_id,
        Recommendation.for_date >= week_start,
        Recommendation.for_date <= week_start + timedelta(days=6),
        Recommendation.status.in_(PLAN_STATUSES),
    ).order_by(Recommendation.id.asc()).all()
    if not recs:
        return None
    latest = {r.for_date: r for r in recs}
    days, done, missed = [], 0, 0
    for d in sorted(latest):
        r = latest[d]
        session = (db.query(TrainingSession).filter(
            TrainingSession.id == r.linked_session_id).first()
            if r.linked_session_id else None)
        if session is not None:
            done += 1
        elif d < today or (include_today and d == today):
            missed += 1
        days.append({
            "date": d.isoformat(), "planned_type": r.workout_type,
            "status": r.status,
            "actual_type": effective_training_type(session) if session else None,
            "actual_km": session.total_distance_km if session else None,
        })
    return {"week_start": week_start.isoformat(), "days": days,
            "planned": len(days), "done": done, "missed": missed,
            "adjusted": sum(1 for r in latest.values() if r.status == "adjusted")}


def _proposal_from_row(rec: Recommendation) -> WorkoutProposal:
    """Восстановить предложение из плановой строки (для re-clamp утром)."""
    from src.coach.segments import segments_from_target

    target, volume = rec.target_json or {}, rec.volume_json or {}
    return WorkoutProposal(
        workout_type=rec.workout_type,
        target_zone=target.get("max_zone") or 1,
        duration_min=volume.get("duration_min"),
        distance_km=volume.get("distance_km"),
        target_pace_min_km=target.get("pace_min_km"),
        structure=target.get("structure"),
        segments=segments_from_target(target.get("segments")),
        rationale=["план недели"],
    )


def confirm_or_adjust_morning(proposal: WorkoutProposal | None, user_id: int,
                              state: AthleteState, *, db: Session,
                              now: datetime) -> tuple[Prescription, str, Recommendation] | None:
    """Утро при наличии плана дня: подтвердить или осознанно заменить.

    None — плановой строки на сегодня нет (оркестратор идёт старым путём).
    Возврат (prescription, "confirmed"|"adjusted", plan_row) — plan_row нужна строке
    «Изменил план на … (было: …)»:
    - confirmed — re-clamp плана по СЕГОДНЯШНЕМУ состоянию ничего не урезал и
      LLM не меняла → UPDATE status той же строки, без дубля;
    - adjusted — LLM меняет план или safety урезал → новая строка 'adjusted'.
    """
    # #292/#305: план дня — ПОСЛЕДНЯЯ действующая строка на дату (включая proposed из чата),
    # иначе утро подтверждало вытесненную plan-строку, а карточку показывало по новой
    plan_row = db.query(Recommendation).filter(
        Recommendation.user_id == user_id,
        Recommendation.for_date == now.date(),
        Recommendation.status != RECOMMENDATION_STATUS_SUPERSEDED,
    ).order_by(Recommendation.id.desc()).first()
    if plan_row is None or plan_row.status not in PLAN_STATUSES + ("proposed",):
        return None
    chosen = proposal if proposal is not None else _proposal_from_row(plan_row)
    prescription = finalize(chosen, state, db=db, persist=False,
                            source="llm" if proposal is not None else "plan",
                            now=now)
    if unchanged_today(prescription, user_id, db=db):
        if plan_row.status != "confirmed":
            plan_row.status = "confirmed"
            db.commit()
        return prescription, "confirmed", plan_row
    save_prescription(prescription, state, db=db, status="adjusted")
    return prescription, "adjusted", plan_row
