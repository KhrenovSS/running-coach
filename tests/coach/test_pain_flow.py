# Сквозной тест боли: запись → скилл → safety → рендер (pain flow) — DEV_PLAN §10
from datetime import datetime, timezone

from src.coach import orchestrator
from src.coach.rules.p1_safety import evaluate_safety
from src.coach.render import render_prescription
from src.coach.prescriber import finalize
from src.coach.state import assess_state
from src.models import TrainingFeedback, WellnessReport
from tests.coach.conftest import _unique_user
from tests.helpers import build_training_feedback, build_training_session


def test_pain_from_feedback_to_rest_card(db_session):
    """Боль 5/10 в feedback → скилл pain → P1 → карточка «Отдых» (end-to-end)."""
    user = _unique_user(db_session)
    session = build_training_session(db_session, user.id, training_type="easy")
    fb = build_training_feedback(db_session, session.id, user.id, rating=6)
    fb.pain_level = 5
    fb.pain_location = "knee"
    fb.pain_phase = "start"
    db_session.commit()

    state = assess_state(user.id, db=db_session)
    assert state.signals["pain_level"] == 5
    verdict = evaluate_safety(state)
    assert verdict.allow_training is False
    p = finalize(None, state, db=db_session)
    assert p.workout_type == "rest"
    assert "Отдых" in render_prescription(p)


def test_wellness_pain_counts_on_rest_days(db_session):
    """Боль в день без тренировки (wellness) тоже видна скиллу (rest-day pain)."""
    user = _unique_user(db_session)
    db_session.add(WellnessReport(user_id=user.id,
                                  report_date=datetime.now(timezone.utc).date(),
                                  pain_level=3, pain_location="knee"))
    db_session.commit()
    state = assess_state(user.id, db=db_session)
    assert state.signals["pain_level"] == 3
    assert "pain" not in state.missing


def test_evening_check_skipped_when_pain_recorded(db_session):
    """Вечерний вопрос пропускается, если боль сегодня уже записана (skip logic)."""
    user = _unique_user(db_session)
    assert orchestrator.evening_check_needed(user.id, db=db_session) is True
    db_session.add(WellnessReport(user_id=user.id,
                                  report_date=datetime.now(timezone.utc).date(),
                                  pain_level=0))
    db_session.commit()
    assert orchestrator.evening_check_needed(user.id, db=db_session) is False


def test_pain_recorded_via_feedback_skips_evening(db_session):
    """Боль из тренировочного feedback тоже гасит вечерний вопрос."""
    user = _unique_user(db_session)
    session = build_training_session(db_session, user.id)
    fb = build_training_feedback(db_session, session.id, user.id, rating=4)
    fb.pain_level = 0
    fb.pain_phase = "none"
    db_session.commit()
    assert orchestrator.evening_check_needed(user.id, db=db_session) is False


def test_initiative_roundtrip(db_session):
    """Инициатива: дефолт high, set/get через UserModel.params_json."""
    user = _unique_user(db_session)
    assert orchestrator.get_initiative(user.id, db=db_session) == "high"
    orchestrator.set_initiative(user.id, "off", db=db_session)
    assert orchestrator.get_initiative(user.id, db=db_session) == "off"
    orchestrator.set_initiative(user.id, "мусор", db=db_session)
    assert orchestrator.get_initiative(user.id, db=db_session) == "high"


def test_morning_verdict_and_chat_deterministic(athlete_with_history, db_session):
    """Вердикт, чат и разбор работают без LLM и не бросают исключений (C4 gate)."""
    from src.models import TrainingSession

    verdict_text = orchestrator.morning_verdict(athlete_with_history.id, db=db_session)
    assert "Состояние" in verdict_text
    chat_reply = orchestrator.handle_chat(athlete_with_history.id, "привет", db=db_session)
    assert chat_reply.source == "fallback"  # без ключа — детерминированный режим
    assert "состояние" in chat_reply.text.lower()

    session = db_session.query(TrainingSession).filter_by(
        user_id=athlete_with_history.id).first()
    review = orchestrator.on_workout_completed(
        athlete_with_history.id, session.id, db=db_session)
    assert "Разбор тренировки" in review
