# Безусловный clamp — ЕДИНСТВЕННЫЙ конструктор Prescription (DEV_PLAN §1/§4)
#
# clamp() может только СУЖАТЬ предложение: даунгрейд типа по лестнице, усечение
# зоны/длительности, сдвиг интенсива вперёд. Расширить предложение он не умеет —
# в коде нет ни одной ветки, присваивающей значение больше входного.
# (Unconditional clamp — the only Prescription constructor; it can only narrow.)

from __future__ import annotations

from datetime import datetime, timezone

from src.coach.config import (
    HARD_TYPES,
    TYPE_INTENSITY_ORDER,
    TYPE_MIN_ZONE,
)
from src.coach.contracts import (
    AthleteState,
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


def clamp(proposal: WorkoutProposal | None, verdict: SafetyVerdict,
          state: AthleteState, *, now: datetime | None = None,
          source: str = "fallback") -> tuple[Prescription, bool]:
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

    wtype = proposal.workout_type
    if wtype not in TYPE_INTENSITY_ORDER:
        # Неизвестный тип трактуется как максимально опасный (unknown = dangerous)
        clamped = True
        rationale.append(_step("тип → easy", f"неизвестный тип «{wtype}» отклонён"))
        wtype = "easy"

    # 3. Тип не разрешён или не вписывается в потолок зоны → даунгрейд по лестнице
    target = _downgrade(wtype, verdict.allowed_types, verdict.max_zone)
    if target != wtype:
        clamped = True
        rationale.append(_step(f"тип {wtype} → {target}",
                               "тип не разрешён границами безопасности"))
        wtype = target

    # 4. Интенсив раньше восстановления → easy (hard before earliest_next_hard → easy)
    if (wtype in HARD_TYPES and verdict.earliest_next_hard is not None
            and now < verdict.earliest_next_hard):
        clamped = True
        rationale.append(_step(f"тип {wtype} → easy",
                               "интенсив не раньше "
                               f"{verdict.earliest_next_hard:%d.%m %H:%M}"))
        wtype = "easy"

    # 5. Зона — не выше потолка (zone at most the cap)
    zone = proposal.target_zone
    if zone > verdict.max_zone:
        clamped = True
        rationale.append(_step(f"зона {zone} → {verdict.max_zone}",
                               "потолок зоны по безопасности"))
        zone = verdict.max_zone
    zone = max(1, min(zone, verdict.max_zone))

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
        zone, duration, distance = 1, None, None

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
    if proposal.structure and not clamped:
        # Структура интервалов при урезании отбрасывается — числа в ней уже неверны.
        # (Interval structure is dropped on clamp — its numbers are no longer valid.)
        target_d["structure"] = proposal.structure

    return Prescription(
        safety=verdict,
        workout_type=wtype,
        when=now.date(),
        earliest=verdict.earliest_next_hard,
        target=target_d,
        volume=volume,
        rationale=rationale,
        confidence=0.7 if not clamped else 0.85,
        clamped=clamped,
        source=source,
        proposal=proposal,
    ), clamped
