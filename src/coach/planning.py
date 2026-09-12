# Детерминированное планирование недели (Weekly planning math) — решения 29.08.2026
#
# «Осознанность» тренера — это числа, посчитанные здесь, а не интуиция LLM:
# целевой объём недели (прогрессия ≤10%, мезоцикл 3:1), потолки качества,
# сверка план-vs-факт прошедшей недели, подтверждение плана утренним вердиктом.
# (Deterministic weekly targets/mesocycle/review; the LLM never computes volumes.)
# #329 (11.09.2026): доступность/отмена дней — planning_availability.py, строки плана и утреннее
# подтверждение — planning_rows.py; здесь — числа недели, потолок беговых дней, мезоцикл.

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from src.analysis.session_metrics import FLAG_LONG_RUN_SHARE
from src.coach.config import (
    DETRAINING_PEAK_WEEKS,
    DETRAINING_RETURN_MIN_DAYS_OFF,
    DETRAINING_RETURN_VOLUME_PCT,
    LONG_RUN_SHARE_LOOKBACK_DAYS,
    CYCLE_3_1,
    INTERVAL_MAX_KM,
    INTERVAL_MAX_PCT_WEEK,
    LOAD_PROGRESSION,
    LONG_RUN_MAX_MIN,
    PLAN_RUN_DAYS_CAP,
    PLAN_RUN_DAYS_FLOOR,
    PLAN_RUN_DAYS_STEP,
    THRESHOLD_MAX_KM,
    THRESHOLD_MAX_PCT_WEEK,
    long_run_max_pct,
)
from src.coach.contracts import WorkoutProposal
from src.coach.illness import context_block, illness_state, paused_dates
# #329 (11.09.2026): доступность/отмена дней и строки плана вынесены в соседние модули;
# имена реэкспортируются — вызовы `planning.cancel_days(...)` и т.п. остаются валидными.
# (Split-out modules re-exported for backward compatibility.)
from src.coach.planning_availability import (  # noqa: F401 — реэкспорт
    _week_plan_meta,
    availability,
    blocked_by_unavailable,
    cancel_days,
    reopen_days,
    set_availability,
    unavailable_dates,
)
from src.coach.planning_rows import (  # noqa: F401 — реэкспорт
    PLAN_STATUSES,
    _monday_of,
    _proposal_from_row,
    confirm_or_adjust_morning,
    latest_rows_for_dates,
    supersede_future_rows,
    supersede_rows_for_dates,
    week_plan_review,
)
from src.coach.planning_safety import long_run_min_hint
from src.coach.planning_window import local_week_volumes, plan_window, week_done
from src.coach.quality_ladder import quality_ladder
from src.coach import lthr_field
from src.coach.training_status import compute_status
from src.services.repositories_insights import InsightRepository
from src.models import TrainingSession, User, UserModel
from src.utils.logger import get_logger
from src.utils.timeutils import WEEKDAYS_RU_SHORT, user_now

logger = get_logger("coach.planning")

# Типы, которые enforce_run_days НЕ убирает (качество и длительная — каркас недели)
_KEEP_TYPES = ("long", "tempo", "interval", "race")

_MESO_LEN = CYCLE_3_1["build_weeks"] + CYCLE_3_1["deload_week"]  # 4


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


def week_targets(user_id: int, *, db: Session, today: date | None = None,
                 now: datetime | None = None) -> dict:
    """Числа планируемой недели — LLM получает их как факты.

    Вс вечером → следующая неделя целиком (plan_scope="week"); /plan среди недели →
    ОСТАТОК текущей (plan_scope="rest_of_week", #293): полные недельные числа плюс блок
    remaining_* с вычетом уже сделанного и окно days_ahead_allowed. today — DI для тестов;
    now — локальное время подопечного (#319: после PLAN_TODAY_CUTOFF_HOUR день 0 не планируем;
    без now отсечка не применяется).
    """
    user = db.query(User).filter(User.id == user_id).first()
    today = today or (now or user_now(user)).date()
    done = week_done(user_id, db=db, week_start=_monday_of(today), today=today)
    hour = now.hour if now is not None and now.date() == today else None
    week_start, first_offset, last_offset = plan_window(today, done["trained_today"], hour)
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
    # #322: дни болезни/паузы после неё закрыты для плана (гайд 50)
    ill = illness_state(user_id, db=db)
    blocked_dates = sorted(set(blocked_dates) | set(paused_dates(
        ill, today, today + timedelta(days=first_offset), today + timedelta(days=last_offset))))
    days_allowed = [
        d for d in range(first_offset, last_offset + 1)
        if (today + timedelta(days=d)) not in blocked_dates
        and (not avail["weekdays"] or (today + timedelta(days=d)).weekday() in avail["weekdays"])
    ]

    # P0 #289: длительная не растёт, если на прошлой неделе её доля превысила потолок
    # (long-run share exceeded last week → hold the long run at its last size)
    # Доля длительной: 40 % при малом объёме/частоте, 30 % при большом (07.09.2026)
    long_run_pct = long_run_max_pct(target_km, run_days_max)
    long_run_km_max = round(target_km * long_run_pct, 1)
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
    # 12.09.2026: статус подопечного и лестница качественных дней — из данных, не константой
    # (athlete status + tolerance ladder replace the fixed quality-days constant)
    status = compute_status(user_id, db=db, today=today)
    ladder = quality_ladder(user_id, db=db, today=today, phase=status["phase"],
                            active_injury=status["active_injury"], run_days_max=run_days_max,
                            week_start=week_start)
    hard_days_max = ladder["level"]
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
        "long_run_max_pct": long_run_pct,
        "long_run_hold": long_run_hold,             # #289: доля длительной превышена — не растим
        "long_run_min_max": LONG_RUN_MAX_MIN,
        # #318: ориентир минут длительной под потолок км — LLM планирует минутами
        "long_run_min_hint": long_run_min_hint(user_id, user, long_run_km_max, db=db),
        "hard_days_max": hard_days_max,
        # 12.09.2026: фаза returning/stabilizing/stable и почему качественных дней столько
        "athlete_status": status["phase"],
        "quality_ladder": ladder,
        # M3.2 (12.09.2026): нужен полевой тест ПАНО — stable и нет свежего полевого значения
        "lthr_test_due": lthr_field.is_due(user_id, db=db, phase=status["phase"]),
        "detraining_return": detraining_return,     # #289: возврат после паузы — объём ≤ 65% пика
        "illness": context_block(ill, today),       # #322: болезнь/пауза — что знает система
        "days_off": days_off,
        # Беговых дней ≤ и дней полного отдыха ≥ (решение владельца 02.09.2026)
        "run_days_max": run_days_max,
        "rest_days_min": 7 - run_days_max,
        # Частота прошлых недель — при плоском объёме беговой день не добавляем (07.09.2026)
        "prev_week_runs_max": max([w.get("session_count", 0) for w in prev] or [0]),
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
    каркас (длительная, качественные, дни с сегментами — ускорения) держим.
    Возврат — (items, сколько убрано). (Deterministic run-day cap: drop the shortest plain
    easy days first; structured days are skeleton, 07.09.2026.)
    """
    if len(items) <= run_days_max:
        return items, 0
    droppable = sorted((it for it in items
                        if it.workout_type not in _KEEP_TYPES and not it.segments),
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
