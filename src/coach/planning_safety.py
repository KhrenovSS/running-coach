# Согласование потолков недели с вердиктом safety (week targets ⟂ safety verdict)
#
# Инцидент 06.09.2026: safety запретил интенсив на неделю (правила 16/17), а week_targets
# всё ещё давал hard_days_max=1 → LLM заложил темповую, clamp вырезал её молча, проза
# осталась про «качественную работу». Потолки должны видеть вердикт ДО вызова LLM.
# (Targets must reflect the verdict before the LLM plans, so prose matches the card.)

from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from src.coach.config import (
    EASY_TOO_HARD_LOOKBACK_DAYS,
    HARD_TYPES,
    LONG_RUN_CAP_TOLERANCE_KM,
    LONG_RUN_MAX_MIN,
    PLAN_EASY_MIN_MINUTES,
    PLAN_RUN_DAYS_FLOOR,
    WEEK_VOLUME_TOLERANCE_PCT,
    long_run_max_pct,
)
from src.coach.contracts import AthleteState, Prescription, SafetyVerdict, WorkoutProposal
from src.coach.rules.p1_safety import evaluate_safety


def quality_blocked(verdict: SafetyVerdict) -> bool:
    """Вердикт не оставил ни одного качественного типа (no hard type is allowed)."""
    if not verdict.allow_training:
        return True
    if not verdict.allowed_types:            # пусто = все разрешены (empty = all allowed)
        return False
    return not (set(HARD_TYPES) & set(verdict.allowed_types))


def easy_too_hard_counts_by_day(flag_times: list[datetime], *, now: datetime,
                                horizon_days: int = 7,
                                lookback_days: int = EASY_TOO_HARD_LOOKBACK_DAYS) -> dict[int, int]:
    """Сколько флагов easy_run_too_hard будет «в окне 7 дней» на каждый день вперёд (0..horizon).

    Правило 17 считает флаги по дате тренировки; план недели строится сегодня, но флаги
    выходят из окна по ходу недели — счётчик прогнозируется детерминированно (07.09.2026:
    план обнулял качество на Чт/Пт, хотя к среде правило уже не сработало бы).
    (Projected 7-day flag count per day ahead.)
    """
    def _aware(t: datetime) -> datetime:
        return t if t.tzinfo is not None else t.replace(tzinfo=timezone.utc)
    times = [_aware(t) for t in flag_times]
    return {d: sum(1 for t in times if t >= now + timedelta(days=d - lookback_days))
            for d in range(0, horizon_days + 1)}


def project_state(state: AthleteState, counts: dict[int, int], day: int) -> AthleteState:
    """Снимок состояния с прогнозным счётчиком правила 17 на день `day` (остальные сигналы —
    сегодняшние, консервативно). (State copy with the projected rule-17 counter.)"""
    if day not in counts:
        return state
    return replace(state, signals={**(state.signals or {}), "easy_too_hard_7d": counts[day]})


def quality_reopens_at(state: AthleteState, counts: dict[int, int], *, now: datetime,
                       days: list[int]) -> int | None:
    """Первый день окна (сдвиг от сегодня), когда вердикт уже допускает качественный день:
    правило 17 по прогнозному счётчику, `earliest_next_hard` — не позже конца того дня.
    None — интенсив закрыт на всё окно (другие правила прогнозу не поддаются).
    (First day ahead on which a hard session is allowed; None = blocked all window.)"""
    for d in sorted(days):
        v = evaluate_safety(project_state(state, counts, d), now=now)
        if quality_blocked(v):
            continue
        day_end = datetime.combine(now.date() + timedelta(days=d + 1), time(0),
                                   tzinfo=now.tzinfo or timezone.utc)
        if v.earliest_next_hard is not None and v.earliest_next_hard > day_end:
            continue
        return d
    return None


