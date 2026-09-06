# Согласование потолков недели с вердиктом safety (week targets ⟂ safety verdict)
#
# Инцидент 06.09.2026: safety запретил интенсив на неделю (правила 16/17), а week_targets
# всё ещё давал hard_days_max=1 → LLM заложил темповую, clamp вырезал её молча, проза
# осталась про «качественную работу». Потолки должны видеть вердикт ДО вызова LLM.
# (Targets must reflect the verdict before the LLM plans, so prose matches the card.)

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

from src.coach.config import HARD_TYPES, LONG_RUN_CAP_TOLERANCE_KM
from src.coach.contracts import Prescription, SafetyVerdict, WorkoutProposal


def quality_blocked(verdict: SafetyVerdict) -> bool:
    """Вердикт не оставил ни одного качественного типа (no hard type is allowed)."""
    if not verdict.allow_training:
        return True
    if not verdict.allowed_types:            # пусто = все разрешены (empty = all allowed)
        return False
    return not (set(HARD_TYPES) & set(verdict.allowed_types))


def apply_safety_to_targets(targets: dict[str, Any], verdict: SafetyVerdict) -> dict[str, Any]:
    """Обнулить потолки качества недели, если safety закрыл интенсив; иначе — без изменений.

    Чистая функция: возвращает новый dict, ключ `quality_blocked_by_safety` — первая причина
    вердикта (текст для шапки карточки и промпта). (Pure: zero quality caps when hard types
    are forbidden; records the first safety reason.)
    """
    if not quality_blocked(verdict):
        return targets
    out = dict(targets)
    out["hard_days_max"] = 0
    if "remaining_hard_days_max" in out:
        out["remaining_hard_days_max"] = 0
    out["quality_z3_km_max"] = 0.0
    out["quality_z4_km_max"] = 0.0
    reason = next((r.reason for r in verdict.reasons if r.reason), None)
    out["quality_blocked_by_safety"] = reason or "интенсив закрыт границами безопасности"
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
    return replace(proposal, duration_min=int(new_min), distance_km=new_km), note
