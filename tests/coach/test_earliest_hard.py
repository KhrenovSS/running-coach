# #306 (07.09.2026): «Интенсив — не раньше …» считается от тренировки и не дрейфует;
# на лёгкой карточке при малом остатке строка скрыта.
from datetime import datetime, timedelta, timezone

from src.coach.config import EARLIEST_HARD_HIDE_MIN, RECOVERY_HOURS_BY_TYPE
from src.coach.contracts import Prescription, SafetyVerdict
from src.coach.render import _show_earliest, render_prescription
from src.coach.rules.p1_safety import evaluate_safety
from src.coach.skills import recovery
from src.domain.models.base import utcnow
from tests.coach.test_safety_clamp import _state
from tests.helpers import build_training_session


def test_rule10_anchored_to_session_not_to_now():
    ready = datetime.now(timezone.utc) + timedelta(hours=5)
    state = _state(recovery_ready_at=ready.isoformat())
    v1 = evaluate_safety(state, now=datetime.now(timezone.utc))
    v2 = evaluate_safety(state, now=datetime.now(timezone.utc) + timedelta(minutes=40))
    assert "recovery_hours" in v1.triggered
    assert v1.earliest_next_hard == v2.earliest_next_hard == ready      # не плывёт между ходами
    # срок вышел → правило молчит, даже если recovery_hours_left в состоянии старое
    past = _state(recovery_ready_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat())
    assert "recovery_hours" not in evaluate_safety(past).triggered
    # без сигнала — прежний путь через recovery_hours_left
    legacy = _state(); legacy.recovery_hours_left = 3.0
    assert "recovery_hours" in evaluate_safety(legacy).triggered


def test_ready_at_from_last_session(empty_user, db_session):
    begin = utcnow() - timedelta(hours=2)
    build_training_session(db_session, empty_user.id, training_type="easy", avg_heart_rate=130,
                           begin_ts=begin)
    ready = recovery.ready_at(empty_user.id, db=db_session)
    expected = begin.replace(tzinfo=timezone.utc) + timedelta(hours=RECOVERY_HOURS_BY_TYPE["easy"])
    assert abs((ready - expected).total_seconds()) < 1
    assert recovery.hours_left(empty_user.id, db=db_session) == round(RECOVERY_HOURS_BY_TYPE["easy"] - 2, 1)


def _card(wtype, minutes_left):
    return Prescription(safety=SafetyVerdict(), workout_type=wtype,
                        earliest=datetime.now(timezone.utc) + timedelta(minutes=minutes_left),
                        target={"max_zone": 2}, volume={"duration_min": 40})


def test_easy_card_hides_near_expired_line_but_tempo_shows():
    assert _show_earliest(_card("easy", EARLIEST_HARD_HIDE_MIN - 5)) is False
    assert _show_earliest(_card("easy", EARLIEST_HARD_HIDE_MIN + 5)) is True
    assert _show_earliest(_card("tempo", 5)) is True
    assert "не раньше" not in render_prescription(_card("easy", 30))
    assert "не раньше" in render_prescription(_card("easy", 180))
