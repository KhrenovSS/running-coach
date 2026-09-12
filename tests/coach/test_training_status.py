# Статус подопечного из данных (training_status, 12.09.2026): фаза returning/stabilizing/stable
# считается по полным неделям с пробежками и паузам, а не пишется в персоне промпта.
from datetime import date, datetime, timedelta, timezone

from src.coach import training_status as ts
from src.coach.config import STATUS_STABLE_WEEKS
from src.coach.turn_context import build_extras, status_phase
from tests.coach.conftest import _unique_user
from tests.helpers import build_training_session

TODAY = date(2026, 9, 12)  # суббота


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _runs(db, user_id, weeks_back: int, per_week: int, today: date = TODAY):
    """per_week пробежек в каждой из weeks_back полных недель перед текущей (noon UTC)
    + пробежки в текущей неделе (пн и вчера), чтобы ни days_off, ни разрыв в 7 дней
    не делали фазу returning."""
    for d in {_monday(today), today - timedelta(days=1)}:
        if d < today:
            build_training_session(db, user_id, training_type="easy", avg_heart_rate=130,
                                   begin_ts=datetime(d.year, d.month, d.day, 12,
                                                     tzinfo=timezone.utc))
    for w in range(1, weeks_back + 1):
        ws = _monday(today) - timedelta(weeks=w)
        for i in range(per_week):
            d = ws + timedelta(days=i * 2)
            build_training_session(db, user_id, training_type="easy", avg_heart_rate=130,
                                   begin_ts=datetime(d.year, d.month, d.day, 12, tzinfo=timezone.utc))


# --- pure ---

def test_find_pauses_and_continuity_pure():
    days = [date(2026, 8, 1), date(2026, 8, 3), date(2026, 8, 14), date(2026, 8, 16)]
    pauses = ts.find_pauses(days, date(2026, 8, 20))
    assert len(pauses) == 1 and pauses[0].days == 11 and pauses[0].ended_days_ago == 6
    weeks = [{"week_start": _monday(date(2026, 8, 3)), "session_count": 2},
             {"week_start": _monday(date(2026, 8, 10)), "session_count": 2}]
    # пауза 11 дн из недели 03.08 в неделю 10.08 рвёт серию: засчитана только последняя неделя
    assert ts.continuity_weeks(weeks, days) == 1
    # пауза 6 дн целиком внутри недели (пн → вс) серию не рвёт
    assert ts.continuity_weeks(weeks, [date(2026, 8, 3), date(2026, 8, 9), date(2026, 8, 11),
                                        date(2026, 8, 13)]) == 2
    assert ts.continuity_weeks(weeks, [date(2026, 8, 4), date(2026, 8, 6), date(2026, 8, 11),
                                        date(2026, 8, 13)]) == 2
    assert ts.continuity_weeks(weeks + [{"week_start": _monday(date(2026, 8, 17)),
                                         "session_count": 1}], days) == 0


def test_classify_phases_pure():
    assert ts.classify(continuity=6, days_off=2, last_pause=None) == ts.PHASE_STABLE
    assert ts.classify(continuity=STATUS_STABLE_WEEKS - 1, days_off=2,
                       last_pause=None) == ts.PHASE_STABILIZING
    assert ts.classify(continuity=6, days_off=6, last_pause=None) == ts.PHASE_RETURNING
    assert ts.classify(continuity=6, days_off=None, last_pause=None) == ts.PHASE_RETURNING
    # пауза 15 дн закончилась 5 дн назад — восстановление ≈ длине паузы, ещё returning
    assert ts.classify(continuity=6, days_off=1,
                       last_pause=ts.Pause(days=15, ended_days_ago=5)) == ts.PHASE_RETURNING
    assert ts.classify(continuity=6, days_off=1,
                       last_pause=ts.Pause(days=15, ended_days_ago=16)) == ts.PHASE_STABLE
    # короткая пауза 8 дн, уже отработана (days_off < 6) — серию считает continuity
    assert ts.classify(continuity=1, days_off=3,
                       last_pause=ts.Pause(days=8, ended_days_ago=3)) == ts.PHASE_STABILIZING


# --- DB ---

def test_status_stable_after_four_regular_weeks(db_session):
    user = _unique_user(db_session)
    _runs(db_session, user.id, weeks_back=4, per_week=3)
    st = ts.compute_status(user.id, db=db_session, today=TODAY)
    assert st["phase"] == ts.PHASE_STABLE
    assert st["continuity_weeks"] == 4 and st["weeks_with_runs_last_4"] == [3, 3, 3, 3]
    assert st["last_pause"] is None and st["restrictions"] == [] and st["active_injury"] is False
    block = ts.context_block(st)
    assert block["phase"] == "stable" and "стабильный" in block["summary"]
    assert not any(isinstance(v, str) and v[:4].isdigit() and "-" in v
                   for v in block.values())  # без ISO-дат в контексте


def test_status_stabilizing_with_three_weeks(db_session):
    user = _unique_user(db_session)
    _runs(db_session, user.id, weeks_back=3, per_week=2)
    st = ts.compute_status(user.id, db=db_session, today=TODAY)
    assert st["phase"] == ts.PHASE_STABILIZING and st["continuity_weeks"] == 3


def test_status_returning_after_long_pause(db_session):
    """Пауза 15 дн закончилась 3 дня назад: returning, хотя days_off мал."""
    user = _unique_user(db_session)
    _runs(db_session, user.id, weeks_back=6, per_week=3, today=TODAY - timedelta(days=22))
    d = TODAY - timedelta(days=3)
    build_training_session(db_session, user.id, training_type="easy",
                           begin_ts=datetime(d.year, d.month, d.day, 12, tzinfo=timezone.utc))
    st = ts.compute_status(user.id, db=db_session, today=TODAY)
    assert st["phase"] == ts.PHASE_RETURNING
    assert st["last_pause"] and st["last_pause"]["days"] >= 14
    assert st["days_off"] == 3


def test_status_returning_when_days_off_now(db_session):
    user = _unique_user(db_session)
    _runs(db_session, user.id, weeks_back=5, per_week=3, today=TODAY - timedelta(days=6))
    st = ts.compute_status(user.id, db=db_session, today=TODAY)
    assert st["days_off"] >= 6 and st["phase"] == ts.PHASE_RETURNING


def test_status_lists_illness_and_injury(db_session):
    from src.coach import concerns, illness
    user = _unique_user(db_session)
    _runs(db_session, user.id, weeks_back=4, per_week=3)
    illness._save(user.id, {"status": "sick", "kind": "cold", "since": TODAY.isoformat()},
                  db=db_session)
    concerns.refresh_from_pain(user.id, 3, db=db_session, today=TODAY)
    st = ts.compute_status(user.id, db=db_session, today=TODAY)
    assert any(r.startswith("illness") for r in st["restrictions"])
    assert st["active_injury"] is True and any(r.startswith("injury") for r in st["restrictions"])


def test_extras_carry_status_and_phase_helper(db_session):
    user = _unique_user(db_session)
    _runs(db_session, user.id, weeks_back=2, per_week=2)
    extras = build_extras(user.id, db=db_session)
    assert "athlete_status (computed)" in extras
    assert status_phase(extras) in (ts.PHASE_STABILIZING, ts.PHASE_RETURNING)
    assert status_phase(None) == ts.PHASE_STABLE
