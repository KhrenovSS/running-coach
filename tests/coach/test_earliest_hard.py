# #306 (07.09.2026): «Интенсив — не раньше …» считается от тренировки и не дрейфует;
# на лёгкой карточке при малом остатке строка скрыта. #306 ч.2 (17.09.2026): то же для правил
# 11/18/19; на нехардовой карточке строка — только при качественном дне в плане недели.
from datetime import date, datetime, timedelta, timezone

import pytest

from src.coach.config import (DOWNHILL_EXTRA_H, EARLIEST_HARD_HIDE_MIN, HRR_POOR_RECOVERY_EXTRA_H,
                              QUALITY_VOLUME_EXTRA_H, RECOVERY_HOURS_BY_TYPE)
from src.coach.contracts import Prescription, SafetyVerdict
from src.coach.render import _show_earliest, render_prescription
from src.coach.rules.p1_safety import evaluate_safety
from src.coach.skills import recovery
from src.coach.state import assess_state
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
    """Качественный день в плане есть (hard_planned=True): на лёгкой строка при остатке ≥ 60 мин."""
    assert _show_earliest(_card("easy", EARLIEST_HARD_HIDE_MIN - 5), hard_planned=True) is False
    assert _show_earliest(_card("easy", EARLIEST_HARD_HIDE_MIN + 5), hard_planned=True) is True
    assert _show_earliest(_card("tempo", 5)) is True
    assert "не раньше" not in render_prescription(_card("easy", 30), hard_planned=True)
    assert "не раньше" in render_prescription(_card("easy", 180), hard_planned=True)


def test_easy_card_without_planned_hard_day_hides_line():
    """Решение владельца 17.09.2026: качественных дней в плане нет → на лёгкой/длительной строки нет
    (инцидент 16–17.09: «Интенсив — не раньше 19.09» на неделе без интенсива → «интенсив с субботы»);
    на качественной карточке — всегда."""
    assert _show_earliest(_card("easy", 180)) is False
    assert _show_earliest(_card("long", 180), hard_planned=False) is False
    assert "не раньше" not in render_prescription(_card("easy", 180))
    assert "не раньше" in render_prescription(_card("tempo", 180))


# --- #306 ч.2 (17.09.2026): правила 11/18/19 — срок от флагнутой тренировки, не от «сейчас» ---

@pytest.mark.parametrize("flag_key, at_key, rule, extra_h", [
    ("poor_interval_recovery", "poor_interval_recovery_at", "poor_interval_recovery",
     HRR_POOR_RECOVERY_EXTRA_H),
    ("quality_volume_exceeded_recent", "quality_volume_exceeded_at", "quality_volume_exceeded",
     QUALITY_VOLUME_EXTRA_H),
    ("downhill_load_recent", "downhill_load_at", "downhill_load", DOWNHILL_EXTRA_H),
])
def test_rules_11_18_19_anchored_to_flagged_session(flag_key, at_key, rule, extra_h):
    now = datetime(2026, 9, 17, 6, 30, tzinfo=timezone.utc)          # утро Чт (прод-инцидент)
    session_start = datetime(2026, 9, 15, 9, 23, tzinfo=timezone.utc)  # флагнутая пробежка Вт
    state = _state(**{flag_key: True, at_key: session_start.isoformat()})
    v1 = evaluate_safety(state, now=now)
    v2 = evaluate_safety(state, now=now + timedelta(hours=20))
    expected = session_start + timedelta(hours=extra_h)
    if expected > now:
        assert rule in v1.triggered
        assert v1.earliest_next_hard == expected                      # не «сейчас + часы»
    else:
        assert rule not in v1.triggered                               # срок вышел → молчит
    # ход позже: срок либо тот же, либо правило уже погасло — но никогда не уезжает вперёд
    assert v2.earliest_next_hard is None or v2.earliest_next_hard == expected
    assert rule not in v2.triggered or expected > now + timedelta(hours=20)


