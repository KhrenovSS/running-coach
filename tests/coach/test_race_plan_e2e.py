# Старт из календаря в плане недели (#243 ч.1, 17.09.2026): неделя старта — race на день гонки кодом,
# качества нет, теста ПАНО нет, шапка «неделя старта»; закрытый день старта — заметка.
from datetime import datetime, timedelta, timezone

from src.coach import planning, races
from src.coach.llm.client import LLMResponse
from src.coach.llm.schemas import RaceReport
from src.coach.weekly_plan import generate_weekly_plan
from src.models import Recommendation
from tests.coach.fakes import ScriptedLLM
from tests.coach.test_lthr_plan import _stable_athlete
from tests.coach.test_weekly_plan import PLAN_TURN, _sunday

_ITEMS = [
    {"workout_type": "easy", "target_zone": 2, "duration_min": 40, "for_days_ahead": 1},
    {"workout_type": "tempo", "target_zone": 3, "duration_min": 40, "for_days_ahead": 3},
    {"workout_type": "easy", "target_zone": 2, "duration_min": 40, "for_days_ahead": 5},
    {"workout_type": "long", "target_zone": 2, "duration_min": 70, "for_days_ahead": 6},
]


def test_weekly_plan_places_race_in_race_week(db_session):
    user = _stable_athlete(db_session)
    sunday = _sunday(user)
    race_day = sunday.date() + timedelta(days=6)                       # сб планируемой недели
    races.record_race(RaceReport(status="add", date=race_day.isoformat(), distance_km=10.0, label="Десятка"),
                      user.id, db=db_session, now=sunday)
    t = planning.week_targets(user.id, db=db_session, today=sunday.date(), now=sunday)
    assert t["goal"]["phase"] == "race_week" and t["race_day_ahead"] == 6 and t["hard_days_max"] == 0
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=dict(PLAN_TURN, weekly_plan=_ITEMS))])
    text = generate_weekly_plan(user.id, db=db_session, llm=llm, now=sunday)
    assert text is not None and "неделя старта (Десятка" in text and "🏁 День +6: старт Десятка 10 км" in text
    assert "Тест ПАНО" not in text
    rows = {(r.for_date - sunday.date()).days: r for r in db_session.query(Recommendation).filter_by(
        user_id=user.id, status="planned").all()}
    assert rows[6].workout_type == "race" and rows[6].target_json["race"]["distance_km"] == 10.0
    assert rows[6].volume_json.get("distance_km") == 10.0
    assert rows[5].workout_type == "easy" and rows[3].workout_type != "tempo"    # накануне лёгкий; качества в неделю старта нет
    assert '"phase": "race_week"' in str(llm.calls[0])                             # промпт видел фазу
    # /week рендерит сохранённую мету с целью
    from src.coach.week_view import week_targets_stored
    meta = week_targets_stored(user.id, db=db_session, week_start=sunday.date() + timedelta(days=1))
    assert meta["goal"]["phase"] == "race_week" and meta["goal_phase"] == "race_week"


def test_weekly_plan_race_day_closed_by_athlete_gets_note(db_session):
    user = _stable_athlete(db_session)
    sunday = _sunday(user)
    race_day = sunday.date() + timedelta(days=6)
    races.record_race(RaceReport(status="add", date=race_day.isoformat(), distance_km=10.0),
                      user.id, db=db_session, now=sunday)
    planning.set_availability(user.id, db=db_session, weekdays=[0, 2, 4])     # сб недоступна
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=dict(PLAN_TURN, weekly_plan=_ITEMS[:1]))])
    text = generate_weekly_plan(user.id, db=db_session, llm=llm, now=sunday)
    assert text is not None and "День старта закрыт" in text
    assert not db_session.query(Recommendation).filter_by(user_id=user.id, workout_type="race").count()
    # окно доступности пережило /plan (баг до 17.09.2026)
    assert planning.availability(user.id, db=db_session)["weekdays"] == [0, 2, 4]
