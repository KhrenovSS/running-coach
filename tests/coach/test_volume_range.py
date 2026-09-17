# Диапазон времени ровного дня и допуск объёма по состоянию (решения владельца 17.09.2026):
# низ производный (volume_range.duration_low) и считается в finalize; карточки «30–40 мин · ≈4.3–5.7 км»;
# факт внутри диапазона = по плану; проза с числом из диапазона не режется; допуск дня 15 %/5 % по
# fatigue_signals с гистерезисом. Даты фиксированные (#328/#332).
from datetime import date, datetime, timezone
from types import SimpleNamespace

from src.coach import planning
from src.coach.config import (
    DAY_CAP_MIN_CUT_MIN,
    DAY_VOLUME_TOLERANCE_RELAXED_PCT,
    PLAN_EASY_MIN_MINUTES,
    WEEK_VOLUME_TOLERANCE_PCT,
)
from src.coach.contracts import AthleteState, Prescription, SafetyVerdict, WorkoutProposal, WorkoutSegment
from src.coach.day_caps import cap_day_volume, context_block, day_targets, finalize_with_caps
from src.coach.numeric_check import check_prose
from src.coach.planning_safety import fatigue_signals, volume_hold
from src.coach.prescriber import finalize
from src.coach.render import render_prescription, render_prescription_short
from src.coach.render_week import plan_change_line
from src.coach.volume_range import duration_low, km_label, km_range, minutes_label
from src.coach.rules.p1_safety import evaluate_safety
from tests.coach.test_day_caps import PACE, _prescription, _targets, capped_world  # noqa: F401 — фикстура

THU = date(2026, 9, 17)


def _state(**signals) -> AthleteState:
    base = {"hrv_status": "normal", "rhr_status": "normal", "recovery_pct": 90, "ati_cti_ratio": 1.0,
            "acwr_ratio": 1.0, "consecutive_hard_days": 0, "pain_level": None, "pain_days": 0,
            "days_since_quality": None, "quality_days_7d": 0, "post_race_days_left": 0, "days_off": None,
            "consecutive_run_days": 0}
    base.update(signals)
    return AthleteState(user_id=1, as_of=THU, data_confidence=0.9, recovery_hours_left=0.0, signals=base)


# --- низ диапазона: правило ---

def test_duration_low_rule():
    assert duration_low("easy", 40, has_segments=False, has_pace=False) == 30.0
    assert duration_low("easy", 35, has_segments=False, has_pace=False) == 30.0      # пол 30
    assert duration_low("easy", 30, has_segments=False, has_pace=False) is None      # точка
    assert duration_low("recovery", 48, has_segments=False, has_pace=False) == 36.0
    assert duration_low("long", 75, has_segments=False, has_pace=False, long_min_minutes=60) == 64.0
    assert duration_low("long", 60, has_segments=False, has_pace=False, long_min_minutes=60) is None
    assert duration_low("long", 75, has_segments=False, has_pace=False, long_min_minutes=50) == 64.0
    for bad in (("easy", 40, True, False), ("easy", 40, False, True), ("tempo", 40, False, False),
                ("race", 40, False, False), ("rest", None, False, False)):
        t, d, seg, pace = bad
        assert duration_low(t, d, has_segments=seg, has_pace=pace) is None


def test_labels_and_km_range():
    v = {"duration_min": 40.0, "duration_min_low": 30.0}
    pred = {"pace_min_km": 7.05, "distance_km": 5.7}
    assert minutes_label(v) == "30–40 мин" and minutes_label({"duration_min": 40.0}) == "40 мин"
    assert minutes_label({}) is None
    assert km_range(v, pred) == (4.3, 5.7) and km_range({"duration_min": 40.0}, pred) is None
    assert km_label(v, pred) == "≈4.3–5.7 км" and km_label({"duration_min": 40.0}, pred) == "≈5.7 км"
    assert km_label(v, {}) is None


# --- finalize пишет низ; кэпы пересчитывают его от урезанного верха ---

def test_finalize_writes_low_for_plain_days_only():
    state = _state()
    easy = finalize(WorkoutProposal(workout_type="easy", target_zone=2, duration_min=40), state, source="llm")
    assert easy.volume["duration_min_low"] == 30.0 and easy.volume["duration_min"] == 40
    long = finalize(WorkoutProposal(workout_type="long", target_zone=2, duration_min=75), state, source="llm")
    assert long.volume["duration_min_low"] == 64.0
    strides = finalize(WorkoutProposal(workout_type="easy", target_zone=2, duration_min=40, segments=[
        WorkoutSegment(role="steady", amount_value=35, target_zone=2),
        WorkoutSegment(role="work", amount_kind="sec", amount_value=20, repeat=4, target_zone=4)]),
        state, source="llm")
    assert "duration_min_low" not in strides.volume
    paced = finalize(WorkoutProposal(workout_type="easy", target_zone=2, duration_min=40, target_pace_min_km=6.5),
                     state, source="llm")
    assert "duration_min_low" not in paced.volume
    rest = finalize(WorkoutProposal(workout_type="rest", target_zone=1), state, source="llm")
    assert rest.volume == {}
    short = finalize(WorkoutProposal(workout_type="easy", target_zone=2, duration_min=30), state, source="llm")
    assert "duration_min_low" not in short.volume


