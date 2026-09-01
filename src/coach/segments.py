# Посегментные метрики тренировки (per-segment workout metrics) — M2.1
#
# LLM задаёт КАЧЕСТВЕННУЮ структуру (роли/повторы/объём/относительная зона), а числа
# пульса/темпа проставляет ДЕТЕРМИНИРОВАННО этот модуль — из зон (zone_ceiling_hr) и
# личной истории (expected_pace_at_hr/expected_hr_at_pace). Инвариант проекта:
# числа для пользователя рендерит код, не проза LLM. При нехватке данных — честная
# пометка «мало данных» (решение владельца 01.09.2026), не выдумка.

from __future__ import annotations

from sqlalchemy.orm import Session

from src.analysis.hr_zones import zone_ceiling_hr
from src.coach.config import TYPE_INTENSITY_ORDER
from src.coach.contracts import RecoverySpec, WorkoutSegment

_LADDER = {t: i for i, t in enumerate(TYPE_INTENSITY_ORDER)}


def _recovery_to_dict(rec: RecoverySpec | None, max_hr: int) -> dict | None:
    if rec is None:
        return None
    until_hr = rec.until_hr
    if until_hr is None and rec.target_zone is not None:
        until_hr = zone_ceiling_hr(rec.target_zone, max_hr)
    return {"until_hr": until_hr, "duration_min": rec.duration_min,
            "distance_km": rec.distance_km, "target_zone": rec.target_zone}


def enrich_and_clamp_segments(segments: list[WorkoutSegment], *, workout_type: str,
                              proposal_type: str, max_zone: int, max_hr: int,
                              user_id: int, db: Session | None) -> list[dict]:
    """Проставить числа сегментам и заклэмпить зоны под safety (→ render-ready dicts).

    Возвращает [] если структуру нельзя показать безопасно: тип понижен по интенсивности
    (числа сегментов недостоверны — как drop-on-clamp для строковой structure) или список
    пуст. Иначе для каждого сегмента: зона ≤ max_zone; hr_ceiling из зоны; темп-ориентир из
    истории (нет данных → pace_missing); если задан явный темп — проверка предсказуемости
    пульса (нет данных → hr_missing). (Enrich segments with numbers, clamp zones to safety.)
    """
    if not segments:
        return []
    # Тип понижен по лестнице интенсивности → структура относится к более жёсткой
    # тренировке, её числа уже неверны: показываем простую карточку (как со structure).
    if _LADDER.get(workout_type, 0) < _LADDER.get(proposal_type, 0):
        return []

    from src.services.workout_insights import (expected_hr_at_pace,
                                               expected_pace_at_hr)

    out: list[dict] = []
    for seg in segments:
        zone = seg.target_zone
        if zone is not None:
            zone = max(1, min(zone, max_zone))     # per-segment clamp под потолок safety
        hr_ceiling = zone_ceiling_hr(zone, max_hr) if zone is not None else None

        pace_target = seg.pace_target_min_km
        pace_hint = None
        pace_missing = False
        hr_missing = False
        if pace_target is not None:
            # Явный темп: проверяем, можем ли предсказать пульс на нём.
            est = (expected_hr_at_pace(user_id, pace_target, db=db)
                   if db is not None else None)
            hr_missing = est is None
        elif hr_ceiling is not None:
            # Темпа нет — оцениваем ориентир по истории на потолке зоны.
            est = (expected_pace_at_hr(user_id, hr_ceiling, db=db)
                   if db is not None else None)
            if est is not None:
                pace_hint = est["pace_min_km"]
            else:
                pace_missing = True

        out.append({
            "role": seg.role,
            "repeat": max(1, seg.repeat),
            "amount_kind": seg.amount_kind,
            "amount_value": seg.amount_value,
            "target_zone": zone,
            "hr_ceiling": hr_ceiling,
            "pace_target_min_km": pace_target,
            "pace_hint_min_km": pace_hint,
            "pace_missing": pace_missing,
            "hr_missing": hr_missing,
            "effort": seg.effort,
            "recovery": _recovery_to_dict(seg.recovery, max_hr),
        })
    return out


def segments_from_schema(items) -> list[WorkoutSegment]:
    """Схема хода LLM (WorkoutSegmentIn) → доменные WorkoutSegment (schema → domain)."""
    out: list[WorkoutSegment] = []
    for s in items or []:
        rec = None
        if s.recovery is not None:
            rec = RecoverySpec(until_hr=s.recovery.until_hr,
                               duration_min=s.recovery.duration_min,
                               distance_km=s.recovery.distance_km,
                               target_zone=s.recovery.target_zone)
        out.append(WorkoutSegment(
            role=s.role, repeat=s.repeat, amount_kind=s.amount_kind,
            amount_value=s.amount_value, target_zone=s.target_zone,
            pace_target_min_km=s.pace_target_min_km, effort=s.effort, recovery=rec))
    return out


def segments_from_target(raw: list[dict] | None) -> list[WorkoutSegment]:
    """Восстановить сегменты предложения из target_json (для re-clamp утром)."""
    if not raw:
        return []
    out: list[WorkoutSegment] = []
    for d in raw:
        rec = d.get("recovery")
        recovery = (RecoverySpec(until_hr=rec.get("until_hr"),
                                 duration_min=rec.get("duration_min"),
                                 distance_km=rec.get("distance_km"),
                                 target_zone=rec.get("target_zone"))
                    if rec else None)
        out.append(WorkoutSegment(
            role=d.get("role", "steady"),
            repeat=d.get("repeat", 1),
            amount_kind=d.get("amount_kind", "time"),
            amount_value=d.get("amount_value"),
            target_zone=d.get("target_zone"),
            pace_target_min_km=d.get("pace_target_min_km"),
            effort=d.get("effort"),
            recovery=recovery,
        ))
    return out