def apply_safety_to_targets(targets: dict[str, Any], verdict: SafetyVerdict, *,
                            quality_from_days_ahead: int | None = None) -> dict[str, Any]:
    """Согласовать потолки недели с вердиктом safety; без блокировки — без изменений.

    Интенсив закрыт на всё окно → потолки качества = 0. `quality_from_days_ahead` = N
    (прогноз `quality_reopens_at`, 07.09.2026) → качественный день остаётся, но только с
    for_days_ahead ≥ N (`quality_allowed_from_days_ahead`; раньше — clamp по прогнозному
    состоянию режет сам). В обоих случаях объём плоский и частота прошлой недели (решение
    владельца 06.09.2026 + 07.09.2026). Чистая функция; `quality_blocked_by_safety` — первая
    причина вердикта для шапки/промпта. (Pure: reconcile weekly caps with the verdict.)
    """
    if not quality_blocked(verdict):
        return targets
    out = dict(targets)
    reason = next((r.reason for r in verdict.reasons if r.reason), None)
    out["quality_blocked_by_safety"] = reason or "интенсив закрыт границами безопасности"
    if quality_from_days_ahead is not None:
        out["quality_allowed_from_days_ahead"] = quality_from_days_ahead
    else:
        out["hard_days_max"] = 0
        if "remaining_hard_days_max" in out:
            out["remaining_hard_days_max"] = 0
        out["quality_z3_km_max"] = 0.0
        out["quality_z4_km_max"] = 0.0
    # Решение владельца 06.09.2026: в safety-разгрузку объём недели плоский — цель = прошлая
    # неделя, потолок длительной пересчитан; рост +10 % вернётся, когда интенсив снова открыт
    # (owner decision: hold weekly volume flat while quality is blocked by safety)
    prev_km = out.get("prev_week_km") or 0.0
    if prev_km > 0 and (out.get("target_km") or 0.0) > prev_km:
        out["target_km"] = round(prev_km, 1)
        if "remaining_km" in out and "done_km" in out:
            out["remaining_km"] = round(max(0.0, out["target_km"] - (out["done_km"] or 0.0)), 1)
        out["volume_held_by_safety"] = True
        # Частота растёт вместе с объёмом (07.09.2026): объём плоский → беговых дней не больше,
        # чем в прошлые недели — иначе лёгкие ужимаются до 28 мин ради лишнего дня
        # (flat volume → no extra run day)
        prev_runs = out.get("prev_week_runs_max") or 0
        if prev_runs and out.get("run_days_max"):
            out["run_days_max"] = min(out["run_days_max"], max(PLAN_RUN_DAYS_FLOOR, prev_runs))
            out["rest_days_min"] = 7 - out["run_days_max"]
            if "remaining_run_days_max" in out:
                out["remaining_run_days_max"] = min(
                    max(0, out["run_days_max"] - (out.get("done_runs") or 0)),
                    len(out.get("days_ahead_allowed") or []) or out["run_days_max"])
        if out.get("long_run_km_max"):
            pct = long_run_max_pct(prev_km, out.get("run_days_max"))
            out["long_run_km_max"] = round(min(out["long_run_km_max"], prev_km * pct), 1)
            out["long_run_max_pct"] = pct
    return out


def cap_long_run(proposal: WorkoutProposal, prescription: Prescription,
                 targets: dict[str, Any]) -> tuple[WorkoutProposal | None, str | None]:
    """Потолок длительной — кодом, не промптом (06.09.2026: LLM дал 70 мин ≈ 10 км при
    потолке 8,4 км, а отчёт обещал «без роста длительной»).

    Километры — тот же ориентир, что печатает карточка (`prescription.predicted` из
    predict_volume); потолок км — `long_run_km_max` (30 % недели, при long_run_hold — прошлая
    длительная); минут — `long_run_min_max` (150). Нет оценки темпа → только потолок минут
    (нет данных → не выдумываем). Возврат: (урезанная копия proposal | None, заметка | None).
    (Deterministic long-run cap; pure — returns a trimmed copy or (None, None).)
    """
    if proposal.workout_type != "long" or not proposal.duration_min:
        return None, None
    if proposal.segments:
        # Структурная длительная (прогрессия/блоки): молча резать нельзя — сегменты разойдутся
        # с длительностью; выше потолка — только заметка (structured long run: warn, don't trim)
        km_est = (prescription.predicted or {}).get("distance_km")
        cap_km = targets.get("long_run_km_max")
        if cap_km and km_est and km_est > cap_km + LONG_RUN_CAP_TOLERANCE_KM:
            return None, (f"⚠️ Длительная ≈{km_est:.1f} км выше потолка {cap_km:.1f} км, "
                          "структура задана — проверь вручную.")
        return None, None
    duration = float(proposal.duration_min)
    cap_km = targets.get("long_run_km_max")
    cap_min = targets.get("long_run_min_max")
    km_est = (prescription.predicted or {}).get("distance_km")
    new_min = duration
    new_km = proposal.distance_km
    reason = None
    if cap_km and km_est and km_est > cap_km + LONG_RUN_CAP_TOLERANCE_KM:
        new_min = math.floor(duration * cap_km / km_est)
        reason = "потолок 30 % недельного объёма"
    if cap_km and proposal.distance_km and proposal.distance_km > cap_km + LONG_RUN_CAP_TOLERANCE_KM:
        new_km = cap_km
        reason = reason or "потолок 30 % недельного объёма"
    if cap_min and new_min > cap_min:
        new_min = float(cap_min)
        reason = f"не дольше {cap_min:.0f} мин"
    if new_min >= duration and new_km == proposal.distance_km:
        return None, None
    if targets.get("long_run_hold"):
        reason += ", длительная не растёт после прошлой недели"
    est_km = round(new_min * km_est / duration, 1) if km_est else None
    note = f"⚠️ Длительная урезана до {new_min:.0f} мин"
    if est_km is not None:
        note += f" (≈{est_km:.1f} км)"
    note += f": {reason}."
    # След урезания в proposal_json.rationale — что предлагал LLM (audit trail in rationale)
    trail = f"урезано кодом: {duration:.0f} → {new_min:.0f} мин ({reason})"
    return replace(proposal, duration_min=int(new_min), distance_km=new_km,
                   rationale=[*proposal.rationale, trail], code_trimmed=True), note


