# Тесты генерации недельного плана (Weekly plan generation tests)
from datetime import date, timedelta

from src.coach.llm.client import LLMResponse
from src.coach.weekly_plan import generate_weekly_plan
from src.models import CoachMessage, Recommendation, UserModel
from tests.coach.conftest import _unique_user
from tests.coach.fakes import FailingLLM, ScriptedLLM

PLAN_TURN = {
    "message": "Неделя роста: аккуратно наращиваем объём, одна длительная.",
    "proposal": None,
    "followup_question": None,
    "log_suggestion": None,
    "weekly_plan": [
        {"workout_type": "easy", "target_zone": 2, "duration_min": 40,
         "for_days_ahead": 2},
        {"workout_type": "easy", "target_zone": 2, "duration_min": 45,
         "for_days_ahead": 4},
        {"workout_type": "rest", "target_zone": 1, "for_days_ahead": 5},
        {"workout_type": "long", "target_zone": 2, "duration_min": 70,
         "for_days_ahead": 7},
        {"workout_type": "easy", "target_zone": 2, "duration_min": 30,
         "for_days_ahead": 0},   # день 0 — отбрасывается (план только вперёд)
        {"workout_type": "easy", "target_zone": 2, "duration_min": 50,
         "for_days_ahead": 4},   # дубль дня — побеждает последний
    ],
}


def test_generate_weekly_plan_persists_rows(athlete_with_history, db_session):
    """План: строки status='planned' на будущие даты, rest/день-0/дубли чищены,
    карточка недели, kind='plan', мета мезоцикла в params_json."""
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=PLAN_TURN)])
    uid = athlete_with_history.id
    text = generate_weekly_plan(uid, db=db_session, llm=llm)
    assert text is not None

    rows = db_session.query(Recommendation).filter_by(
        user_id=uid, status="planned").all()
    assert len(rows) == 3                                 # дни 2, 4(дубль→50мин), 7
    assert all(r.for_date > date.today() - timedelta(days=1) for r in rows)
    by_day = {r.for_date: r for r in rows}
    day4 = [r for r in rows if r.volume_json.get("duration_min") == 50.0]
    assert len(day4) == 1                                 # дубль дня схлопнут
    assert not any(r.workout_type == "rest" for r in rows)

    assert "План на неделю" in text
    assert "мезоцикла" in text and "Остальные дни — отдых" in text
    msg = db_session.query(CoachMessage).filter_by(
        user_id=uid, kind="plan", role="assistant").first()
    assert msg is not None and msg.meta_json["days"] == 3

    um = db_session.query(UserModel).filter_by(user_id=uid).first()
    meta = um.params_json["week_plan"]
    assert meta["mesocycle_week"] >= 1 and meta["target_km"] > 0


def test_generate_weekly_plan_llm_failure_returns_none(athlete_with_history,
                                                       db_session):
    """LLM недоступна → None и НИ ОДНОЙ строки плана (fallback-плана нет)."""
    uid = athlete_with_history.id
    before = db_session.query(Recommendation).filter_by(user_id=uid).count()
    assert generate_weekly_plan(uid, db=db_session, llm=FailingLLM()) is None
    assert db_session.query(Recommendation).filter_by(
        user_id=uid).count() == before


def test_generate_weekly_plan_empty_list_returns_none(athlete_with_history,
                                                      db_session):
    """weekly_plan=null от LLM → None (план не создан)."""
    turn = dict(PLAN_TURN, weekly_plan=None)
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=turn)])
    assert generate_weekly_plan(athlete_with_history.id,
                                db=db_session, llm=llm) is None


def test_weekly_plan_field_dropped_in_chat(athlete_with_history, db_session):
    """weekly_plan в обычном чате дропается (как assessment вне разбора)."""
    from src.coach import orchestrator

    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=PLAN_TURN)])
    uid = athlete_with_history.id
    before = db_session.query(Recommendation).filter_by(user_id=uid).count()
    reply = orchestrator.handle_chat(uid, "привет", db=db_session, llm=llm)
    assert reply.source == "llm"
    assert db_session.query(Recommendation).filter_by(
        user_id=uid).count() == before                    # план не записан
