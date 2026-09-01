# Детерминированное планирование недели (Weekly planning math) — решения 29.08.2026
#
# «Осознанность» тренера — это числа, посчитанные здесь, а не интуиция LLM:
# целевой объём недели (прогрессия ≤10%, мезоцикл 3:1), потолки качества,
# сверка план-vs-факт прошедшей недели, подтверждение плана утренним вердиктом.
# (Deterministic weekly targets/mesocycle/review; the LLM never computes volumes.)

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from src.coach.config import (
    CYCLE_3_1,
    INTERVAL_MAX_KM,
    INTERVAL_MAX_PCT_WEEK,
    LOAD_PROGRESSION,
    LONG_RUN_MAX_MIN,
    LONG_RUN_MAX_PCT_WEEK,
    PLAN_QUALITY_DAYS_MAX,
    THRESHOLD_MAX_KM,
    THRESHOLD_MAX_PCT_WEEK,
)
from src.coach.contracts import AthleteState, Prescription, WorkoutProposal
from src.coach.prescriber import finalize, save_prescription
from src.coach.turn_context import unchanged_today
from src.models import Recommendation, TrainingSession, User, UserModel
from src.services.repositories import TrainingRepository
from src.utils.logger import get_logger
from src.utils.timeutils import user_now

logger = get_logger("coach.planning")

# Статусы строк недельного плана (статус-машина на существующей колонке):
# planned (вс-план) → confirmed (утро подтвердило) / adjusted (заменили).
PLAN_STATUSES = ("planned", "confirmed", "adjusted")

_MESO_LEN = CYCLE_3_1["build_weeks"] + CYCLE_3_1["deload_week"]  # 4


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _week_plan_meta(user_id: int, *, db: Session) -> dict:
    um = db.query(UserModel).filter(UserModel.user_id == user_id).first()
    if um and um.params_json:
        return um.params_json.get("week_plan") or {}
    return {}


def week_targets(user_id: int, *, db: Session) -> dict:
    """Числа следующей планируемой недели — LLM получает их как факты.

    Планируемая неделя — та, что содержит завтрашний локальный день
    (вс вечером → следующая неделя; /plan среди недели → остаток текущей).
    """
    user = db.query(User).filter(User.id == user_id).first()
    today = user_now(user).date()
    week_start = _monday_of(today + timedelta(days=1))

    weeks = TrainingRepository.weekly_volume(user_id, weeks=4, db=db)
    prev = [w for w in weeks if w["week_start"] < week_start]
    meta = _week_plan_meta(user_id, db=db)

    # Счётчик мезоцикла: replan той же недели НЕ двигает счётчик (идемпотентно)
    if meta.get("week_start") == week_start.isoformat():
        meso_week = meta.get("mesocycle_week", 1)
    elif meta.get("mesocycle_week"):
        meso_week = meta["mesocycle_week"] % _MESO_LEN + 1
    else:
        meso_week = 1
    phase = "deload" if meso_week == _MESO_LEN else "build"

    low_history = len(prev) < 2
    prev_km = prev[-1]["total_km"] if prev else 0.0
    last_build_km = meta.get("last_build_km") or prev_km
    if low_history or prev_km <= 0:
        # Консервативный fallback: без прогрессии, от наблюдаемого
        base = prev_km or last_build_km or 15.0
        target_km = round(base, 1)
    elif phase == "deload":
        # Разгрузка от пика цикла (guide 60: 75%)
        target_km = round(max(prev_km, last_build_km)
                          * CYCLE_3_1["deload_volume_pct"], 1)
    elif meta.get("phase") == "deload":
        # Первая build-неделя нового цикла: от последней build-недели, не от deload
        target_km = round(last_build_km, 1)
    else:
        pct = LOAD_PROGRESSION["max_weekly_increase_pct"] / 100.0
        target_km = round(prev_km * (1 + pct), 1)

    return {
        "week_start": week_start.isoformat(),
        "mesocycle_week": meso_week,
        "mesocycle_length": _MESO_LEN,
        "phase": phase,
        "prev_week_km": round(prev_km, 1),
        "target_km": target_km,
        "low_history": low_history,
        # Потолки качества/длительной — от целевого объёма (guides 44/45)
        "quality_z4_km_max": round(min(target_km * INTERVAL_MAX_PCT_WEEK,
                                       INTERVAL_MAX_KM), 1),
        "quality_z3_km_max": round(min(target_km * THRESHOLD_MAX_PCT_WEEK,
                                       THRESHOLD_MAX_KM), 1),
        "long_run_km_max": round(target_km * LONG_RUN_MAX_PCT_WEEK, 1),
        "long_run_min_max": LONG_RUN_MAX_MIN,
        "hard_days_max": PLAN_QUALITY_DAYS_MAX,
    }


def advance_mesocycle(user_id: int, *, db: Session, targets: dict) -> None:
    """Записать мету планируемой недели (merge-паттерн params_json).

    last_build_km обновляется только build-фазой — база для post-deload недели.
    """
    um = db.query(UserModel).filter(UserModel.user_id == user_id).first()
    if um is None:
        um = UserModel(user_id=user_id, params_json={})
        db.add(um)
    params = dict(um.params_json or {})
    prev_meta = params.get("week_plan") or {}
    last_build = (targets["target_km"] if targets["phase"] == "build"
                  else prev_meta.get("last_build_km") or targets["prev_week_km"])
    params["week_plan"] = {
        "week_start": targets["week_start"],
        "mesocycle_week": targets["mesocycle_week"],
        "phase": targets["phase"],
        "target_km": targets["target_km"],
        "last_build_km": round(last_build, 1),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    um.params_json = params
    db.commit()


def week_plan_review(user_id: int, *, db: Session) -> dict | None:
    """Сверка текущей недели: план (строки planned/confirmed/adjusted) vs факт.

    Факт — через linked_session_id (проставляет план-vs-факт при разборе).
    None — плановых строк на неделе не было (фича только включилась).
    """
    user = db.query(User).filter(User.id == user_id).first()
    today = user_now(user).date()
    week_start = _monday_of(today)
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
        elif d < today:
            missed += 1
        days.append({
            "date": d.isoformat(), "planned_type": r.workout_type,
            "status": r.status,
            "actual_type": session.training_type if session else None,
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
                              now: datetime) -> tuple[Prescription, str] | None:
    """Утро при наличии плана дня: подтвердить или осознанно заменить.

    None — плановой строки на сегодня нет (оркестратор идёт старым путём).
    Возврат (prescription, "confirmed"|"adjusted"):
    - confirmed — re-clamp плана по СЕГОДНЯШНЕМУ состоянию ничего не урезал и
      LLM не меняла → UPDATE status той же строки, без дубля;
    - adjusted — LLM меняет план или safety урезал → новая строка 'adjusted'.
    """
    plan_row = db.query(Recommendation).filter(
        Recommendation.user_id == user_id,
        Recommendation.for_date == now.date(),
        Recommendation.status.in_(PLAN_STATUSES),
    ).order_by(Recommendation.id.desc()).first()
    if plan_row is None:
        return None
    chosen = proposal if proposal is not None else _proposal_from_row(plan_row)
    prescription = finalize(chosen, state, db=db, persist=False,
                            source="llm" if proposal is not None else "plan",
                            now=now)
    if unchanged_today(prescription, user_id, db=db):
        if plan_row.status != "confirmed":
            plan_row.status = "confirmed"
            db.commit()
        return prescription, "confirmed"
    save_prescription(prescription, state, db=db, status="adjusted")
    return prescription, "adjusted"
