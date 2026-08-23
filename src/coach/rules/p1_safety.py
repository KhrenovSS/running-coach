# P1 — граница безопасности (Safety boundary) — DEV_PLAN §4
#
# ЧИСТАЯ функция над AthleteState (без db, без I/O, `now` — параметр):
# реплеябельна по сохранённому снимку. Через неё проходит 100% назначений.
# (Pure function over AthleteState; every prescription passes through it.)

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.coach.config import (
    ATI_CTI_HIGH,
    HARD_TYPES,
    INJURY_RISK_THRESHOLDS,
    PAIN_CAUTION_LEVEL,
    PAIN_PERSIST_DAYS,
    PAIN_STOP_LEVEL,
    RECOVERY_PCT_MODERATE,
    SAFETY_MAX_DURATION_CAUTION_MIN,
    SAFETY_MAX_ZONE_DEFAULT,
    TYPE_INTENSITY_ORDER,
)
from src.coach.contracts import AthleteState, ReasoningStep, SafetyVerdict


def _step(decision: str, reason: str) -> ReasoningStep:
    return ReasoningStep(rule="p1_safety", decision=decision, reason=reason)


def evaluate_safety(state: AthleteState, *, now: datetime | None = None) -> SafetyVerdict:
    """Вычислить границы безопасности из снимка состояния (compute safety bounds).

    Незнание = опасность: при отсутствии данных потолок ОПУСКАЕТСЯ, а не снимается.
    """
    now = now or datetime.now(timezone.utc)
    sig = state.signals or {}
    triggered: list[str] = []
    reasons: list[ReasoningStep] = []
    allow = True
    max_zone = SAFETY_MAX_ZONE_DEFAULT
    max_duration: int | None = None
    forbidden: set[str] = set()
    earliest_next_hard: datetime | None = None

    # 0. Незнание = опасность (no data → conservative ceiling, not free rein)
    if state.as_of is None:
        triggered.append("no_data")
        max_zone = min(max_zone, 2)
        forbidden |= set(HARD_TYPES) | {"long"}
        reasons.append(_step("max_zone=2, только лёгкое",
                             "нет метрик здоровья — консервативный потолок"))

    # 1. RHR критически повышен → тренировка запрещена (болезнь/перетрен)
    if sig.get("rhr_status") == "critical_elevated":
        triggered.append("rhr_critical")
        allow = False
        reasons.append(_step("отдых", "пульс покоя критически выше базовой линии — "
                                      "признак болезни или перетренированности"))

    # 2–3. HRV низкая/очень низкая
    hrv = sig.get("hrv_status")
    if hrv == "very_low":
        triggered.append("hrv_very_low")
        max_zone = min(max_zone, 2)
        forbidden |= set(HARD_TYPES) | {"long"}
        reasons.append(_step("max_zone=2, только rest/recovery/easy",
                             "HRV значительно ниже базовой линии"))
    elif hrv == "low":
        triggered.append("hrv_low")
        max_zone = min(max_zone, 2)
        forbidden |= set(HARD_TYPES)
        reasons.append(_step("max_zone=2, без интенсива", "HRV ниже базовой линии"))

    # 4. Восстановление не завершено по данным часов
    rec_pct = sig.get("recovery_pct")
    if rec_pct is not None and rec_pct < RECOVERY_PCT_MODERATE:
        triggered.append("recovery_low")
        max_zone = min(max_zone, 2)
        reasons.append(_step("max_zone=2", f"восстановление {rec_pct}% — ниже порога"))

    # 5. Перекос в анаэробную нагрузку
    ati_cti = sig.get("ati_cti_ratio")
    if ati_cti is not None and ati_cti > ATI_CTI_HIGH:
        triggered.append("ati_cti_high")
        max_zone = min(max_zone, 3)
        forbidden.add("interval")
        reasons.append(_step("max_zone=3, без интервалов",
                             f"ATI/CTI={ati_cti:.2f} — перекос в анаэробную нагрузку"))

    # 6. ACWR выше травмоопасного порога
    acwr = sig.get("acwr_ratio")
    if acwr is not None and acwr > INJURY_RISK_THRESHOLDS["load_ratio_high"]:
        triggered.append("acwr_high")
        max_zone = min(max_zone, 3)
        reasons.append(_step("max_zone=3", f"ACWR={acwr:.2f} — острая нагрузка "
                                           "травмоопасно выше хронической"))

    # 7. Серия тяжёлых дней
    hard_days = sig.get("consecutive_hard_days") or 0
    if hard_days >= INJURY_RISK_THRESHOLDS["consecutive_hard_days"]:
        triggered.append("hard_streak")
        max_zone = min(max_zone, 2)
        reasons.append(_step("max_zone=2", f"{hard_days} тяжёлых дня подряд"))

    # 8–9. Боль (колено) — ранний датчик (pain as an early sensor)
    pain = sig.get("pain_level")
    pain_days = sig.get("pain_days") or 0
    if pain is not None and pain >= PAIN_STOP_LEVEL:
        triggered.append("pain_stop")
        allow = False
        reasons.append(_step("отдых", f"боль {pain}/10 — бегать нельзя"))
    elif (pain is not None and pain >= PAIN_CAUTION_LEVEL) or pain_days >= PAIN_PERSIST_DAYS:
        triggered.append("pain_caution")
        max_zone = min(max_zone, 2)
        max_duration = SAFETY_MAX_DURATION_CAUTION_MIN
        forbidden |= set(HARD_TYPES)
        reasons.append(_step(f"max_zone=2, ≤{SAFETY_MAX_DURATION_CAUTION_MIN} мин",
                             f"боль {pain}/10 или {pain_days} дн. подряд — щадящий режим"))

    # 10. Часы восстановления не вышли → интенсив не раньше чем (ex-P2)
    left = state.recovery_hours_left or 0
    if left > 0:
        triggered.append("recovery_hours")
        earliest_next_hard = now + timedelta(hours=left)
        reasons.append(_step("интенсив не раньше чем",
                             f"до восстановления после последней тренировки {left:.0f} ч"))

    allowed_types: tuple[str, ...] = ()
    if forbidden:
        allowed_types = tuple(t for t in TYPE_INTENSITY_ORDER if t not in forbidden)

    return SafetyVerdict(
        allow_training=allow,
        max_zone=max_zone,
        max_duration_min=max_duration,
        allowed_types=allowed_types,
        earliest_next_hard=earliest_next_hard,
        triggered=triggered,
        reasons=reasons,
    )
