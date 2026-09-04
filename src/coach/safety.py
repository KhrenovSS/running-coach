# Безусловный clamp — ЕДИНСТВЕННЫЙ конструктор Prescription (DEV_PLAN §1/§4)
#
# clamp() может только СУЖАТЬ предложение: даунгрейд типа по лестнице, усечение
# зоны/длительности, сдвиг интенсива вперёд; целевой темп может только
# замедлиться или исчезнуть, никогда не ускориться. Расширить предложение он
# не умеет — в коде нет ни одной ветки, присваивающей значение больше входного.
# (Unconditional clamp — the only Prescription constructor; it can only narrow;
# target pace may only slow down or be dropped.)

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from src.coach.config import (
    HARD_TYPES,
    PACE_TARGET_MAX_PER_KM,
    PACE_TARGET_MIN_PER_KM,
    STRIDE_MAX_SEC,
    TYPE_INTENSITY_ORDER,
    TYPE_MIN_ZONE,
)
from src.coach.contracts import (
    AthleteState,
    PaceClampContext,
    Prescription,
    ReasoningStep,
    SafetyVerdict,
    WorkoutProposal,
)

_LADDER = {t: i for i, t in enumerate(TYPE_INTENSITY_ORDER)}


def _step(decision: str, reason: str) -> ReasoningStep:
    return ReasoningStep(rule="p1_safety", decision=decision, reason=reason)


def _downgrade(workout_type: str, allowed: tuple[str, ...], max_zone: int) -> str:
    """Самый интенсивный тип, разрешённый и вписывающийся в потолок зоны.

    (Highest-intensity type that is both allowed and fits under the zone cap.)
    """
    candidates = [
        t for t in TYPE_INTENSITY_ORDER
        if (not allowed or t in allowed) and TYPE_MIN_ZONE[t] <= max_zone
    ]
    if not candidates:
        return "rest"
    # не выше исходного типа — clamp только сужает (never above the original type)
    origin_rank = _LADDER.get(workout_type, len(TYPE_INTENSITY_ORDER))
    fitting = [t for t in candidates if _LADDER[t] <= origin_rank]
    return fitting[-1] if fitting else candidates[0]


def is_stride(seg) -> bool:
    """Короткое ускорение (гайды 45/46: 15–20 с): секунды ≤ STRIDE_MAX_SEC или минуты ≤ его доля.
    Принимает WorkoutSegment и render-dict. (Short stride, not a quality rep.)"""
    kind = getattr(seg, "amount_kind", None) if not isinstance(seg, dict) else seg.get("amount_kind")
    value = getattr(seg, "amount_value", None) if not isinstance(seg, dict) else seg.get("amount_value")
    if value is None:
        return False
    if kind == "sec":
        return value <= STRIDE_MAX_SEC
    if kind == "min":
        return value * 60 <= STRIDE_MAX_SEC
    return False


def _seg_field(seg, name):
    return seg.get(name) if isinstance(seg, dict) else getattr(seg, name, None)


def effective_workout_type(proposal: WorkoutProposal) -> str:
    """Тип по СОДЕРЖИМОМУ сегментов, не по ярлыку (инцидент 04.09.2026).

    Рабочие отрезки в Z3+, которые не ускорения, — качественная работа: Z3 → tempo,
    Z4+ → interval; иначе исходный тип. Тип не понижается (long с работой в Z2 остаётся long).
    (Classify by work segments; mislabelled quality work cannot dodge the intensity gates.)
    """
    hard_zone = 0
    for seg in proposal.segments or []:
        if _seg_field(seg, "role") != "work" or is_stride(seg):
            continue
        zone = _seg_field(seg, "target_zone") or 0
        if zone >= 3:
            hard_zone = max(hard_zone, zone)
    if hard_zone == 0:
        return proposal.workout_type
    eff = "tempo" if hard_zone == 3 else "interval"
    return eff if _LADDER.get(eff, 0) > _LADDER.get(proposal.workout_type, 0) else proposal.workout_type


def _work_summary(proposal: WorkoutProposal) -> str:
    """«4×3 мин в Z3» — для причины переклассификации (human-readable work summary)."""
    parts = []
    for seg in proposal.segments or []:
        if _seg_field(seg, "role") == "work" and not is_stride(seg) and (_seg_field(seg, "target_zone") or 0) >= 3:
            rep = _seg_field(seg, "repeat") or 1
            val = _seg_field(seg, "amount_value")
            kind = _seg_field(seg, "amount_kind") or "min"
            unit = {"min": "мин", "sec": "с", "km": "км", "m": "м"}.get(kind, kind)
            parts.append(f"{rep}×{val:g} {unit} в Z{_seg_field(seg, 'target_zone')}")
    return ", ".join(parts)


