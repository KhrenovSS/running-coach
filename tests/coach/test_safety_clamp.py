# Табличные тесты границы безопасности (Safety boundary table tests) — DEV_PLAN §10
import pytest

from src.coach.config import (
    INJURY_RISK_THRESHOLDS,
    PAIN_CAUTION_LEVEL,
    PAIN_STOP_LEVEL,
    RECOVERY_PCT_MODERATE,
    SAFETY_MAX_DURATION_CAUTION_MIN,
)
from src.coach.contracts import AthleteState, WorkoutProposal
from src.coach.rules.p1_safety import evaluate_safety
from src.coach.safety import clamp

AGGRESSIVE = WorkoutProposal(workout_type="interval", target_zone=5,
                             duration_min=90, distance_km=15.0,
                             structure="10×400/400")


def _state(**signals) -> AthleteState:
    """Состояние с данными и заданными сигналами (state with given safety signals)."""
    base = {
        "hrv_status": "normal", "rhr_status": "normal", "recovery_pct": 90,
        "ati_cti_ratio": 1.0, "acwr_ratio": 1.0, "consecutive_hard_days": 0,
        "pain_level": None, "pain_days": 0,
    }
    base.update(signals)
    from datetime import date
    return AthleteState(user_id=1, as_of=date.today(), data_confidence=0.9,
                        recovery_hours_left=0.0, signals=base)


# Каждый триггер × агрессивное предложение «interval 10×400 Z5 90мин» (DEV_PLAN §4)
TRIGGER_CASES = [
    # (signals-override, ожидание: allow, тип НЕ interval, max_zone)
    ({"rhr_status": "critical_elevated"}, False, "rest", None),
    ({"hrv_status": "very_low"}, True, None, 2),
    ({"hrv_status": "low"}, True, None, 2),
    ({"recovery_pct": RECOVERY_PCT_MODERATE - 1}, True, None, 2),
    ({"ati_cti_ratio": 1.6}, True, None, 3),
    ({"acwr_ratio": INJURY_RISK_THRESHOLDS["load_ratio_high"] + 0.1}, True, None, 3),
    ({"consecutive_hard_days": INJURY_RISK_THRESHOLDS["consecutive_hard_days"]}, True, None, 2),
    ({"pain_level": PAIN_STOP_LEVEL}, False, "rest", None),
    ({"pain_level": PAIN_CAUTION_LEVEL}, True, None, 2),
    ({"pain_days": 3}, True, None, 2),
]


@pytest.mark.parametrize("signals,allow,forced_type,max_zone", TRIGGER_CASES)
def test_each_trigger_clamps_aggressive_proposal(signals, allow, forced_type, max_zone):
    state = _state(**signals)
    verdict = evaluate_safety(state)
    p, clamped = clamp(AGGRESSIVE, verdict, state)

    assert clamped is True
    assert p.clamped is True
    assert any(r.rule == "p1_safety" for r in p.rationale)
    assert verdict.allow_training is allow
    if forced_type:
        assert p.workout_type == forced_type
    else:
        assert p.workout_type != "interval"          # агрессия не прошла
        assert p.target["max_zone"] <= max_zone


def test_no_triggers_aggressive_passes_after_recovery():
    """Здоровое состояние, часы вышли → интервалы проходят без урезания."""
    state = _state()
    verdict = evaluate_safety(state)
    p, clamped = clamp(AGGRESSIVE, verdict, state)
    assert clamped is False
    assert p.workout_type == "interval"
    assert p.target["max_zone"] == 5
    assert p.target["structure"] == "10×400/400"
    assert p.volume["duration_min"] == 90


def test_recovery_hours_shift_hard_to_easy():
    """Часы восстановления не вышли → интервалы сегодня превращаются в easy."""
    state = _state()
    state.recovery_hours_left = 12.0
    verdict = evaluate_safety(state)
    assert verdict.earliest_next_hard is not None
    p, clamped = clamp(AGGRESSIVE, verdict, state)
    assert clamped is True
    assert p.workout_type == "easy"
    assert p.earliest == verdict.earliest_next_hard


