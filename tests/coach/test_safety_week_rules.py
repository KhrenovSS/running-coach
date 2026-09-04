# Правила 12–15 p1_safety (M4.1/M4.3, F5/F6, #254): близость качественных дней,
# восстановление после гонки, возврат после паузы, недосып.
# (Safety rules 12–15: quality-day spacing, post-race window, detraining, sleep.)

from datetime import date, datetime, timedelta, timezone

import pytest

from src.coach.config import (
    HARD_TYPES,
    SAFETY_MAX_DURATION_CAUTION_MIN,
    SAFETY_MAX_ZONE_DEFAULT,
    SLEEP_SHORT_MIN,
    SLEEP_VERY_SHORT_MIN,
)
from src.coach.contracts import AthleteState, WorkoutProposal
from src.coach.rules.p1_safety import evaluate_safety
from src.coach.safety import clamp
from src.config.constants import QUALITY_MIN_GAP_DAYS

NOW = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
AGGRESSIVE = WorkoutProposal(workout_type="interval", target_zone=5,
                             duration_min=90, distance_km=15.0)


def _state(**signals) -> AthleteState:
    """Здоровое состояние + недельные сигналы в форме _week_signals по умолчанию.
    (Healthy state with the default _week_signals shape.)"""
    base = {
        "hrv_status": "normal", "rhr_status": "normal", "recovery_pct": 90,
        "ati_cti_ratio": 1.0, "acwr_ratio": 1.0, "consecutive_hard_days": 0,
        "pain_level": None, "pain_days": 0,
        # дефолты _week_signals (см. src/coach/state.py)
        "days_since_quality": None, "quality_days_7d": 0,
        "post_race_days_left": 0, "days_off": None,
    }
    base.update(signals)
    return AthleteState(user_id=1, as_of=date.today(), data_confidence=0.9,
                        recovery_hours_left=0.0, signals=base)


# --- Правило 12: качественные дни слишком близко --------------------------------

def test_quality_yesterday_delays_next_hard():
    """days_since_quality=1 → hard_days_too_close, интенсив не раньше now+1д."""
    verdict = evaluate_safety(_state(days_since_quality=1, quality_days_7d=1),
                              now=NOW)
    assert "hard_days_too_close" in verdict.triggered
    assert verdict.earliest_next_hard == NOW + timedelta(days=1)
    assert verdict.allow_training is True

    p, clamped = clamp(AGGRESSIVE, verdict, _state(days_since_quality=1), now=NOW)
    assert clamped is True
    assert p.workout_type == "easy"                # интенсив сегодня урезан


def test_quality_days_limit_boundary():
    """Лимит ≤3 качественных/нед: ровно 3 — правило молчит (лимит соблюдён,
    выравнено с week_structure #1c 02.09), 4 — срабатывает."""
    verdict = evaluate_safety(
        _state(days_since_quality=3, quality_days_7d=3), now=NOW)
    assert "hard_days_too_close" not in verdict.triggered
    verdict = evaluate_safety(
        _state(days_since_quality=3, quality_days_7d=4), now=NOW)
    assert "hard_days_too_close" in verdict.triggered
    assert verdict.earliest_next_hard == NOW + timedelta(days=1)  # max(1, 2-3)


def test_quality_gap_respected_rule_silent():
    """Интервал = QUALITY_MIN_GAP_DAYS и ≤2 качественных → правило молчит."""
    verdict = evaluate_safety(
        _state(days_since_quality=QUALITY_MIN_GAP_DAYS, quality_days_7d=2),
        now=NOW)
    assert "hard_days_too_close" not in verdict.triggered
    assert verdict.earliest_next_hard is None


def test_quality_gap_takes_max_with_recovery_hours():
    """Совместно с часами восстановления действует МАКСИМУМ границ."""
    state = _state(days_since_quality=1, quality_days_7d=2)
    state.recovery_hours_left = 72.0               # дольше, чем +1 день правила 12
    verdict = evaluate_safety(state, now=NOW)
    assert {"recovery_hours", "hard_days_too_close"} <= set(verdict.triggered)
    assert verdict.earliest_next_hard == NOW + timedelta(hours=72)


# --- Правило 13: восстановление после гонки -------------------------------------

