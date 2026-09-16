# Потолки объёма в ad-hoc пути (чат / утро) — day caps, #338–#340, 16.09.2026
#
# Инцидент 13.09.2026: подопечный тремя репликами поднял длительную 50 → 72 мин / 10 км, коуч
# согласился — safety (`clamp`) режет объём только при боли/сне < 5 ч, а потолки прогрессии
# (`week_targets`, `cap_long_run`, `cap_week_volume`) звались только из /plan. Здесь те же чистые
# кэпы применяются к ОДНОМУ назначению симметрично двухпроходной схеме weekly_plan (finalize →
# кэп → повторный finalize урезанного): Prescription по-прежнему рождается только в clamp.
# Требование владельца: уменьшить/перенести/отменить подопечный может, «предложить больше» —
# оценивается кодом, для своих предложений коуча и просьб подопечного одинаково.
# (Deterministic day-level volume caps for chat/morning; two-pass finalize, pure cap functions.)

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from src.coach import planning
from src.coach.config import (
    LONG_RUN_CAP_TOLERANCE_KM,
    LONG_RUN_MIN_MINUTES,
    PLAN_EASY_MIN_MINUTES,
    WEEK_VOLUME_TOLERANCE_PCT,
)
from src.coach.contracts import AthleteState, Prescription, SafetyVerdict, WorkoutProposal
from src.coach.planning_safety import apply_safety_to_targets, cap_long_run
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
                 "detraining_return")


def _week_bounds(targets: dict[str, Any]) -> tuple[date, date] | None:
    ws = targets.get("week_start")
    if not ws:
        return None
    start = date.fromisoformat(ws)
    return start, start + timedelta(days=6)


def planned_km_other_days(user_id: int, *, db: Session, week_start: date, today: date,
                          exclude_dates: tuple[date, ...] = ()) -> float:
    """Километры действующих назначений недели на ДРУГИЕ дни (≥ сегодня, ≠ exclude_dates):
    последняя не-superseded строка на дату, отдых и отменённые подопечным дни — 0; оценка км —
    `predicted_json.distance_km` (ориентир карточки), иначе `volume_json.distance_km`.
    (Sum of planned km on other days of the week; deterministic.)"""
    lo = max(today, week_start)
    rows = db.query(Recommendation).filter(
        Recommendation.user_id == user_id,
        Recommendation.for_date >= lo,
        Recommendation.for_date <= week_start + timedelta(days=6),
        Recommendation.status != RECOMMENDATION_STATUS_SUPERSEDED,
    ).order_by(Recommendation.id.asc()).all()
    latest = {r.for_date: r for r in rows}
    total = 0.0
    for d, r in latest.items():
        if d in exclude_dates or r.workout_type == "rest" or is_athlete_unavailable(r):
            continue
        km = ((r.predicted_json or {}).get("distance_km")
              or (r.volume_json or {}).get("distance_km") or 0.0)
        total += float(km)
    return round(total, 1)


def day_targets(user_id: int, verdict: SafetyVerdict, *, db: Session, now: datetime) -> dict:
    """Числа недели для одного хода: `week_targets` + согласование с вердиктом safety
    (`apply_safety_to_targets`) + `planned_km_remaining` (уже назначено на оставшиеся дни, включая
    сегодня). Один вызов на ход. (Week numbers for a chat/morning turn.)"""
    targets = planning.week_targets(user_id, db=db, now=now)
    targets = apply_safety_to_targets(targets, verdict)
    bounds = _week_bounds(targets)
    if bounds is not None:
        targets["planned_km_remaining"] = planned_km_other_days(
            user_id, db=db, week_start=bounds[0], today=now.date())
    return targets


def context_block(targets: dict[str, Any]) -> dict:
    """Компактный срез потолков недели для today-контекста LLM (#339): что уже сделано, что
    осталось, потолок одной пробежки, сколько км ещё не распределено. Числа — факты, не советы."""
    out = {k: targets[k] for k in _CONTEXT_KEYS if targets.get(k) is not None}
    base = targets.get("remaining_km") if targets.get("plan_scope") == "rest_of_week" \
        else targets.get("target_km")
    planned = targets.get("planned_km_remaining")
    if base is not None:
        out["planned_km_remaining"] = planned or 0.0
        out["unallocated_km"] = round(max(0.0, base * (1 + WEEK_VOLUME_TOLERANCE_PCT)
                                          - (planned or 0.0)), 1)
        out["rule"] = ("одна пробежка не длиннее long_run_km_max; день можно увеличить не больше, "
                       "чем на unallocated_km сверх его плана — иначе код урежет")
    return out


def cap_day_volume(proposal: WorkoutProposal, prescription: Prescription,
                   targets: dict[str, Any], *,
                   other_planned_km: float = 0.0) -> tuple[WorkoutProposal | None, str | None]:
    """Потолок объёма ДНЯ от остатка недели — чистая функция.

    Допуск дня = (remaining_km | target_km) × (1 + WEEK_VOLUME_TOLERANCE_PCT) − км, уже назначенные
    на другие дни недели. Оценка км — `prescription.predicted.distance_km` (тот же ориентир, что в
    карточке), иначе `proposal.distance_km`. Выше допуска (+ LONG_RUN_CAP_TOLERANCE_KM) → минуты
    вниз пропорционально (не ниже PLAN_EASY_MIN_MINUTES), структура — через shrink_proposal.
    Дата вне недели targets (вс вечером про пн) → не применяем. Возврат (копия | None, заметка | None).
    (Day-volume cap from the week's remaining km; pure.)"""
    if proposal.workout_type == "rest" or not proposal.duration_min:
        return None, None
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
    allowance = base * (1 + WEEK_VOLUME_TOLERANCE_PCT) - (other_planned_km or 0.0)
    if est <= allowance + LONG_RUN_CAP_TOLERANCE_KM:
        return None, None
    duration = float(proposal.duration_min)
    new_min = max(PLAN_EASY_MIN_MINUTES, math.floor(duration * max(allowance, 0.0) / est))
    if new_min >= duration:
        return None, None
    reason = f"на неделе осталось {base:.1f} км"
    if other_planned_km:
        reason += f", из них {other_planned_km:.1f} уже назначено на другие дни"
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
    """finalize → потолок одной пробежки → потолок объёма дня → повторный finalize урезанного.

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
    capped, note = cap_long_run(proposal, prescription, targets)
    if capped is not None:
        logger.info("Day cap (single run) user=%s: %s→%s min", state.user_id,
                    proposal.duration_min, capped.duration_min)
        proposal = capped
        prescription = finalize(proposal, state, db=db, persist=False, source=source, now=now,
                                long_min_minutes=long_min)
        notes.append(note)
    bounds = _week_bounds(targets)
    other = 0.0
    if bounds is not None:
        other = planned_km_other_days(state.user_id, db=db, week_start=bounds[0], today=now.date(),
                                      exclude_dates=(prescription.when, *exclude_dates))
    capped, note = cap_day_volume(proposal, prescription, targets, other_planned_km=other)
    if capped is not None:
        logger.info("Day cap (week volume) user=%s: %s→%s min (other planned %.1f km)",
                    state.user_id, proposal.duration_min, capped.duration_min, other)
        prescription = finalize(capped, state, db=db, persist=False, source=source, now=now,
                                long_min_minutes=long_min)
        notes.append(note)
    return prescription, notes