def test_forbidden_types_when_disallowed_anything_becomes_rest():
    """allow_training=False → ЛЮБОЕ предложение становится rest."""
    state = _state(pain_level=PAIN_STOP_LEVEL + 2)
    verdict = evaluate_safety(state)
    for wtype in ("interval", "tempo", "long", "easy", "recovery"):
        p, _ = clamp(WorkoutProposal(workout_type=wtype, target_zone=3), verdict, state)
        assert p.workout_type == "rest"
        assert p.volume == {}


def test_pain_caution_caps_duration():
    """Боль 3/10 → длительность усечена, дистанция пересчитана пропорционально."""
    state = _state(pain_level=PAIN_CAUTION_LEVEL)
    verdict = evaluate_safety(state)
    p, _ = clamp(WorkoutProposal(workout_type="easy", target_zone=2,
                                 duration_min=80, distance_km=12.0), verdict, state)
    assert p.volume["duration_min"] == SAFETY_MAX_DURATION_CAUTION_MIN
    assert p.volume["distance_km"] == 6.0  # 12 × (40/80)


def test_no_data_is_conservative():
    """Незнание = опасность: пустой state → потолок easy, не свобода."""
    empty = AthleteState(user_id=1)
    verdict = evaluate_safety(empty)
    assert "no_data" in verdict.triggered
    p, clamped = clamp(AGGRESSIVE, verdict, empty)
    assert clamped is True
    assert p.workout_type in ("rest", "recovery", "easy")
    assert p.target["max_zone"] <= 2


def test_clamp_total_on_garbage():
    """Фаззинг: мусорный тип/отрицательные объёмы → консервативный выход, не исключение."""
    state = _state(hrv_status="low")
    verdict = evaluate_safety(state)
    garbage = WorkoutProposal(workout_type="марафон по вертикали", target_zone=99,
                              duration_min=100000)
    p, clamped = clamp(garbage, verdict, state)
    assert clamped is True
    assert p.workout_type in ("rest", "recovery", "easy", "long")
    assert p.target["max_zone"] <= verdict.max_zone

    p2, c2 = clamp(None, verdict, state)
    assert p2.workout_type == "rest" and c2 is True


def test_clamp_idempotent():
    """clamp(clamp(x)) == clamp(x) по типу/зоне/объёму (idempotence)."""
    state = _state(hrv_status="low")
    verdict = evaluate_safety(state)
    p1, _ = clamp(AGGRESSIVE, verdict, state)
    reproposal = WorkoutProposal(
        workout_type=p1.workout_type, target_zone=p1.target["max_zone"],
        duration_min=p1.volume.get("duration_min"),
        distance_km=p1.volume.get("distance_km"),
    )
    p2, _ = clamp(reproposal, verdict, state)
    assert p2.workout_type == p1.workout_type
    assert p2.target["max_zone"] == p1.target["max_zone"]
    assert p2.volume == p1.volume


def test_finalize_persists_recommendation(athlete_with_history, db_session):
    """finalize(persist=True) пишет Recommendation со status=proposed."""
    from src.coach.prescriber import finalize
    from src.coach.state import assess_state
    from src.models import Recommendation

    state = assess_state(athlete_with_history.id, db=db_session)
    p = finalize(None, state, db=db_session, persist=True)
    assert p.source == "fallback"
    rec = db_session.query(Recommendation).filter_by(
        user_id=athlete_with_history.id).order_by(Recommendation.id.desc()).first()
    assert rec is not None
    assert rec.status == "proposed"
    assert rec.workout_type == p.workout_type


def test_finalize_persists_observability_columns(athlete_with_history, db_session):
    """C3-колонки наблюдаемости заполняются: source/clamped/safety/proposal."""
    from src.coach.contracts import WorkoutProposal
    from src.coach.prescriber import finalize
    from src.coach.state import assess_state
    from src.models import Recommendation

    state = assess_state(athlete_with_history.id, db=db_session)
    finalize(WorkoutProposal(workout_type="interval", target_zone=5, duration_min=60),
             state, db=db_session, persist=True, source="llm")
    rec = db_session.query(Recommendation).filter_by(
        user_id=athlete_with_history.id).order_by(Recommendation.id.desc()).first()
    assert rec.source == "llm"
    assert rec.clamped is not None
    assert rec.safety_json is not None
    assert rec.proposal_json["workout_type"] == "interval"  # ДО урезания


