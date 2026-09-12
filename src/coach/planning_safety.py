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
    HARD_SHARE_MIN_MINUTES_7D,
    HARD_TYPES,
    INTENSITY_ONLY_SAFETY_RULES,
    LONG_RUN_CAP_TOLERANCE_KM,
    LONG_RUN_MAX_PCT_WEEK,
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


def hard_share_by_day(zone_rows: list[tuple[datetime, dict]], *, now: datetime,
                      horizon_days: int = 7, lookback_days: int = 7,
                      min_minutes: float = HARD_SHARE_MIN_MINUTES_7D) -> dict[int, float | None]:
    """Доля времени Z3+ «за последние 7 дней» на каждый день вперёд (правило 16, #315).

    Окно сдвигается по дню плана: тренировки старше 7 дней от этого дня выходят из окна,
    будущие дни неизвестны (не считаем — консервативно: доля падает только за счёт ухода
    старых). Меньше min_minutes в окне → None (правило молчит, как и сегодня).
    (Projected 7-day Z3+ share per day ahead; the window slides with the plan day.)
    """
    def _aware(t: datetime) -> datetime:
        return t if t.tzinfo is not None else t.replace(tzinfo=timezone.utc)
    rows = [(_aware(t), z) for t, z in zone_rows]
    out: dict[int, float | None] = {}
    for d in range(0, horizon_days + 1):
        since = now + timedelta(days=d - lookback_days)
        total = hard = 0.0
        for t, z in rows:
            if t >= since:
                total += sum(z.values())
                hard += z.get("z3", 0.0) + z.get("z4", 0.0) + z.get("z5", 0.0)
        out[d] = round(hard / total, 2) if total >= min_minutes else None
    return out


def project_state(state: AthleteState, counts: dict[int, int], day: int,
                  hard_shares: dict[int, float | None] | None = None) -> AthleteState:
    """Снимок состояния на день `day`: прогнозный счётчик правила 17, доля Z3+ правила 16
    (#315, окно сдвигается по дню) и сдвиг дня для правила 21 (болезнь/пауза); остальные
    сигналы — сегодняшние, консервативно.
    (State copy with the projected rule-16/17 signals and the plan-day offset.)"""
    signals = {**(state.signals or {}), "day_offset": day}   # #322: правило 21 знает день плана
    if day in counts:
        signals["easy_too_hard_7d"] = counts[day]
    if hard_shares is not None and day in hard_shares:
        signals["hard_share_7d"] = hard_shares[day]
    return replace(state, signals=signals)


def quality_reopens_at(state: AthleteState, counts: dict[int, int], *, now: datetime,
                       days: list[int],
                       hard_shares: dict[int, float | None] | None = None) -> int | None:
    """Первый день окна (сдвиг от сегодня), когда вердикт уже допускает качественный день:
    правила 16/17 по прогнозным сигналам, `earliest_next_hard` — не позже конца того дня.
    None — интенсив закрыт на всё окно (остальные правила прогнозу не поддаются).
    (First day ahead on which a hard session is allowed; None = blocked all window.)"""
    for d in sorted(days):
        v = evaluate_safety(project_state(state, counts, d, hard_shares), now=now)
        if quality_blocked(v):
            continue
        day_end = datetime.combine(now.date() + timedelta(days=d + 1), time(0),
                                   tzinfo=now.tzinfo or timezone.utc)
        if v.earliest_next_hard is not None and v.earliest_next_hard > day_end:
            continue
        return d
    return None


def volume_hold(verdict: SafetyVerdict) -> bool:
    """Держать ли объём недели плоским при закрытом интенсиве (решение владельца 12.09.2026):
    да — если сработало хоть одно правило усталости/здоровья или список пустой (консервативно);
    нет — если интенсив закрыт только правилами распределения нагрузки (INTENSITY_ONLY_SAFETY_RULES).
    (Hold weekly volume flat unless the block is intensity-distribution only.)"""
    if not verdict.triggered:
        return True
    return any(t not in INTENSITY_ONLY_SAFETY_RULES for t in verdict.triggered)


def apply_safety_to_targets(targets: dict[str, Any], verdict: SafetyVerdict, *,
                            quality_from_days_ahead: int | None = None) -> dict[str, Any]:
    """Согласовать потолки недели с вердиктом safety; без блокировки — без изменений.

    Интенсив закрыт на всё окно → потолки качества = 0. `quality_from_days_ahead` = N
    (прогноз `quality_reopens_at`, 07.09.2026) → качественный день остаётся, но только с
    for_days_ahead ≥ N (`quality_allowed_from_days_ahead`; раньше — clamp по прогнозному
    состоянию режет сам). Объём и частота: плоские (цель = прошлая неделя) только при усталости/
    здоровье (`volume_hold`); при блоке лишь по распределению нагрузки рост +10 % сохраняется
    (`volume_growth_kept`, решение владельца 12.09.2026 — отменяет «всегда плоский» от 06.09).
    Чистая функция; `quality_blocked_by_safety` — первая причина вердикта для шапки/промпта.
    (Pure: reconcile weekly caps with the verdict.)
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
    # 06.09.2026: в safety-разгрузку объём недели плоский — цель = прошлая неделя, потолок длительной
    # пересчитан. 12.09.2026: только при усталости/здоровье; блок по распределению нагрузки
    # (правила 16/17 и родня) объём не держит — быстрые лёгкие лечатся темпом, не километрами.
    # (Hold volume flat only for fatigue/health blocks; intensity-only blocks keep the +10 % growth.)
    prev_km = out.get("prev_week_km") or 0.0
    if prev_km > 0 and (out.get("target_km") or 0.0) > prev_km and not volume_hold(verdict):
        out["volume_growth_kept"] = "intensity_only"
    elif prev_km > 0 and (out.get("target_km") or 0.0) > prev_km:
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
    predict_volume); потолок км — `long_run_km_max` (30/40 % недели, при long_run_hold — прошлая
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
    # Доля — из targets (30 % / 40 %, 12.09.2026), не захардкоженное «30 %»
    pct_reason = (f"потолок {(targets.get('long_run_max_pct') or LONG_RUN_MAX_PCT_WEEK) * 100:.0f} % "
                  "недельного объёма")
    if cap_km and km_est and km_est > cap_km + LONG_RUN_CAP_TOLERANCE_KM:
        new_min = math.floor(duration * cap_km / km_est)
        reason = pct_reason
    if cap_km and proposal.distance_km and proposal.distance_km > cap_km + LONG_RUN_CAP_TOLERANCE_KM:
        new_km = cap_km
        reason = reason or pct_reason
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
