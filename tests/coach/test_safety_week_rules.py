# Правила 12–14 p1_safety (M4.1/M4.3, F5/F6): близость качественных дней,
# восстановление после гонки, возврат после паузы.
# (Safety rules 12–14: quality-day spacing, post-race window, detraining.)

from datetime import date, datetime, timedelta, timezone

from src.coach.config import HARD_TYPES, SAFETY_MAX_ZONE_DEFAULT
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


def test_three_quality_days_in_week_trigger():
    """quality_days_7d=3 (лимит недели) → правило срабатывает даже при
    соблюдённом интервале между качественными."""
    verdict = evaluate_safety(
        _state(days_since_quality=3, quality_days_7d=3), now=NOW)
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