def test_post_race_days_left_caps_zone_and_forbids_hard():
    verdict = evaluate_safety(_state(post_race_days_left=3), now=NOW)
    assert "post_race_recovery" in verdict.triggered
    assert verdict.max_zone == 2
    assert all(t not in verdict.allowed_types for t in HARD_TYPES)

    p, clamped = clamp(AGGRESSIVE, verdict, _state(post_race_days_left=3), now=NOW)
    assert clamped is True
    assert p.workout_type not in HARD_TYPES
    assert p.target["max_zone"] <= 2


# --- Правило 14: возврат после паузы ---------------------------------------------

def test_days_off_eight_triggers_detraining():
    verdict = evaluate_safety(_state(days_off=8), now=NOW)
    assert "detraining" in verdict.triggered
    assert verdict.max_zone == 2
    assert all(t not in verdict.allowed_types for t in HARD_TYPES)

    p, clamped = clamp(AGGRESSIVE, verdict, _state(days_off=8), now=NOW)
    assert clamped is True
    assert p.workout_type not in HARD_TYPES
    assert p.target["max_zone"] <= 2


def test_days_off_five_rule_silent():
    """Пауза 5 дней (< DETRAINING_MIN_DAYS_OFF=6) → форма не потеряна."""
    verdict = evaluate_safety(_state(days_off=5), now=NOW)
    assert "detraining" not in verdict.triggered
    assert verdict.max_zone == SAFETY_MAX_ZONE_DEFAULT


# --- Правило 15 (#254): недосып из скриншота сна ----------------------------------

# (sleep_duration_min, ожидаемый триггер или None-«молчит»)
SLEEP_CASES = [
    (None, None),                          # скриншота нет → не наказываем
    (400, None),                           # 6ч40м — норм
    (SLEEP_SHORT_MIN, None),               # ровно 6 ч — граница, молчит
    (340, "sleep_short"),                  # 5ч40м → без интенсива
    (SLEEP_VERY_SHORT_MIN, "sleep_short"), # ровно 5 ч → ещё не very_short
    (280, "sleep_very_short"),             # 4ч40м → max_zone=2 + потолок 40 мин
]


@pytest.mark.parametrize("sleep_min,trigger", SLEEP_CASES)
def test_sleep_rule_table(sleep_min, trigger):
    verdict = evaluate_safety(_state(sleep_duration_min=sleep_min), now=NOW)
    sleep_triggers = {t for t in verdict.triggered if t.startswith("sleep")}
    assert sleep_triggers == ({trigger} if trigger else set())
    if trigger is None:
        assert verdict.max_zone == SAFETY_MAX_ZONE_DEFAULT
        assert verdict.max_duration_min is None
        assert verdict.allowed_types == ()             # запретов нет
    else:
        assert all(t not in verdict.allowed_types for t in HARD_TYPES)


def test_sleep_short_forbids_hard_but_keeps_zone():
    """340 мин → HARD_TYPES запрещены, clamp урезает interval,
    но max_zone НЕ тронут (лёгкий длинный день разрешён)."""
    state = _state(sleep_duration_min=340)
    verdict = evaluate_safety(state, now=NOW)
    assert verdict.allow_training is True
    assert verdict.max_zone == SAFETY_MAX_ZONE_DEFAULT  # потолок зоны не опущен
    assert verdict.max_duration_min is None
    p, clamped = clamp(AGGRESSIVE, verdict, state, now=NOW)
    assert clamped is True
    assert p.workout_type not in HARD_TYPES


def test_sleep_very_short_caps_zone_and_duration():
    """280 мин → max_zone=2, потолок длительности 40 мин, HARD запрещены."""
    state = _state(sleep_duration_min=280)
    verdict = evaluate_safety(state, now=NOW)
    assert verdict.max_zone == 2
    assert verdict.max_duration_min == SAFETY_MAX_DURATION_CAUTION_MIN
    p, clamped = clamp(AGGRESSIVE, verdict, state, now=NOW)
    assert clamped is True
    assert p.workout_type not in HARD_TYPES
    assert p.target["max_zone"] <= 2
    assert p.volume["duration_min"] <= SAFETY_MAX_DURATION_CAUTION_MIN


# --- Пустые сигналы: правила 12–14 молчат ----------------------------------------

def test_default_week_signals_all_rules_silent():
    """None/0 (пустая история) → правила 12–14 молчат, интервал проходит."""
    verdict = evaluate_safety(_state(), now=NOW)
    for trig in ("hard_days_too_close", "post_race_recovery", "detraining"):
        assert trig not in verdict.triggered
    assert verdict.earliest_next_hard is None
    p, clamped = clamp(AGGRESSIVE, verdict, _state(), now=NOW)
    assert clamped is False
    assert p.workout_type == "interval"