def test_finalize_with_caps_recomputes_low_from_capped_upper(capped_world, db_session):
    """Кэп режет верх 60 → 43 (остаток 6 км × 1.05 при 8.6 км/60 мин): низ пересчитан от урезанного верха
    (32 = 75 % от 43), а не от исходных 60 (было бы 45)."""
    from src.coach.state import assess_state
    user, today = capped_world
    state = assess_state(user.id, db=db_session)
    t = _targets(today, remaining_km=6.0, day_volume_tolerance_pct=WEEK_VOLUME_TOLERANCE_PCT)
    p, notes = finalize_with_caps(WorkoutProposal(workout_type="easy", target_zone=2, duration_min=60), state,
                                  db=db_session, now=datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc),
                                  source="llm", targets=t)
    assert p.volume["duration_min"] == 43 and p.volume["duration_min_low"] == 32.0 and notes


# --- рендер ---

def test_render_cards_show_range():
    state = _state()
    p = finalize(WorkoutProposal(workout_type="easy", target_zone=2, duration_min=40), state, source="llm")
    p.predicted = {"pace_min_km": 7.05, "distance_km": 5.7, "hr_ceiling": 138}
    full = render_prescription(p, max_hr=177)
    assert "30–40 мин" in full and "Ориентир по твоим пробежкам: ~7:03/км → ≈4.3–5.7 км" in full
    short = render_prescription_short(p, max_hr=177)
    assert "30–40 мин · ~7:03/км ≈ 4.3–5.7 км" in short
    old = SimpleNamespace(workout_type="easy", volume_json={"duration_min": 40.0, "duration_min_low": 30.0})
    rest = finalize(WorkoutProposal(workout_type="rest", target_zone=1), state, source="llm")
    assert plan_change_line(THU, rest, old) == "Изменил план на Чт 17.09: 🛌 Отдых (было: 🟢 Лёгкий бег · 30–40 мин)"
    # старая строка без низа — точка
    assert plan_change_line(THU, rest, SimpleNamespace(workout_type="easy", volume_json={"duration_min": 40.0})) \
        .endswith("(было: 🟢 Лёгкий бег · 40 мин)")


def test_numeric_check_accepts_numbers_inside_range():
    p = Prescription(safety=SafetyVerdict(), workout_type="easy", target={"max_zone": 2},
                     volume={"duration_min": 40.0, "duration_min_low": 30.0},
                     predicted={"pace_min_km": 7.05, "distance_km": 5.7})
    assert check_prose("сегодня 35 мин, около 5 км", p, max_hr=177) == []
    assert check_prose("хватит 30 мин и 4.3 км", p, max_hr=177) == []
    found = check_prose("давай 50 мин и 9 км", p, max_hr=177)
    assert len(found) == 2 and "30–40" in found[1]


# --- план vs факт ---

def test_plan_vs_actual_inside_range_is_on_plan():
    from src.analysis.session_metrics import FLAG_PLAN_VOLUME, plan_vs_actual, time_in_zones
    zones = time_in_zones([i * 60.0 for i in range(34)], [130] * 34, 177)
    plan = {"type": "easy", "max_zone": 2, "duration_min": 40, "duration_min_low": 30,
            "baseline": {"type": "easy", "duration_min": 40, "duration_min_low": 30}}
    r = plan_vs_actual(plan, "easy", 4.8, 34.0, zones, volume_tol=0.15, intensity_tol=0.10)
    assert r["within_range"] is True and r["volume_ratio"] == 1.0 and r["volume_ratio_raw"] == 0.85
    assert r["baseline"]["volume_ratio"] == 1.0 and r["flags"] == []
    over = plan_vs_actual(plan, "easy", 7.5, 52.0, zones, volume_tol=0.15, intensity_tol=0.10)
    assert over["within_range"] is False and over["volume_ratio"] == 1.3 and FLAG_PLAN_VOLUME in over["flags"]
    plain = plan_vs_actual({"type": "easy", "max_zone": 2, "duration_min": 40}, "easy", 4.8, 34.0, zones,
                           volume_tol=0.15, intensity_tol=0.10)
    assert "within_range" not in plain and plain["volume_ratio"] == 0.85