def test_rule19_expired_anchor_does_not_cap_zone():
    """Спуски позавчера: 24 ч вышли → правило 19 молчит целиком, max_zone не понижен."""
    now = datetime(2026, 9, 17, 6, 30, tzinfo=timezone.utc)
    state = _state(downhill_load_recent=True,
                   downhill_load_at=(now - timedelta(hours=DOWNHILL_EXTRA_H + 1)).isoformat())
    v = evaluate_safety(state, now=now)
    assert "downhill_load" not in v.triggered and v.max_zone == 5
    fresh = _state(downhill_load_recent=True, downhill_load_at=(now - timedelta(hours=2)).isoformat())
    vf = evaluate_safety(fresh, now=now)
    assert "downhill_load" in vf.triggered and vf.max_zone == 3


def test_rules_without_anchor_keep_legacy_now_based_deadline():
    now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    v = evaluate_safety(_state(poor_interval_recovery=True), now=now)
    assert v.earliest_next_hard == now + timedelta(hours=HRR_POOR_RECOVERY_EXTRA_H)


def test_state_carries_flag_anchor_instants(empty_user, db_session):
    """state.signals: `*_at` = начало последней флагнутой тренировки в окне; без флага — None."""
    from src.models import WorkoutInsight
    begin = utcnow() - timedelta(hours=30)
    s = build_training_session(db_session, empty_user.id, training_type="easy", avg_heart_rate=130,
                               begin_ts=begin)
    db_session.add(WorkoutInsight(user_id=empty_user.id, session_id=s.id, status="done",
                                  computed_json={"flags": ["poor_interval_recovery"]}))
    db_session.commit()
    sig = assess_state(empty_user.id, db=db_session).signals
    assert sig["poor_interval_recovery"] is True
    anchored = datetime.fromisoformat(sig["poor_interval_recovery_at"])
    assert abs((anchored - begin.replace(tzinfo=timezone.utc)).total_seconds()) < 1
    assert sig["downhill_load_at"] is None and sig["quality_volume_exceeded_at"] is None
    v = evaluate_safety(assess_state(empty_user.id, db=db_session))
    assert v.earliest_next_hard is not None
    assert abs((v.earliest_next_hard - (anchored + timedelta(hours=HRR_POOR_RECOVERY_EXTRA_H)))
               .total_seconds()) < 1


def _rec(db, user_id, for_date, wtype, status="planned"):
    from src.models import Recommendation
    row = Recommendation(user_id=user_id, for_date=for_date, workout_type=wtype,
                         target_json={"max_zone": 2}, volume_json={"duration_min": 40},
                         status=status, source="llm", clamped=False)
    db.add(row)
    db.commit()
    return row


def test_hard_day_planned_looks_at_active_rows_of_current_week(empty_user, db_session):
    from src.coach.planning import hard_day_planned
    today = date(2026, 9, 17)                                   # Чт
    uid = empty_user.id
    assert hard_day_planned(uid, db=db_session, today=today) is False
    _rec(db_session, uid, today, "easy")
    _rec(db_session, uid, date(2026, 9, 20), "long")
    assert hard_day_planned(uid, db=db_session, today=today) is False       # только лёгкое/длительная
    _rec(db_session, uid, date(2026, 9, 12), "tempo")                       # прошлая неделя
    _rec(db_session, uid, date(2026, 9, 22), "interval")                    # следующая неделя
    assert hard_day_planned(uid, db=db_session, today=today) is False
    old = _rec(db_session, uid, date(2026, 9, 19), "tempo", status="superseded")
    assert hard_day_planned(uid, db=db_session, today=today) is False       # погашенная не считается
    _rec(db_session, uid, date(2026, 9, 19), "tempo")
    assert hard_day_planned(uid, db=db_session, today=today) is True
    _rec(db_session, uid, date(2026, 9, 19), "easy", status="adjusted")     # позже заменили на лёгкую
    assert hard_day_planned(uid, db=db_session, today=today) is False
    assert old.status == "superseded"
