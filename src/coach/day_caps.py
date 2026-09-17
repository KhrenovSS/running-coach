# Потолки объёма в ad-hoc пути (чат / утро) — day caps, #338–#340, 16.09.2026
#
# Инцидент 13.09.2026: подопечный тремя репликами поднял длительную 50 → 72 мин / 10 км, коуч
# согласился — safety (`clamp`) режет объём только при боли/сне < 5 ч, а потолки прогрессии
# (`week_targets`, `cap_long_run`, `cap_week_volume`) звались только из /plan. Здесь те же чистые
# кэпы применяются к ОДНОМУ назначению симметрично двухпроходной схеме weekly_plan (finalize →
# кэп → повторный finalize урезанного): Prescription по-прежнему рождается только в clamp.
# Требование владельца: уменьшить/перенести/отменить подопечный может, «предложить больше» —
# оценивается кодом, для своих предложений коуча и просьб подопечного одинаково.
# 17.09.2026 — та же симметрия для ЧАСТОТЫ: лишний беговой день сверх `run_days_max` (плановый отдых
# строкой не хранится — `weekly_plan._clean_days`) не отклоняется, а понижается до лёгкого
# ≤ PLAN_EASY_MIN_MINUTES с пометкой (`cap_run_days`, мягкий кэп — решение владельца).
# (Deterministic day-level volume and frequency caps for chat/morning; two-pass finalize.)

from __future__ import annotations

import math
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from src.coach import planning
from src.coach.config import (
    DAY_CAP_MIN_CUT_KM,
    DAY_CAP_MIN_CUT_MIN,
    DAY_VOLUME_TOLERANCE_RELAXED_PCT,
    LONG_RUN_MIN_MINUTES,
    PLAN_EASY_MIN_MINUTES,
    WEEK_VOLUME_TOLERANCE_PCT,
)
from src.coach.contracts import AthleteState, Prescription, SafetyVerdict, WorkoutProposal
from src.coach.planning_rows import PLAN_STATUSES
from src.coach.planning_safety import (
    _UNCAPPED_TYPES,
    apply_safety_to_targets,
    cap_long_run,
    fatigue_signals,
)
from src.coach.prescriber import finalize
from src.coach.segment_trim import shrink_proposal
from src.coach.turn_context import is_athlete_unavailable
from src.config.constants import RECOMMENDATION_STATUS_SUPERSEDED
from src.models import Recommendation
from src.utils.logger import get_logger

logger = get_logger("coach.day_caps")

# Ключи week_targets, которые модель видит в чате/утре (#339): только объём и потолки —
# без лестницы качества и мезоцикла (они — про /plan). (Compact slice for the chat context.)
_CONTEXT_KEYS = ("plan_scope", "week_start", "prev_week_km", "target_km", "done_km", "remaining_km",
                 "long_run_km_max", "long_run_max_pct", "long_run_min_hint", "long_run_min_max",
                 "long_run_hold", "hard_days_max", "volume_held_by_safety", "volume_growth_kept",
                 "detraining_return",
                 # 17.09.2026: частота — беговых дней в неделе не больше run_days_max
                 "run_days_max", "rest_days_min", "done_runs", "run_days_used",
                 # 17.09.2026 (#243 ч.1): фаза подготовки к старту и потолок объёма
                 "goal", "capped_by_ceiling",
                 # 17.09.2026: допуск объёма дня по состоянию (15 % без стойких сигналов усталости, иначе 5 %)
                 "day_volume_tolerance_pct", "day_volume_tolerance_reason")


def _week_bounds(targets: dict[str, Any]) -> tuple[date, date] | None:
    ws = targets.get("week_start")
    if not ws:
        return None
    start = date.fromisoformat(ws)
    return start, start + timedelta(days=6)


def _other_day_rows(user_id: int, *, db: Session, week_start: date, today: date,
                    exclude_dates: tuple[date, ...] = ()) -> list[Recommendation]:
    """Действующие БЕГОВЫЕ строки недели на ДРУГИЕ дни (≥ сегодня, ≠ exclude_dates): последняя
    не-superseded строка на дату; отдых и отменённые подопечным дни исключены. Один запрос на ход.
    (Latest active run rows of the week on other days.)"""
    lo = max(today, week_start)
    rows = db.query(Recommendation).filter(
        Recommendation.user_id == user_id,
        Recommendation.for_date >= lo,
        Recommendation.for_date <= week_start + timedelta(days=6),
        Recommendation.status != RECOMMENDATION_STATUS_SUPERSEDED,
    ).order_by(Recommendation.id.asc()).all()
    latest = {r.for_date: r for r in rows}
    return [r for d, r in latest.items()
            if d not in exclude_dates and r.workout_type != "rest" and not is_athlete_unavailable(r)]


