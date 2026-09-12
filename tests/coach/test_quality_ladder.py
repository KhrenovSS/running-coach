# Лестница качественных дней (quality_ladder, 12.09.2026): 1 → 2 → 3 по переносимости.
from datetime import date, datetime, timedelta, timezone

from src.coach import quality_ladder as ql
from src.coach.training_status import PHASE_STABILIZING, PHASE_STABLE
from tests.coach.conftest import _unique_user
from tests.helpers import build_daily_metrics, build_training_feedback, build_training_session

WEEK_START = date(2026, 9, 14)  # понедельник планируемой недели
W1 = WEEK_START - timedelta(days=7)
W2 = WEEK_START - timedelta(days=14)


def _s(d: date, tolerated):
    return {"date": d, "tolerated": tolerated}


def _level(sessions, phase=PHASE_STABLE, injury=False, run_days=5):
    return ql.ladder_level(sessions, phase=phase, active_injury=injury,
                           run_days_max=run_days, week_start=WEEK_START)[0]


def test_tolerance_of_signals():
    assert ql.tolerance_of(rating=None, pain_level=None, flags=None, hr_z=None,
                           next_recovery_pct=None, next_hrv_very_low=None) == (None, [])
    ok, bad = ql.tolerance_of(rating=5, pain_level=0, flags=["low_cadence"], hr_z=0.4,
                              next_recovery_pct=85, next_hrv_very_low=False)
    assert ok is True and bad == []
    ok, bad = ql.tolerance_of(rating=9, pain_level=0, flags=["hr_above_baseline"], hr_z=2.3,
                              next_recovery_pct=40, next_hrv_very_low=True)
    assert ok is False and len(bad) == 5


def test_ladder_level_one_by_default():
    assert _level([]) == 1
    good3 = [_s(W2 + timedelta(days=1), True), _s(W1 + timedelta(days=1), True),
             _s(W1 + timedelta(days=4), True)]
    assert _level(good3, phase=PHASE_STABILIZING) == 1          # статус не stable
    assert _level(good3, injury=True) == 1                      # активная травма
    assert _level(good3[:2]) == 1                               # < 3 качественных в окне
    # качественные не каждую из двух последних недель
    assert _level([_s(W2 - timedelta(days=5), True), _s(W1 + timedelta(days=1), True),
                   _s(W1 + timedelta(days=4), True)]) == 1


def test_ladder_level_two_and_three():
    good3 = [_s(W2 + timedelta(days=1), True), _s(W1 + timedelta(days=1), True),
             _s(W1 + timedelta(days=4), True)]
    assert _level(good3) == 2
    two_by_two = [_s(W2 + timedelta(days=1), True), _s(W2 + timedelta(days=4), True),
                  _s(W1 + timedelta(days=1), True), _s(W1 + timedelta(days=4), True)]
    assert _level(two_by_two, run_days=6) == 3
    # три дня требуют ≥ 5 беговых: 4 → потолок 2
    assert _level(two_by_two, run_days=4) == 2
    assert _level(two_by_two, run_days=3) == 1


def test_ladder_downgrade_on_last_bad_and_share():
    mixed = [_s(W2 + timedelta(days=1), True), _s(W1 + timedelta(days=1), True),
             _s(W1 + timedelta(days=4), False)]
    level, reasons = ql.ladder_level(mixed, phase=PHASE_STABLE, active_injury=False,
                                     run_days_max=5, week_start=WEEK_START)
    assert level == 1 and any("перенесено 2 из 3" in r for r in reasons)  # доля 2/3 < 0.75
    four = [_s(W2 + timedelta(days=1), True), _s(W2 + timedelta(days=4), True),
            _s(W1 + timedelta(days=1), True), _s(W1 + timedelta(days=4), False)]
    assert _level(four) == 1                                          # 3/4 ≥ 0.75 → 2, последняя плохая → 1
    unknown = [_s(W2 + timedelta(days=1), None), _s(W1 + timedelta(days=1), None),
               _s(W1 + timedelta(days=4), None)]
    assert _level(unknown) == 2                                       # нет сигналов — не против


def test_quality_sessions_from_db_read_signals(db_session):
    user = _unique_user(db_session)
    d = W1 + timedelta(days=1)
    s = build_training_session(db_session, user.id, training_type="tempo", avg_heart_rate=165,
                               begin_ts=datetime(d.year, d.month, d.day, 12, tzinfo=timezone.utc))
    build_training_feedback(db_session, s.id, user.id, rating=9)
    build_daily_metrics(db_session, user.id, metric_date=d + timedelta(days=1), recovery_pct=95)
    # лёгкая в окне — не качественная
    e = d + timedelta(days=2)
    build_training_session(db_session, user.id, training_type="easy", avg_heart_rate=130,
                           begin_ts=datetime(e.year, e.month, e.day, 12, tzinfo=timezone.utc))
    rows = ql.quality_sessions(user.id, db=db_session, today=WEEK_START)
    assert len(rows) == 1 and rows[0]["tolerated"] is False and "rpe 9" in rows[0]["bad"]
    out = ql.quality_ladder(user.id, db=db_session, today=WEEK_START, phase=PHASE_STABLE,
                            active_injury=False, run_days_max=5, week_start=WEEK_START)
    assert out["level"] == 1 and out["sessions_considered"] == 1 and out["judged"] == 1
    assert out["last_bad_days_ago"] == (WEEK_START - d).days