def test_week_plan_review_ignores_low_only_difference(athlete_with_history, db_session):
    """Строка до релиза (без низа) и после (с низом) при том же верхе — не «переторговано в чате»."""
    from datetime import timedelta
    from src.models import Recommendation
    from src.utils.timeutils import user_now
    uid = athlete_with_history.id
    today = user_now(athlete_with_history).date()
    monday = today - timedelta(days=today.weekday())
    d = monday                                         # текущая неделя — сверка по умолчанию идёт по ней
    for vol, status in (({"duration_min": 40.0}, "planned"),
                        ({"duration_min": 40.0, "duration_min_low": 30.0}, "confirmed")):
        db_session.add(Recommendation(user_id=uid, for_date=d, workout_type="easy", status=status,
                                      target_json={"max_zone": 2}, volume_json=vol, source="llm"))
    db_session.commit()
    review = planning.week_plan_review(uid, db=db_session)
    day = next(x for x in review["days"] if x["date"] == d.isoformat())
    assert not day.get("changed_in_chat")


# --- допуск по состоянию ---

def test_fatigue_signals_and_volume_hold_semantics():
    clean = SafetyVerdict(triggered=[])
    dist = SafetyVerdict(triggered=["poor_interval_recovery", "easy_runs_too_hard", "downhill_load"])
    tired = SafetyVerdict(triggered=["easy_runs_too_hard", "hrv_low"])
    assert fatigue_signals(clean) == [] and fatigue_signals(dist) == [] and fatigue_signals(tired) == ["hrv_low"]
    assert volume_hold(clean) is True and volume_hold(dist) is False and volume_hold(tired) is True


def test_cap_day_volume_tolerance_and_hysteresis_incident_17_09():
    """17.09: остаток 18.2, назначено 15.7, план 40 мин (≈5.7 км). 5 % → пол 30; 15 % → срез 4 мин < 10 → нет."""
    proposal = WorkoutProposal(workout_type="easy", target_zone=2, duration_min=40)
    p = _prescription(40, when=THU, workout_type="easy")                     # 40/7 ≈ 5.7 км
    strict = _targets(THU, remaining_km=18.2, day_volume_tolerance_pct=WEEK_VOLUME_TOLERANCE_PCT,
                      day_volume_tolerance_reason=["hrv_low"])
    capped, note = cap_day_volume(proposal, p, strict, other_planned_km=15.7)
    assert capped.duration_min == PLAN_EASY_MIN_MINUTES and "допуск 5 %" in note and "hrv_low" in note
    relaxed = _targets(THU, remaining_km=18.2, day_volume_tolerance_pct=DAY_VOLUME_TOLERANCE_RELAXED_PCT)
    assert cap_day_volume(proposal, p, relaxed, other_planned_km=15.7) == (None, None)
    # гистерезис при строгом допуске: 35 мин при остатке, дающем пол 30 (срез 5 < 10) — не режем
    p35 = _prescription(35, when=THU, workout_type="easy")
    assert cap_day_volume(WorkoutProposal(workout_type="easy", target_zone=2, duration_min=35), p35,
                          _targets(THU, remaining_km=18.2, day_volume_tolerance_pct=WEEK_VOLUME_TOLERANCE_PCT),
                          other_planned_km=15.7) == (None, None)
    # большое превышение при 15 % режется как раньше
    big = _prescription(90, when=THU, workout_type="easy")
    capped, _ = cap_day_volume(WorkoutProposal(workout_type="easy", target_zone=2, duration_min=90), big, relaxed,
                               other_planned_km=15.7)
    assert capped is not None and 90 - capped.duration_min >= DAY_CAP_MIN_CUT_MIN


def test_day_targets_pick_tolerance_by_fatigue(capped_world, db_session, monkeypatch):
    user, today = capped_world
    now = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
    dist = SafetyVerdict(triggered=["easy_runs_too_hard", "downhill_load"])
    t = day_targets(user.id, dist, db=db_session, now=now)
    assert t["day_volume_tolerance_pct"] == DAY_VOLUME_TOLERANCE_RELAXED_PCT and t["day_volume_tolerance_reason"] == []
    tired = day_targets(user.id, SafetyVerdict(triggered=["hrv_low", "easy_runs_too_hard"]), db=db_session, now=now)
    assert tired["day_volume_tolerance_pct"] == WEEK_VOLUME_TOLERANCE_PCT and tired["day_volume_tolerance_reason"] == ["hrv_low"]
    block = context_block(t)
    assert block["day_volume_tolerance_pct"] == DAY_VOLUME_TOLERANCE_RELAXED_PCT
    assert block["unallocated_km"] == round(10.0 * 1.15 - (t.get("planned_km_remaining") or 0.0), 1)