def _rows_km(rows: list[Recommendation]) -> float:
    """Километры строк: `predicted_json.distance_km` (ориентир карточки), иначе `volume_json`."""
    total = 0.0
    for r in rows:
        km = ((r.predicted_json or {}).get("distance_km")
              or (r.volume_json or {}).get("distance_km") or 0.0)
        total += float(km)
    return round(total, 1)


def planned_km_other_days(user_id: int, *, db: Session, week_start: date, today: date,
                          exclude_dates: tuple[date, ...] = ()) -> float:
    """Километры действующих назначений недели на ДРУГИЕ дни (см. `_other_day_rows`).
    (Sum of planned km on other days of the week; deterministic.)"""
    return _rows_km(_other_day_rows(user_id, db=db, week_start=week_start, today=today,
                                    exclude_dates=exclude_dates))


def run_days_used(targets: dict[str, Any], planned_dates: set[date], *,
                  when: date | None = None) -> int:
    """Беговые дни недели, уже занятые фактом или действующим планом: множество дат (день с
    пробежкой и живой строкой не удваивается), без целевого дня `when`. Чистая функция.
    (Run days already taken this week: session dates ∪ planned dates, minus the target day.)"""
    done = {date.fromisoformat(d) for d in (targets.get("done_dates") or [])}
    taken = done | set(planned_dates)
    if when is not None:
        taken.discard(when)
    return len(taken)


def day_targets(user_id: int, verdict: SafetyVerdict, *, db: Session, now: datetime) -> dict:
    """Числа недели для одного хода: `week_targets` + согласование с вердиктом safety
    (`apply_safety_to_targets`) + `planned_km_remaining` (уже назначено на оставшиеся дни, включая
    сегодня). Один вызов на ход. (Week numbers for a chat/morning turn.)"""
    targets = planning.week_targets(user_id, db=db, now=now)
    targets = apply_safety_to_targets(targets, verdict)
    # 17.09.2026 (решение владельца): допуск объёма дня — по состоянию. Стойкие сигналы усталости/здоровья
    # (HRV, recovery %, ACWR/ATI, боль, болезнь, detraining, монотонность, нет данных) → строго 5 %; чистый
    # вердикт или только правила распределения/разовые сигналы → 15 %. /plan остаётся на 5 %.
    # (State-dependent day tolerance: fatigue → strict, clean → relaxed.)
    fatigue = fatigue_signals(verdict)
    targets["day_volume_tolerance_pct"] = (WEEK_VOLUME_TOLERANCE_PCT if fatigue
                                           else DAY_VOLUME_TOLERANCE_RELAXED_PCT)
    targets["day_volume_tolerance_reason"] = fatigue[:3]
    bounds = _week_bounds(targets)
    if bounds is not None:
        rows = _other_day_rows(user_id, db=db, week_start=bounds[0], today=now.date())
        targets["planned_km_remaining"] = _rows_km(rows)
        # 17.09.2026: сколько беговых дней недели уже занято (факт ∪ план) — для контекста модели
        targets["run_days_used"] = run_days_used(targets, {r.for_date for r in rows})
    return targets


def context_block(targets: dict[str, Any]) -> dict:
    """Компактный срез потолков недели для today-контекста LLM (#339): что уже сделано, что
    осталось, потолок одной пробежки, сколько км ещё не распределено. Числа — факты, не советы."""
    out = {k: targets[k] for k in _CONTEXT_KEYS if targets.get(k) is not None}
    base = targets.get("remaining_km") if targets.get("plan_scope") == "rest_of_week" \
        else targets.get("target_km")
    planned = targets.get("planned_km_remaining")
    tol = targets.get("day_volume_tolerance_pct", WEEK_VOLUME_TOLERANCE_PCT)
    if base is not None:
        out["planned_km_remaining"] = planned or 0.0
        out["unallocated_km"] = round(max(0.0, base * (1 + tol) - (planned or 0.0)), 1)
        out["rule"] = ("одна пробежка не длиннее long_run_km_max; день можно увеличить не больше, "
                       "чем на unallocated_km сверх его плана — иначе код урежет; unallocated_km уже "
                       "включает допуск по состоянию (day_volume_tolerance_pct: без стойких сигналов "
                       "усталости шире, при них строгий)")
    if targets.get("run_days_max") is not None:
        out["frequency_rule"] = ("беговых дней в неделе не больше run_days_max (run_days_used уже занято "
                                 "фактом и планом), день полного отдыха обязателен; лишний беговой день "
                                 "код понизит до лёгких 30 мин")
    return out


