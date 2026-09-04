# Детерминированное планирование недели (Weekly planning math) — решения 29.08.2026
#
# «Осознанность» тренера — это числа, посчитанные здесь, а не интуиция LLM:
# целевой объём недели (прогрессия ≤10%, мезоцикл 3:1), потолки качества,
# сверка план-vs-факт прошедшей недели, подтверждение плана утренним вердиктом.
# (Deterministic weekly targets/mesocycle/review; the LLM never computes volumes.)

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from src.analysis.session_metrics import FLAG_LONG_RUN_SHARE
from src.coach.config import (
    DETRAINING_PEAK_WEEKS,
    DETRAINING_RETURN_MIN_DAYS_OFF,
    DETRAINING_RETURN_VOLUME_PCT,
    LONG_RUN_SHARE_LOOKBACK_DAYS,
    UNAVAILABLE_RATIONALE,
    CYCLE_3_1,
    INTERVAL_MAX_KM,
    INTERVAL_MAX_PCT_WEEK,
    LOAD_PROGRESSION,
    LONG_RUN_MAX_MIN,
    LONG_RUN_MAX_PCT_WEEK,
    PLAN_QUALITY_DAYS_MAX,
    PLAN_RUN_DAYS_CAP,
    PLAN_RUN_DAYS_FLOOR,
    PLAN_RUN_DAYS_STEP,
    THRESHOLD_MAX_KM,
    THRESHOLD_MAX_PCT_WEEK,
)
from src.coach.contracts import AthleteState, Prescription, WorkoutProposal
from src.coach.planning_window import local_week_volumes, plan_window, week_done
from src.coach.prescriber import finalize, save_prescription
from src.coach.turn_context import is_athlete_unavailable, unchanged_today
from src.coach.util import effective_training_type
from src.config.constants import RECOMMENDATION_STATUS_SUPERSEDED
from src.services.repositories_insights import InsightRepository
from src.models import Recommendation, TrainingSession, User, UserModel
from src.services.repositories import TrainingRepository
from src.utils.logger import get_logger
from src.coach.render_week import plan_change_line
from src.utils.timeutils import WEEKDAYS_RU_SHORT, user_now

logger = get_logger("coach.planning")

# Статусы строк недельного плана (статус-машина на существующей колонке):
# planned (вс-план) → confirmed (утро подтвердило) / adjusted (заменили);
# superseded — будущая строка прежнего плана, погашенная перепланированием (02.09.2026).
PLAN_STATUSES = ("planned", "confirmed", "adjusted")
# Типы, которые enforce_run_days НЕ убирает (качество и длительная — каркас недели)
_KEEP_TYPES = ("long", "tempo", "interval", "race")

_MESO_LEN = CYCLE_3_1["build_weeks"] + CYCLE_3_1["deload_week"]  # 4


def availability(user_id: int, *, db: Session) -> dict:
    """Окно доступности подопечного (#294): {"weekdays": [0..6] | None} из params_json.week_plan.
    None/пусто — бегать можно в любой день. (Persisted weekday availability.)"""
    meta = _week_plan_meta(user_id, db=db)
    return {"weekdays": (meta.get("availability") or {}).get("weekdays")}


def set_availability(user_id: int, *, db: Session, weekdays: list[int] | None) -> dict:
    """Записать дни недели, когда подопечный может бегать (merge-паттерн advance_mesocycle).
    Пустой список/None — снять ограничение. Возврат — сохранённое окно."""
    um = db.query(UserModel).filter(UserModel.user_id == user_id).first()
    if um is None:
        um = UserModel(user_id=user_id, params_json={})
        db.add(um)
    params = dict(um.params_json or {})
    meta = dict(params.get("week_plan") or {})
    days = sorted({d for d in (weekdays or []) if 0 <= d <= 6})
    meta["availability"] = {"weekdays": days or None,
                            "updated_at": datetime.now(timezone.utc).isoformat()}
    params["week_plan"] = meta
    um.params_json = params
    db.commit()
    logger.info("Availability set for user=%s: weekdays=%s", user_id, days or "any")
    return {"weekdays": days or None}