# --- Правило 16 (гайд 10, 04.09.2026): перекос 7 дней в интенсивность ------------------

@pytest.mark.parametrize("share, triggered", [(0.35, True), (0.31, True), (0.30, False),
                                              (0.2, False), (None, False)])
def test_week_intensity_overload_rule(share, triggered):
    from tests.coach.test_safety_clamp import _state

    verdict = evaluate_safety(_state(hard_share_7d=share))
    assert ("week_intensity_overload" in verdict.triggered) is triggered
    if triggered:
        assert verdict.max_zone == 2
        assert not set(HARD_TYPES) & set(verdict.allowed_types)
        assert "перегружена интенсивностью" in " ".join(r.reason for r in verdict.reasons)
    else:
        assert verdict.max_zone == SAFETY_MAX_ZONE_DEFAULT


# --- P0 04.09.2026: шкала восстановления Coros §12 (#249) и правила 17–20 (#289, #308) -------

@pytest.mark.parametrize("pct, triggered, zone, hard_forbidden", [
    (19, "recovery_low", 2, True),          # Exhausted
    (20, "recovery_fatigued", None, True),  # Fatigued: без интенсива, зона не режется
    (69, "recovery_fatigued", None, True),
    (70, None, None, False),                # Normal
    (95, None, None, False),                # Fresh
])
def test_recovery_bands_follow_coros_scale(pct, triggered, zone, hard_forbidden):
    from tests.coach.test_safety_clamp import _state

    v = evaluate_safety(_state(recovery_pct=pct))
    assert (triggered in v.triggered) if triggered else not (
        {"recovery_low", "recovery_fatigued"} & set(v.triggered))
    assert v.max_zone == (zone or SAFETY_MAX_ZONE_DEFAULT)
    assert (not set(HARD_TYPES) & set(v.allowed_types)) is hard_forbidden if v.allowed_types \
        else hard_forbidden is False


def test_easy_runs_too_hard_rule_17():
    from src.coach.config import EASY_TOO_HARD_WEEK_FLAGS
    from tests.coach.test_safety_clamp import _state

    v = evaluate_safety(_state(easy_too_hard_7d=EASY_TOO_HARD_WEEK_FLAGS))
    assert "easy_runs_too_hard" in v.triggered and v.max_zone == 2
    assert not set(HARD_TYPES) & set(v.allowed_types)
    silent = evaluate_safety(_state(easy_too_hard_7d=EASY_TOO_HARD_WEEK_FLAGS - 1))
    assert "easy_runs_too_hard" not in silent.triggered


def test_quality_volume_and_downhill_push_next_hard():
    from src.coach.config import DOWNHILL_EXTRA_H, QUALITY_VOLUME_EXTRA_H
    from tests.coach.test_safety_clamp import _state

    now = datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc)
    v = evaluate_safety(_state(quality_volume_exceeded_recent=True), now=now)
    assert "quality_volume_exceeded" in v.triggered
    assert v.earliest_next_hard == now + timedelta(hours=QUALITY_VOLUME_EXTRA_H)
    d = evaluate_safety(_state(downhill_load_recent=True), now=now)
    assert "downhill_load" in d.triggered and d.max_zone == 3
    assert d.earliest_next_hard == now + timedelta(hours=DOWNHILL_EXTRA_H)
    both = evaluate_safety(_state(quality_volume_exceeded_recent=True,
                                  downhill_load_recent=True), now=now)
    assert both.earliest_next_hard == now + timedelta(hours=max(QUALITY_VOLUME_EXTRA_H,
                                                                DOWNHILL_EXTRA_H))


@pytest.mark.parametrize("mono, days, triggered", [
    (2.5, 5, True), (2.5, 4, False), (1.5, 6, False), (None, 6, False)])
def test_monotony_rule_20(mono, days, triggered):
    from tests.coach.test_safety_clamp import _state

    v = evaluate_safety(_state(monotony_7d=mono, trained_days_7d=days))
    assert ("monotony_high" in v.triggered) is triggered
    if triggered:
        assert not set(HARD_TYPES) & set(v.allowed_types)
        assert "нужен день отдыха" in " ".join(r.reason for r in v.reasons)
