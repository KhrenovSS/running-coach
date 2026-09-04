# P1 — граница безопасности (Safety boundary) — DEV_PLAN §4
#
# ЧИСТАЯ функция над AthleteState (без db, без I/O, `now` — параметр):
# реплеябельна по сохранённому снимку. Через неё проходит 100% назначений.
# (Pure function over AthleteState; every prescription passes through it.)

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.config.constants import (
    DETRAINING_MIN_DAYS_OFF,
    QUALITY_MAX_PER_WEEK,
    QUALITY_MIN_GAP_DAYS,
)
from src.coach.config import (
    ATI_CTI_HIGH,
    HARD_SHARE_OVERLOAD,
    HARD_TYPES,
    HRR_POOR_RECOVERY_EXTRA_H,
    SLEEP_SHORT_MIN,
    SLEEP_VERY_SHORT_MIN,
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

    # 11. Плохое восстановление между интервалами (F3, §7 METRICS_GUIDE):
    # пульс не падал между повторами — признак недовосстановления, следующий
    # качественный день консервативно отодвигается
    # (poor HRR between reps → push the next hard day further out)
    if sig.get("poor_interval_recovery"):
        triggered.append("poor_interval_recovery")
        hrr_earliest = now + timedelta(hours=HRR_POOR_RECOVERY_EXTRA_H)
        if earliest_next_hard is None or hrr_earliest > earliest_next_hard:
            earliest_next_hard = hrr_earliest
        reasons.append(_step("интенсив не раньше чем",
                             "пульс плохо падал между повторами последней интервальной — "
                             f"минимум {HRR_POOR_RECOVERY_EXTRA_H} ч до следующего качественного дня"))

    # 12. Качественные дни слишком близко (M4.1, гайды 41/45): минимум 1 лёгкий
    # день между качественными и ≤3 качественных за 7 дней
    # (quality days too close: at least one easy day between, ≤3 per week)
    dsq = sig.get("days_since_quality")
    if ((dsq is not None and dsq < QUALITY_MIN_GAP_DAYS)
            or (sig.get("quality_days_7d") or 0) > QUALITY_MAX_PER_WEEK):
        triggered.append("hard_days_too_close")
        gap_earliest = now + timedelta(days=max(1, QUALITY_MIN_GAP_DAYS - (dsq or 0)))
        if earliest_next_hard is None or gap_earliest > earliest_next_hard:
            earliest_next_hard = gap_earliest
        reasons.append(_step("интенсив не раньше чем",
                             "между качественными днями нужен минимум один лёгкий день "
                             "(длительная — тоже качественный день, гайд 45; "
                             f"качественных за неделю: {sig.get('quality_days_7d')})"))

    # 13. Восстановление после гонки (M4.1, гайд 45): 1 лёгкий день на каждые 3 км
    # (post-race recovery: one easy day per 3 km of race distance)
    race_left = sig.get("post_race_days_left") or 0
    if race_left > 0:
        triggered.append("post_race_recovery")
        max_zone = min(max_zone, 2)
        forbidden |= set(HARD_TYPES)
        reasons.append(_step("max_zone=2",
                             f"восстановление после гонки: ещё {race_left} лёгких дн."))

    # 14. Возврат после паузы (M4.3, гайд 46): ≥6 дней без бега → мягкий вход
    # (return from a layoff: gentle first sessions back)
    days_off = sig.get("days_off")
    if days_off is not None and days_off >= DETRAINING_MIN_DAYS_OFF:
        triggered.append("detraining")
        max_zone = min(max_zone, 2)
        forbidden |= set(HARD_TYPES)
        reasons.append(_step("max_zone=2",
                             f"пауза {days_off} дн. — форма просела, возвращаемся мягко"))

    # 15. Недосып (#254, v1 — абсолютные пороги; данные — скриншот сна за сегодня)
    # (short sleep last night → easier day; silent when no screenshot)
    sleep_min = sig.get("sleep_duration_min")
    if sleep_min is not None and sleep_min < SLEEP_VERY_SHORT_MIN:
        triggered.append("sleep_very_short")
        max_zone = min(max_zone, 2)
        max_duration = (min(max_duration, SAFETY_MAX_DURATION_CAUTION_MIN)
                        if max_duration else SAFETY_MAX_DURATION_CAUTION_MIN)
        forbidden |= set(HARD_TYPES)
        reasons.append(_step(f"max_zone=2, ≤{SAFETY_MAX_DURATION_CAUTION_MIN} мин",
                             f"сон {sleep_min / 60:.1f} ч — сильный недосып, только лёгкое и коротко"))
    elif sleep_min is not None and sleep_min < SLEEP_SHORT_MIN:
        triggered.append("sleep_short")
        forbidden |= set(HARD_TYPES)
        reasons.append(_step("без интенсива",
                             f"сон {sleep_min / 60:.1f} ч — недосып, качественную не сегодня"))

    # 16. Перекос последних 7 дней в интенсивность (гайд 10: Z3+ > 30% времени —
    # неделя перегружена, следующая почти целиком лёгкая; решение владельца 04.09.2026)
    # (weekly intensity skew → easy only until the share drops)
    hard_share = sig.get("hard_share_7d")
    if hard_share is not None and hard_share > HARD_SHARE_OVERLOAD:
        triggered.append("week_intensity_overload")
        max_zone = min(max_zone, 2)
        forbidden |= set(HARD_TYPES)
        reasons.append(_step("max_zone=2, без интенсива",
                             f"за 7 дней {hard_share:.0%} времени в Z3+ — неделя перегружена "
                             "интенсивностью, только лёгкое (гайд 10)"))

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