def unavailable_dates(user_id: int, *, db: Session, week_start: date) -> list[date]:
    """Даты недели week_start, отменённые подопечным (rest с маркером) — план их не трогает."""
    rows = db.query(Recommendation).filter(
        Recommendation.user_id == user_id,
        Recommendation.for_date >= week_start,
        Recommendation.for_date <= week_start + timedelta(days=6),
        Recommendation.status != RECOMMENDATION_STATUS_SUPERSEDED,
    ).order_by(Recommendation.id.asc()).all()
    latest = {r.for_date: r for r in rows}
    return sorted(d for d, r in latest.items() if is_athlete_unavailable(r))


def _last_long_run_km(user_id: int, *, db: Session, since: date) -> float | None:
    """Самая длинная тренировка (км) с даты since (last long run distance)."""
    row = db.query(TrainingSession).filter(
        TrainingSession.user_id == user_id,
        TrainingSession.begin_ts >= datetime.combine(since, datetime.min.time(),
                                                     tzinfo=timezone.utc),
    ).order_by(TrainingSession.total_distance_km.desc()).first()
    return float(row.total_distance_km) if row and row.total_distance_km else None


def _days_off(user_id: int, *, db: Session, today: date) -> int | None:
    """Дней без бега до today (None — тренировок не было вовсе)."""
    from src.utils.timeutils import session_local_dt
    row = db.query(TrainingSession).filter(TrainingSession.user_id == user_id).order_by(
        TrainingSession.begin_ts.desc()).first()
    if row is None or row.begin_ts is None:
        return None
    user = db.query(User).filter(User.id == user_id).first()
    return (today - session_local_dt(row.begin_ts, row, user).date()).days


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _week_plan_meta(user_id: int, *, db: Session) -> dict:
    um = db.query(UserModel).filter(UserModel.user_id == user_id).first()
    if um and um.params_json:
        return um.params_json.get("week_plan") or {}
    return {}


