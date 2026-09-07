# #317 (07.09.2026): «длительная» короче LONG_RUN_MIN_MINUTES → ярлык easy детерминированно
# (карточка показывала «Длительный бег 40 мин»). (Short "long" is relabelled easy in finalize.)

import src.services.workout_insights as wi
from src.coach.contracts import WorkoutProposal
from src.coach.prescriber import finalize
from src.coach.state import assess_state
from src.config.constants import LONG_RUN_MIN_MINUTES


def _finalize(user, db, minutes):
    state = assess_state(user.id, db=db)
    return finalize(WorkoutProposal(workout_type="long", target_zone=2, duration_min=minutes),
                    state, db=db, source="llm")


def test_short_long_run_relabelled_easy(athlete_with_history, db_session, monkeypatch):
    monkeypatch.setattr(wi, "expected_pace_at_hr", lambda uid, hr, *, db, **kw: None)
    p = _finalize(athlete_with_history, db_session, LONG_RUN_MIN_MINUTES - 20)
    assert p.workout_type == "easy"
    assert p.volume["duration_min"] == LONG_RUN_MIN_MINUTES - 20      # длительность не тронута
    assert any(r.rule == "long_run_min" for r in p.rationale)         # след решения
    assert p.proposal.workout_type == "long"                           # что предлагали — сохранено


def test_real_long_run_keeps_label(athlete_with_history, db_session, monkeypatch):
    monkeypatch.setattr(wi, "expected_pace_at_hr", lambda uid, hr, *, db, **kw: None)
    p = _finalize(athlete_with_history, db_session, LONG_RUN_MIN_MINUTES + 10)
    assert p.workout_type == "long"
    assert not any(r.rule == "long_run_min" for r in p.rationale)


def test_code_trimmed_or_week_threshold_keeps_long(athlete_with_history, db_session, monkeypatch):
    """Урезанная кодом длительная (cap_long_run) и длительная под порогом недели остаются long."""
    monkeypatch.setattr(wi, "expected_pace_at_hr", lambda uid, hr, *, db, **kw: None)
    state = assess_state(athlete_with_history.id, db=db_session)
    trimmed = WorkoutProposal(workout_type="long", target_zone=2, duration_min=45, code_trimmed=True)
    assert finalize(trimmed, state, db=db_session, source="llm").workout_type == "long"
    short = WorkoutProposal(workout_type="long", target_zone=2, duration_min=50)
    assert finalize(short, state, db=db_session, source="llm",
                    long_min_minutes=45).workout_type == "long"        # порог недели 45 (hint)
    assert finalize(short, state, db=db_session, source="llm").workout_type == "easy"  # порог 60