def cap_run_days(proposal: WorkoutProposal, prescription: Prescription, targets: dict[str, Any], *,
                 run_days_used: int, plan_day: bool) -> tuple[WorkoutProposal | None, str | None]:
    """Мягкий кэп ЧАСТОТЫ — чистая функция (решение владельца 17.09.2026).

    Беговые дни недели исчерпаны (`run_days_used >= run_days_max`) и день не из плана недели
    (`plan_day=False`: плановые дни — каркас, их защищает enforce_run_days; ad-hoc строка `proposed`
    день не освобождает) → предложение не отклоняется, а понижается до лёгкого: `easy`, зона ≤ 2,
    без темпа и структуры, не дольше PLAN_EASY_MIN_MINUTES. Уже такое → только заметка.
    Дата вне недели targets → не применяем. Возврат (копия | None, заметка | None).
    (Soft frequency cap: extra run day beyond run_days_max → short easy run, never a hard one.)"""
    if proposal.workout_type in _UNCAPPED_TYPES or plan_day:
        return None, None       # старт (race) — не «лишний беговой день», кэп частоты его не трогает
    bounds = _week_bounds(targets)
    if bounds is None or not (bounds[0] <= prescription.when <= bounds[1]):
        return None, None
    cap = targets.get("run_days_max")
    if not cap or run_days_used < cap:
        return None, None
    reason = f"беговых дней на неделе уже {run_days_used} из {cap}, день полного отдыха обязателен"
    duration = float(proposal.duration_min) if proposal.duration_min else None
    new_min = min(duration, float(PLAN_EASY_MIN_MINUTES)) if duration else float(PLAN_EASY_MIN_MINUTES)
    already_easy = (proposal.workout_type in ("easy", "recovery") and proposal.target_zone <= 2
                    and not proposal.segments and proposal.target_pace_min_km is None
                    and duration is not None and duration <= PLAN_EASY_MIN_MINUTES)
    if already_easy:
        return None, f"⚠️ Беговые дни недели исчерпаны ({run_days_used} из {cap}): лишний день — только лёгкий и короткий."
    scale = (new_min / duration) if duration else None
    distance = (round(proposal.distance_km * scale, 1)
                if proposal.distance_km and scale is not None else None)
    trail = f"урезано кодом: лишний беговой день → лёгкие {new_min:.0f} мин ({reason})"
    capped = replace(proposal, workout_type="easy", target_zone=min(proposal.target_zone, 2),
                     duration_min=int(new_min), distance_km=distance, target_pace_min_km=None,
                     segments=[], structure=None,
                     rationale=[*proposal.rationale, trail], code_trimmed=True)
    was = f"{proposal.workout_type} {duration:.0f} мин" if duration else proposal.workout_type
    note = (f"⚠️ Беговые дни недели исчерпаны ({run_days_used} из {cap}) — вместо {was} оставил "
            f"лёгкие {new_min:.0f} мин; день полного отдыха обязателен.")
    return capped, note


def cap_day_volume(proposal: WorkoutProposal, prescription: Prescription,
                   targets: dict[str, Any], *,
                   other_planned_km: float = 0.0) -> tuple[WorkoutProposal | None, str | None]:
    """Потолок объёма ДНЯ от остатка недели — чистая функция.

    Допуск дня = (remaining_km | target_km) × (1 + tol) − км, уже назначенные на другие дни недели;
    tol — `targets["day_volume_tolerance_pct"]` (по состоянию, 17.09.2026), без ключа —
    WEEK_VOLUME_TOLERANCE_PCT. Оценка км — `prescription.predicted.distance_km` (тот же ориентир, что в
    карточке), иначе `proposal.distance_km`. Выше допуска на DAY_CAP_MIN_CUT_KM и больше → минуты вниз
    пропорционально (не ниже PLAN_EASY_MIN_MINUTES), структура — через shrink_proposal; гистерезис —
    эффективный срез (после пола) меньше DAY_CAP_MIN_CUT_MIN не делаем (шум, не перегруз).
    Дата вне недели targets (вс вечером про пн) → не применяем. Возврат (копия | None, заметка | None).
    (Day-volume cap from the week's remaining km; pure.)"""
    if proposal.workout_type in _UNCAPPED_TYPES or not proposal.duration_min:
        return None, None       # отдых нечего резать; старт объёмом не режется (как в /plan)
    bounds = _week_bounds(targets)
    if bounds is None or not (bounds[0] <= prescription.when <= bounds[1]):
        return None, None
    base = targets.get("remaining_km") if targets.get("plan_scope") == "rest_of_week" \
        else targets.get("target_km")
    if base is None or base <= 0:
        return None, None
    predicted = prescription.predicted or {}
    est = predicted.get("distance_km") or proposal.distance_km
    if not est:
        return None, None
    tol = targets.get("day_volume_tolerance_pct", WEEK_VOLUME_TOLERANCE_PCT)
    allowance = base * (1 + tol) - (other_planned_km or 0.0)
    if est <= allowance + DAY_CAP_MIN_CUT_KM:
        return None, None
    duration = float(proposal.duration_min)
    new_min = max(PLAN_EASY_MIN_MINUTES, math.floor(duration * max(allowance, 0.0) / est))
    if new_min >= duration or duration - new_min < DAY_CAP_MIN_CUT_MIN:
        return None, None       # гистерезис: срез короче DAY_CAP_MIN_CUT_MIN — шум, не перегруз
    reason = f"на неделе осталось {base:.1f} км"
    if other_planned_km:
        reason += f", из них {other_planned_km:.1f} уже назначено на другие дни"
    reason += f"; допуск {tol * 100:.0f} %"
    fatigue = targets.get("day_volume_tolerance_reason") or []
    if fatigue:
        reason += f" — усталость ({', '.join(fatigue)})"
    trail = f"урезано кодом: {duration:.0f} → {new_min:.0f} мин (объём недели: {reason})"
    capped, seg_note = shrink_proposal(proposal, new_min, trail=trail,
                                       pace_min_km=predicted.get("pace_min_km"))
    final_min = float(capped.duration_min or new_min)
    est_km = round(est * final_min / duration, 1)
    note = f"⚠️ Объём урезан до {final_min:.0f} мин (≈{est_km:.1f} км): {reason}"
    if seg_note:
        note += f"; {seg_note}"
    return capped, note + "."