def week_targets(user_id: int, *, db: Session, today: date | None = None) -> dict:
    """Числа планируемой недели — LLM получает их как факты.

    Вс вечером → следующая неделя целиком (plan_scope="week"); /plan среди недели →
    ОСТАТОК текущей (plan_scope="rest_of_week", #293): полные недельные числа плюс блок
    remaining_* с вычетом уже сделанного и окно days_ahead_allowed. today — DI для тестов.
    """
    user = db.query(User).filter(User.id == user_id).first()
    today = today or user_now(user).date()
    done = week_done(user_id, db=db, week_start=_monday_of(today), today=today)
    week_start, first_offset, last_offset = plan_window(today, done["trained_today"])
    if week_start != _monday_of(today):
        # Воскресенье: планируем следующую неделю — сделанного в ней ещё нет
        done = {"km": 0.0, "runs": 0, "quality_runs": 0, "trained_today": False}

    # #220: локальные полные недели (не UTC-корзины); при планировании следующей недели
    # текущая (уже завершённая к вс) — тоже «прошлая»
    weeks = local_week_volumes(user_id, db=db, today=week_start + timedelta(days=6), weeks=4)
    # prev — прошлые недели С пробежками (пустые недели прогрессию не задают, как и раньше)
    prev = [w for w in weeks if w["week_start"] < week_start and w["session_count"] > 0]
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
    run_days_max = run_days_cap([w.get("session_count", 0) for w in prev])
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

    # #294: окно доступности — дни недели из params_json + даты, отменённые подопечным
    avail = availability(user_id, db=db)
    blocked_dates = unavailable_dates(user_id, db=db, week_start=week_start)
    days_allowed = [
        d for d in range(first_offset, last_offset + 1)
        if (today + timedelta(days=d)) not in blocked_dates
        and (not avail["weekdays"] or (today + timedelta(days=d)).weekday() in avail["weekdays"])
    ]

    # P0 #289: длительная не растёт, если на прошлой неделе её доля превысила потолок
    # (long-run share exceeded last week → hold the long run at its last size)
    long_run_km_max = round(target_km * LONG_RUN_MAX_PCT_WEEK, 1)
    long_run_hold = False
    if InsightRepository.recent_flag(user_id, FLAG_LONG_RUN_SHARE, db=db,
                                     days=LONG_RUN_SHARE_LOOKBACK_DAYS):
        last_long = _last_long_run_km(user_id, db=db, since=week_start - timedelta(days=7))
        if last_long:
            long_run_km_max = round(min(long_run_km_max, last_long), 1)
            long_run_hold = True
    # P0 #289: возврат после паузы ≥ DETRAINING_RETURN_MIN_DAYS_OFF (2 недели) — объём ≤ 65%
    # пика (гайд 61), без качественных; паузы 6–13 дней закрывает правило 14 safety
    # (detraining return → volume ceiling, no quality)
    detraining_return = False
    hard_days_max = PLAN_QUALITY_DAYS_MAX
    days_off = _days_off(user_id, db=db, today=today)
    if days_off is not None and days_off >= DETRAINING_RETURN_MIN_DAYS_OFF:
        peak = max([w["total_km"] for w in local_week_volumes(
            user_id, db=db, today=today, weeks=DETRAINING_PEAK_WEEKS)] or [0.0])
        if peak > 0:
            target_km = round(min(target_km, peak * DETRAINING_RETURN_VOLUME_PCT), 1)
            detraining_return = True
            hard_days_max = 0

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
        "long_run_km_max": long_run_km_max,
        "long_run_hold": long_run_hold,             # #289: доля длительной превышена — не растим
        "long_run_min_max": LONG_RUN_MAX_MIN,
        "hard_days_max": hard_days_max,
        "detraining_return": detraining_return,     # #289: возврат после паузы — объём ≤ 65% пика
        "days_off": days_off,
        # Беговых дней ≤ и дней полного отдыха ≥ (решение владельца 02.09.2026)
        "run_days_max": run_days_max,
        "rest_days_min": 7 - run_days_max,
        # Остаток недели (#293): что уже сделано и что осталось распределить
        "plan_scope": "week" if first_offset == 1 and last_offset == 7 else "rest_of_week",
        # #294: окно доступности — дни недели подопечного и отменённые им даты вычитаются
        "days_ahead_allowed": days_allowed,
        "availability": {"weekdays": avail["weekdays"],
                         "weekday_names": [WEEKDAYS_RU_SHORT[d] for d in avail["weekdays"]]
                         if avail["weekdays"] else None,
                         "unavailable_dates": [d.isoformat() for d in blocked_dates]},
        "done_km": done["km"], "done_runs": done["runs"],
        "done_quality": done["quality_runs"],
        "remaining_km": round(max(0.0, target_km - done["km"]), 1),
        # #294: не больше доступных дней окна планирования
        "remaining_run_days_max": min(max(0, run_days_max - done["runs"]), len(days_allowed)),
        "remaining_hard_days_max": max(0, hard_days_max - done["quality_runs"]),
    }


def run_days_cap(session_counts: list[int]) -> int:
    """Потолок беговых дней недели: max пробежек за прошлые недели + STEP,
    в границах [FLOOR, CAP]; без истории — FLOOR (adaptive run-day cap).
    """
    recent_max = max(session_counts) if session_counts else 0
    return max(PLAN_RUN_DAYS_FLOOR, min(PLAN_RUN_DAYS_CAP, recent_max + PLAN_RUN_DAYS_STEP))