_SCALABLE_TYPES = ("easy", "recovery")


def cap_week_volume(items: list[WorkoutProposal], prescriptions: list[Prescription],
                    targets: dict[str, Any]) -> tuple[list[WorkoutProposal] | None, str | None]:
    """Потолок объёма недели — кодом (06.09.2026: цель 27,9 км, сумма карточки ≈ 30).

    Сумма — по `predicted.distance_km` каждого дня (тот же ориентир, что в карточке; день без оценки
    считается 0 и не трогается). Выше `target_km × (1 + WEEK_VOLUME_TOLERANCE_PCT)` → лёгкие/
    восстановительные дни ужимаются пропорционально (floor, не ниже PLAN_EASY_MIN_MINUTES);
    длительная и качественные под своими потолками — не трогаем. Возврат: (новый список items с
    заменёнными днями | None, заметка | None). Для остатка недели цель — `remaining_km`.
    (Deterministic weekly-volume cap: scale easy days down to the target; pure.)
    """
    target = targets.get("remaining_km") if targets.get("plan_scope") == "rest_of_week" \
        else targets.get("target_km")
    if not target or target <= 0 or len(items) != len(prescriptions):
        return None, None
    est = [((p.predicted or {}).get("distance_km") or 0.0) for p in prescriptions]
    total = sum(est)
    if total <= target * (1 + WEEK_VOLUME_TOLERANCE_PCT):
        return None, None
    # Структурные дни (сегменты) фиксированы: масштаб длительности разошёлся бы с сегментами
    # (06.09.2026: 39 мин при сегментах на 42) — ужимаются только ровные лёгкие дни
    scalable = [i for i, it in enumerate(items)
                if it.workout_type in _SCALABLE_TYPES and est[i] > 0 and it.duration_min
                and not it.segments]
    if not scalable:
        return None, None
    fixed = sum(est[i] for i in range(len(items)) if i not in scalable)
    scalable_sum = sum(est[i] for i in scalable)
    k = max(0.0, (target - fixed) / scalable_sum) if scalable_sum > 0 else 1.0
    if k >= 1.0:
        return None, None
    new_items = list(items)
    new_total = fixed
    changed = False
    for i in scalable:
        it = items[i]
        new_min = max(PLAN_EASY_MIN_MINUTES, math.floor(it.duration_min * k))
        if new_min < it.duration_min:
            trail = f"урезано кодом: {it.duration_min:.0f} → {new_min:.0f} мин (объём недели)"
            new_items[i] = replace(it, duration_min=int(new_min),
                                   distance_km=(round(it.distance_km * new_min / it.duration_min, 1)
                                                if it.distance_km else None),
                                   rationale=[*it.rationale, trail])
            changed = True
        new_total += est[i] * new_min / it.duration_min
    if not changed:
        return None, None
    prev_km = targets.get("prev_week_km")
    tail = (f": объём в safety-разгрузку не растёт (прошлая неделя {prev_km:.1f} км)"
            if targets.get("volume_held_by_safety") and prev_km
            else (f": рост не больше +10 % к прошлой неделе ({prev_km:.1f} км)" if prev_km
                  else ": цель недели"))
    note = f"⚠️ Объём недели урезан до ~{new_total:.0f} км{tail}."
    return new_items, note


def long_run_min_hint(user_id: int, user: Any, km_max: float | None, *, db: Session) -> int | None:
    """Ориентир длительной в минутах для LLM (#318): потолок км × темп на потолке Z2 по истории,
    не дольше LONG_RUN_MAX_MIN. Только подсказка в week_targets — потолок по-прежнему режет
    `cap_long_run`; нет оценки темпа → None (не выдумываем). (Long-run minutes hint from the
    km cap and historical pace at the Z2 ceiling; advisory only, the code cap still applies.)
    """
    from src.analysis.hr_zones import zone_ceiling_hr
    from src.coach.prescriber import user_max_hr
    from src.services.repositories import latest_lthr
    from src.services.workout_insights import expected_pace_at_hr

    if not km_max:
        return None
    ceiling = zone_ceiling_hr(2, user_max_hr(user), latest_lthr(user_id, db=db))
    if ceiling is None:
        return None
    estimate = expected_pace_at_hr(user_id, ceiling, db=db, workout_type="long", degraded_ok=True)
    if not estimate or not estimate.get("pace_min_km"):
        return None
    return int(min(LONG_RUN_MAX_MIN, round(km_max * float(estimate["pace_min_km"]))))