# --- Ветка целевого темпа (pace-lead clamp branch) — решение владельца 26.08.2026 ---

def _pace_proposal(pace: float = 5.5, wtype: str = "easy", zone: int = 2,
                   duration: int = 40) -> WorkoutProposal:
    return WorkoutProposal(workout_type=wtype, target_zone=zone,
                           duration_min=duration, distance_km=99.0,
                           target_pace_min_km=pace)


def test_pace_kept_without_ctx_distance_deterministic():
    """Валидный темп без оценок → сохранён; дистанция = duration/pace, не догадка LLM."""
    state = _state()
    verdict = evaluate_safety(state)
    p, clamped = clamp(_pace_proposal(pace=5.5, duration=40), verdict, state)
    assert clamped is False
    assert p.target["pace_min_km"] == 5.5
    assert p.volume["distance_km"] == round(40 / 5.5, 1)   # 7.3, а не 99.0


def test_pace_slowed_when_expected_hr_above_ceiling():
    """Расчётный пульс выше потолка зоны → темп замедлен до безопасного, clamped."""
    from src.coach.contracts import PaceClampContext

    state = _state()
    verdict = evaluate_safety(state)
    ctx = PaceClampContext(expected_hr=160, safe_pace_min_km=6.2, zone_ceiling_bpm=141)
    p, clamped = clamp(_pace_proposal(pace=5.0), verdict, state, pace_ctx=ctx)
    assert clamped is True
    assert p.target["pace_min_km"] == 6.2
    assert p.volume["distance_km"] == round(40 / 6.2, 1)   # дистанция от итогового темпа
    assert any("расчётный пульс" in r.reason for r in p.rationale)


def test_pace_dropped_when_no_safe_pace():
    """Пульс выше потолка, безопасный темп неизвестен → темп отброшен (HR-режим)."""
    from src.coach.contracts import PaceClampContext

    state = _state()
    verdict = evaluate_safety(state)
    ctx = PaceClampContext(expected_hr=160, safe_pace_min_km=None, zone_ceiling_bpm=141)
    p, clamped = clamp(_pace_proposal(pace=5.0), verdict, state, pace_ctx=ctx)
    assert clamped is True
    assert "pace_min_km" not in p.target


def test_pace_never_speeds_up():
    """safe_pace быстрее предложенного → темп НЕ ускоряется (clamp только сужает)."""
    from src.coach.contracts import PaceClampContext

    state = _state()
    verdict = evaluate_safety(state)
    ctx = PaceClampContext(expected_hr=160, safe_pace_min_km=4.5, zone_ceiling_bpm=141)
    p, _ = clamp(_pace_proposal(pace=5.5), verdict, state, pace_ctx=ctx)
    assert p.target["pace_min_km"] == 5.5              # max(5.5, 4.5)


def test_pace_dropped_on_structural_clamp():
    """Тип/зона урезаны безопасностью → ведущий темп отброшен (числа невалидны)."""
    state = _state(hrv_status="very_low")              # → max_zone 2, tempo даунгрейд
    verdict = evaluate_safety(state)
    p, clamped = clamp(_pace_proposal(pace=4.5, wtype="tempo", zone=4),
                       verdict, state)
    assert clamped is True
    assert "pace_min_km" not in p.target


def test_pace_sanity_bounds():
    """Темп вне абсолютных границ → отброшен (схема LLM — не гарантия)."""
    state = _state()
    verdict = evaluate_safety(state)
    for bad in (1.5, 15.0):
        p, clamped = clamp(_pace_proposal(pace=bad), verdict, state)
        assert clamped is True
        assert "pace_min_km" not in p.target


def test_pace_absent_for_rest():
    """rest → темп отсутствует вместе с остальным объёмом."""
    state = _state(pain_level=PAIN_STOP_LEVEL)
    verdict = evaluate_safety(state)
    p, _ = clamp(_pace_proposal(pace=5.5), verdict, state)
    assert p.workout_type == "rest"
    assert "pace_min_km" not in p.target
    assert p.volume == {}
