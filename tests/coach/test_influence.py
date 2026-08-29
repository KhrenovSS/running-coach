# Тесты D7: каналы влияния разбора на будущие тренировки
# (D7 tests: review → future workouts influence channels) — DEV_PLAN §9 D-серия

from src.coach import orchestrator
from src.coach.llm.client import LLMResponse
from src.coach.prescriber import finalize
from src.coach.state import assess_state
from src.models import TrainingSession
from src.services.repositories_insights import InsightRepository
from tests.coach.fakes import ScriptedLLM

PLAIN_TURN = {"message": "Доброе утро! План простой.", "proposal": None,
              "followup_question": None, "log_suggestion": None}


def _finish_review(user_id, db, carry: str):
    sid = db.query(TrainingSession).filter_by(user_id=user_id).order_by(
        TrainingSession.begin_ts.desc()).first().id
    InsightRepository.upsert(user_id, sid, db=db)
    InsightRepository.finish(sid, db=db, source="llm", effort_match="harder",
                             assessment={"flags": ["hr_drift_high"]},
                             carry_forward=carry)
    return sid


def test_carry_forward_reaches_morning_context(athlete_with_history, db_session):
    """carry_forward вчерашнего разбора инлайнится в контекст утреннего хода."""
    _finish_review(athlete_with_history.id, db_session,
                   "жара выбила — завтра только лёгкий")
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=PLAIN_TURN)])
    orchestrator.handle_chat(athlete_with_history.id, "что сегодня делать?",
                             db=db_session, llm=llm, kind="morning")
    last_user = llm.calls[0]["messages"][-1]["content"]
    assert "recent_reviews" in last_user
    assert "жара выбила" in last_user
    assert "hr_drift_high" in last_user


def test_planned_workout_reaches_context(athlete_with_history, db_session):
    """Действующее назначение (for_date>=today) видно модели наутро."""
    state = assess_state(athlete_with_history.id, db=db_session)
    finalize(None, state, db=db_session, persist=True)  # Recommendation на сегодня
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=PLAIN_TURN)])
    orchestrator.handle_chat(athlete_with_history.id, "привет",
                             db=db_session, llm=llm)
    last_user = llm.calls[0]["messages"][-1]["content"]
    assert "planned_workout" in last_user


def test_weekly_sees_review_outcomes(athlete_with_history, db_session):
    """Недельный отчёт получает итоги разборов недели."""
    _finish_review(athlete_with_history.id, db_session, "колено стабильно")
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=PLAIN_TURN)])
    orchestrator.weekly_report(athlete_with_history.id, db=db_session, llm=llm)
    last_user = llm.calls[0]["messages"][-1]["content"]
    assert "recent_reviews" in last_user
    assert "колено стабильно" in last_user


def test_no_reviews_no_block(athlete_with_history, db_session):
    """Без завершённых разборов блок recent_reviews не инлайнится (нет шума)."""
    extras = orchestrator._build_extras(athlete_with_history.id, db=db_session)
    assert "recent_reviews (workout_insights)" not in extras
    assert "method_guides (search_guides)" not in extras  # без запроса — нет чанков


def test_review_extras_include_method_guides(athlete_with_history, db_session):
    """E3 (#242): разбор получает чанки методики по типу тренировки/боли."""
    from src.models import TrainingFeedback, TrainingSession
    sess = db_session.query(TrainingSession).filter_by(
        user_id=athlete_with_history.id).order_by(
        TrainingSession.begin_ts.desc()).first()
    db_session.add(TrainingFeedback(session_id=sess.id,
                                    user_id=athlete_with_history.id,
                                    rating=5, pain_level=2, pain_location="knee"))
    db_session.commit()
    extras = orchestrator._build_extras(athlete_with_history.id, db=db_session,
                                        session_id=sess.id)
    chunks = extras["method_guides (search_guides)"]
    assert 1 <= len(chunks) <= 2
    assert all({"guide", "heading", "text"} <= set(c) for c in chunks)
    # боль в фидбеке → чанк про колено в выдаче (pain → knee guide chunk)
    assert any("knee" in c["guide"] or "колен" in c["text"].lower() for c in chunks)


def test_weekly_extras_include_method_guides(athlete_with_history, db_session):
    """E3: недельный отчёт получает чанки про объём/прогрессию."""
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=PLAIN_TURN)])
    orchestrator.weekly_report(athlete_with_history.id, db=db_session, llm=llm)
    last_user = llm.calls[0]["messages"][-1]["content"]
    assert "method_guides" in last_user


def test_planned_workouts_list_all_days_with_days_ahead(athlete_with_history,
                                                        db_session):
    """Назначения на сегодня И на будущий день — оба в контексте, с days_ahead
    (инцидент 29.08: одиночный planned_workout затенял один из планов)."""
    from src.coach.contracts import WorkoutProposal

    state = assess_state(athlete_with_history.id, db=db_session)
    finalize(None, state, db=db_session, persist=True)   # rest на сегодня
    finalize(WorkoutProposal(workout_type="long", target_zone=2, duration_min=60,
                             for_days_ahead=2),
             state, db=db_session, persist=True)          # длительная на +2
    extras = orchestrator._build_extras(athlete_with_history.id, db=db_session)
    planned = extras["planned_workouts (recommendations)"]
    assert [p["days_ahead"] for p in planned] == [0, 2]
    assert planned[1]["type"] == "long"
    from datetime import date, timedelta
    from src.utils.timeutils import WEEKDAYS_RU
    assert planned[1]["weekday"] == WEEKDAYS_RU[
        (date.today() + timedelta(days=2)).weekday()]