def finalize_with_caps(proposal: WorkoutProposal | None, state: AthleteState, *, db: Session,
                       now: datetime, source: str, targets: dict[str, Any] | None,
                       exclude_dates: tuple[date, ...] = ()) -> tuple[Prescription, list[str]]:
    """finalize → кэп частоты → потолок одной пробежки → потолок объёма дня → повторный finalize.

    targets=None → обычный finalize (без потолков; тесты/деградация). Порог «длительная короче
    N мин = лёгкая» — общий с /plan (`min(60, long_run_min_hint)`, #342). Возврат — (Prescription,
    заметки для строки над карточкой). Prescription рождается только в clamp (инвариант §1.2).
    (Two-pass finalize with the same caps /plan uses; notes for the day card.)"""
    long_min = LONG_RUN_MIN_MINUTES
    if targets and targets.get("long_run_min_hint"):
        long_min = min(LONG_RUN_MIN_MINUTES, targets["long_run_min_hint"])
    prescription = finalize(proposal, state, db=db, persist=False, source=source, now=now,
                            long_min_minutes=long_min)
    notes: list[str] = []
    if proposal is None or targets is None or prescription.workout_type == "rest":
        return prescription, notes
    bounds = _week_bounds(targets)
    other_rows: list[Recommendation] = []
    if bounds is not None:
        other_rows = _other_day_rows(state.user_id, db=db, week_start=bounds[0], today=now.date(),
                                     exclude_dates=(prescription.when, *exclude_dates))
    # 17.09.2026: частота — день из плана недели (planned/confirmed/adjusted) кэп не трогает
    row = planning.latest_rows_for_dates(state.user_id, db=db, dates=[prescription.when]).get(prescription.when)
    plan_day = (row is not None and row.status in PLAN_STATUSES and row.workout_type != "rest"
                and not is_athlete_unavailable(row))
    used = run_days_used(targets, {r.for_date for r in other_rows}, when=prescription.when)
    capped, note = cap_run_days(proposal, prescription, targets, run_days_used=used, plan_day=plan_day)
    if capped is not None:
        logger.info("Day cap (run days) user=%s: %s %s→easy %s min (used %s)", state.user_id,
                    proposal.workout_type, proposal.duration_min, capped.duration_min, used)
        proposal = capped
        prescription = finalize(proposal, state, db=db, persist=False, source=source, now=now,
                                long_min_minutes=long_min)
    if note:
        notes.append(note)
    capped, note = cap_long_run(proposal, prescription, targets)
    if capped is not None:
        logger.info("Day cap (single run) user=%s: %s→%s min", state.user_id,
                    proposal.duration_min, capped.duration_min)
        proposal = capped
        prescription = finalize(proposal, state, db=db, persist=False, source=source, now=now,
                                long_min_minutes=long_min)
        notes.append(note)
    other = _rows_km(other_rows)
    capped, note = cap_day_volume(proposal, prescription, targets, other_planned_km=other)
    if capped is not None:
        logger.info("Day cap (week volume) user=%s: %s→%s min (other planned %.1f km)",
                    state.user_id, proposal.duration_min, capped.duration_min, other)
        prescription = finalize(capped, state, db=db, persist=False, source=source, now=now,
                                long_min_minutes=long_min)
        notes.append(note)
    return prescription, notes