def enforce_run_days(items: list[WorkoutProposal],
                     run_days_max: int) -> tuple[list[WorkoutProposal], int]:
    """Урезать план до run_days_max дней: убираем самые короткие лёгкие/восстановительные,
    каркас (длительная, качественные) держим. Возврат — (items, сколько убрано).
    (Deterministic run-day cap: drop the shortest easy days first.)
    """
    if len(items) <= run_days_max:
        return items, 0
    droppable = sorted((it for it in items if it.workout_type not in _KEEP_TYPES),
                       key=lambda it: (it.duration_min or 0.0, it.for_days_ahead))
    to_drop = set()
    for it in droppable:
        if len(items) - len(to_drop) <= run_days_max:
            break
        to_drop.add(id(it))
    kept = [it for it in items if id(it) not in to_drop]
    if len(kept) > run_days_max:
        logger.warning("Run-day cap %s unreachable: %s non-droppable days",
                       run_days_max, len(kept))
    return kept, len(items) - len(kept)


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


def cancel_days(days_ahead: list[int], user_id: int, state: AthleteState, *,
                db: Session, now: datetime) -> str:
    """Снять назначения на дни, когда подопечный не сможет бегать (cancel planned days).

    На каждую дату: прежние строки без факта → superseded, новая строка rest
    (status 'adjusted' — осознанная замена плана, как в утреннем вердикте).
    Возврат — строки «Изменил план на Вс 06.09: 🛌 Отдых (было: …)» по одной на дату,
    детерминированные, не проза LLM. (Deterministic plan-change lines.)
    """
    today = now.date()
    days = sorted(set(days_ahead))
    dates = [today + timedelta(days=d) for d in days]
    old = latest_rows_for_dates(user_id, db=db, dates=dates)
    n = supersede_rows_for_dates(user_id, db=db, dates=dates)
    lines: list[str] = []
    for d, when in zip(days, dates):
        # Маркер «не сможет бегать» — в proposal_json.rationale; по нему чат/утро на этот
        # день назначение не дают (is_athlete_unavailable, blocked_by_unavailable).
        rest = finalize(WorkoutProposal(workout_type="rest", target_zone=1, for_days_ahead=d,
                                        rationale=[UNAVAILABLE_RATIONALE]),
                        state, db=db, persist=False, source="llm", now=now)
        save_prescription(rest, state, db=db, status="adjusted")
        lines.append(plan_change_line(when, rest, old.get(when)))
    logger.info("Cancelled %d planned rows for user=%s, rest on %s", n, user_id, dates)
    return "\n".join(lines)


def blocked_by_unavailable(user_id: int, *, db: Session, when: date) -> str | None:
    """День отменён подопечным («не смогу бегать») → строка-отказ для текста, иначе None.

    Гвард детерминированный: LLM-предложение тренировки на такой день отбрасывается
    (инцидент 04.09.2026: чат назначил пробежку на отменённую пятницу).
    (Athlete cancelled the day → refusal line; the proposal is dropped by the caller.)
    """
    row = latest_rows_for_dates(user_id, db=db, dates=[when]).get(when)
    if row is None or not is_athlete_unavailable(row):
        return None
    label = f"{WEEKDAYS_RU_SHORT[when.weekday()]} {when:%d.%m}"
    return (f"На {label} ты говорил, что бегать не сможешь — назначение не ставлю. "
            f"Если планы изменились, напиши «в этот день смогу побегать» или /plan.")


def reopen_days(days_ahead: list[int], user_id: int, *, db: Session, now: datetime) -> str:
    """Подопечный снова может бегать в эти дни → гасим строки отдыха с маркером
    (обратный путь к cancel_days). Возврат — строка для текста ('' — гасить было нечего)."""
    today = now.date()
    dates = [today + timedelta(days=d) for d in sorted(set(days_ahead))]
    rows = latest_rows_for_dates(user_id, db=db, dates=dates)
    reopened = [d for d in dates if d in rows and is_athlete_unavailable(rows[d])]
    if not reopened:
        return ""
    for d in reopened:
        rows[d].status = RECOMMENDATION_STATUS_SUPERSEDED
    db.commit()
    logger.info("Reopened %d cancelled days for user=%s: %s", len(reopened), user_id, reopened)
    labels = ", ".join(f"{WEEKDAYS_RU_SHORT[d.weekday()]} {d:%d.%m}" for d in reopened)
    return f"Снял отдых: {labels} — день снова свободен для назначения."


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