def clamp(proposal: WorkoutProposal | None, verdict: SafetyVerdict,
          state: AthleteState, *, now: datetime | None = None,
          source: str = "fallback",
          pace_ctx: PaceClampContext | None = None) -> tuple[Prescription, bool]:
    """Превратить предложение в назначение, применив границы (proposal → prescription).

    Тотальная функция: None/мусор на входе → консервативный выход, не исключение.
    Возвращает (prescription, clamped). (Total function; returns conservative output.)
    """
    now = now or datetime.now(timezone.utc)
    rationale: list[ReasoningStep] = []
    clamped = False

    # 1. Полный запрет — всё предложение отбрасывается (full stop discards everything)
    if not verdict.allow_training:
        rationale = list(verdict.reasons) + [_step("отдых", "тренировки сегодня запрещены")]
        return Prescription(
            safety=verdict, workout_type="rest", when=now.date(),
            rationale=rationale, confidence=0.9, clamped=True,
            source=source, proposal=proposal,
        ), True

    # 2. Нет предложения — консервативный отдых (no proposal → conservative rest)
    if proposal is None:
        return Prescription(
            safety=verdict, workout_type="rest", when=now.date(),
            rationale=[_step("отдых", "предложение отсутствует — консервативный выход")],
            confidence=0.3, clamped=True, source=source, proposal=None,
        ), True

    # Целевой день назначения: 0 = сегодня (штатно), N — будущий день недели.
    # (Target day of the prescription; future days come from for_days_ahead.)
    days_ahead = proposal.for_days_ahead or 0
    when = now.date() + timedelta(days=days_ahead)

    wtype = proposal.workout_type
    if wtype not in TYPE_INTENSITY_ORDER:
        # Неизвестный тип трактуется как максимально опасный (unknown = dangerous)
        clamped = True
        rationale.append(_step("тип → easy", f"неизвестный тип «{wtype}» отклонён"))
        wtype = "easy"

    # 2b. Интенсивность — по сегментам, не по ярлыку: «лёгкий бег» с отрезками 4×3 мин в Z3
    # — это темповая, и гейты интенсива (шаги 3–4) обязаны её видеть (инцидент 04.09.2026).
    # (Reclassify by work segments so mislabelled quality work hits the intensity gates.)
    effective = effective_workout_type(proposal) if wtype == proposal.workout_type else wtype
    if effective != wtype:
        rationale.append(_step(f"тип {wtype} → {effective}",
                               f"отрезки {_work_summary(proposal)} — качественная работа, "
                               "не ускорения (гайды 45/46)"))
        wtype = effective

    # 3. Тип не разрешён или не вписывается в потолок зоны → даунгрейд по лестнице
    target = _downgrade(wtype, verdict.allowed_types, verdict.max_zone)
    if target != wtype:
        clamped = True
        rationale.append(_step(f"тип {wtype} → {target}",
                               "тип не разрешён границами безопасности"))
        wtype = target

    # 4. Интенсив раньше восстановления → easy (hard before earliest_next_hard → easy)
    # Для будущего дня сравниваем с КОНЦОМ целевого дня: субботний earliest не
    # должен резать воскресный интенсив; внутри дня границу показывает карточка
    # («Интенсив — не раньше …»), а утренний вердикт целевого дня пересчитает
    # всё по свежим метрикам. (Future day → compare against the target day's end.)
    gate_ref = (now if days_ahead == 0
                else datetime.combine(when + timedelta(days=1), time(0),
                                      tzinfo=now.tzinfo or timezone.utc))
    if (wtype in HARD_TYPES and verdict.earliest_next_hard is not None
            and gate_ref < verdict.earliest_next_hard):
        clamped = True
        rationale.append(_step(f"тип {wtype} → easy",
                               "интенсив не раньше "
                               f"{verdict.earliest_next_hard:%d.%m %H:%M}"))
        wtype = "easy"

    if effective != proposal.workout_type and wtype != effective \
            and _LADDER.get(wtype, 0) > _LADDER.get(proposal.workout_type, 0):
        # Даунгрейд переклассифицированной работы — не выше исходного ярлыка: «easy» с
        # отрезками, урезанное гейтом, становится easy, а не long (лестница ниже tempo).
        # (A gated reclassified proposal falls back to its own label, never above it.)
        rationale.append(_step(f"тип {wtype} → {proposal.workout_type}",
                               "урезанная качественная работа возвращается к исходному типу"))
        wtype = proposal.workout_type

    # 5. Зона — не выше потолка (zone at most the cap)
    zone = proposal.target_zone
    if zone > verdict.max_zone:
        clamped = True
        rationale.append(_step(f"зона {zone} → {verdict.max_zone}",
                               "потолок зоны по безопасности"))
        zone = verdict.max_zone
    zone = max(1, min(zone, verdict.max_zone))

    # 5b. Целевой темп (pace-lead) — может только замедлиться или исчезнуть.
    # (Target pace may only slow down or be dropped, never speed up.)
    pace = proposal.target_pace_min_km
    if pace is not None:
        if not (PACE_TARGET_MIN_PER_KM <= pace <= PACE_TARGET_MAX_PER_KM):
            # Схема LLM — не гарантия: fallback/прямой proposal её обходит.
            clamped = True
            rationale.append(_step("темп отброшен",
                                   f"целевой темп {pace:.2f} мин/км вне допустимых границ"))
            pace = None
        elif clamped:
            # Структурные санкции (тип/интенсив/зона урезаны) — числа предложения
            # уже невалидны; деградация в HR-режим с заклэмпленным потолком зоны.
            rationale.append(_step("темп отброшен",
                                   "ведущий темп отброшен: назначение урезано безопасностью"))
            pace = None
        elif (pace_ctx is not None and pace_ctx.expected_hr is not None
                and pace_ctx.zone_ceiling_bpm is not None
                and pace_ctx.expected_hr > pace_ctx.zone_ceiling_bpm):
            clamped = True
            if pace_ctx.safe_pace_min_km is not None:
                # max(): темп только замедляется (медленнее = численно больше)
                slowed = max(pace, pace_ctx.safe_pace_min_km)
                rationale.append(_step(
                    f"темп {pace:.2f} → {slowed:.2f} мин/км",
                    f"расчётный пульс {pace_ctx.expected_hr} выше потолка "
                    f"{pace_ctx.zone_ceiling_bpm} уд/мин"))
                pace = slowed
            else:
                rationale.append(_step(
                    "темп отброшен",
                    f"расчётный пульс {pace_ctx.expected_hr} выше потолка "
                    f"{pace_ctx.zone_ceiling_bpm} уд/мин, безопасный темп неизвестен"))
                pace = None
        # Оценки нет (мало данных / db=None) → темп как есть: защита — санити,
        # структурные санкции и потолок зоны (решение владельца 26.08.2026).

    # 6. Длительность — усечение; дистанция пересчитывается вниз пропорционально
    duration = proposal.duration_min
    distance = proposal.distance_km
    if (duration is not None and verdict.max_duration_min is not None
            and duration > verdict.max_duration_min):
        clamped = True
        scale = verdict.max_duration_min / duration
        rationale.append(_step(f"длительность {duration} → {verdict.max_duration_min} мин",
                               "потолок длительности по безопасности"))
        duration = verdict.max_duration_min
        if distance is not None:
            distance = round(distance * scale, 1)

    if wtype == "rest":
        zone, duration, distance, pace = 1, None, None, None

    if pace is not None and duration is not None:
        # Pace-режим: дистанция — детерминированная арифметика из итоговых
        # темпа и длительности, а не догадка LLM. (Deterministic distance.)
        distance = round(duration / pace, 1)

    if clamped:
        rationale = list(verdict.reasons) + rationale
    rationale += [ReasoningStep(rule=source, decision=r, reason="предложение источника")
                  for r in proposal.rationale[:5]]

    volume: dict = {}
    if duration is not None:
        volume["duration_min"] = duration
    if distance is not None:
        volume["distance_km"] = distance
    target_d: dict = {"max_zone": zone}
    if pace is not None:
        target_d["pace_min_km"] = pace
    if proposal.structure and not clamped:
        # Структура интервалов при урезании отбрасывается — числа в ней уже неверны.
        # (Interval structure is dropped on clamp — its numbers are no longer valid.)
        target_d["structure"] = proposal.structure

    return Prescription(
        safety=verdict,
        workout_type=wtype,
        when=when,
        earliest=verdict.earliest_next_hard,
        target=target_d,
        volume=volume,
        rationale=rationale,
        confidence=0.7 if not clamped else 0.85,
        clamped=clamped,
        source=source,
        proposal=proposal,
    ), clamped


def rehydrate(row) -> Prescription:
    """Восстановить Prescription из УЖЕ клэмпленной строки recommendations.

    Числа строки прошли clamp() при записи (save_prescription), поэтому это не
    обход границы, а чтение её результата: вердикт — пустой SafetyVerdict
    (исходный лежит в safety_json как метрика дрейфа). Никаких пересчётов.
    Используется read-only карточкой сохранённого плана недели (week_view).
    (Rehydrate a persisted, already-clamped prescription; no recomputation.)
    """
    return Prescription(
        safety=SafetyVerdict(),
        workout_type=row.workout_type,
        when=row.for_date,
        target=dict(row.target_json or {}),
        volume=dict(row.volume_json or {}),
        predicted=dict(row.predicted_json or {}),
        clamped=bool(row.clamped),
        source=row.source or "plan",
    )
