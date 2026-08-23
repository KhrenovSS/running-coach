# Gate Этапа 0: каркас модуля коуча ставится и импортируется, таблицы создаются.
# Stage-0 gate: coach skeleton imports, contracts work, 4 tables exist, stubs raise.

import pytest

from src.models import SessionLocal, Recommendation, PredictionLog, UserModel, Lesson
from src.coach.contracts import (
    AthleteState, Prescription, ReasoningStep, SafetyVerdict, SkillResult, WorkoutProposal,
)
from tests.helpers import make_user


def test_coach_tables_created(db_session):
    """init_db()/create_all создаёт 4 таблицы модуля (в т.ч. под SQLite)."""
    for model in (Recommendation, PredictionLog, UserModel, Lesson):
        assert db_session.query(model).count() == 0


def test_contracts_instantiable():
    sr = SkillResult(key="fatigue", status="ok", value=1.0, confidence=0.8)
    assert sr.key == "fatigue" and sr.confidence == 0.8
    st = AthleteState()
    assert st.skills == {} and st.data_confidence == 0.0
    # Prescription невозможно собрать без SafetyVerdict — это гарантия границы (DEV_PLAN §1)
    with pytest.raises(TypeError):
        Prescription(workout_type="easy")  # type: ignore[call-arg]
    p = Prescription(safety=SafetyVerdict(), workout_type="easy",
                     rationale=[ReasoningStep("p1_safety", "allow", "recovered")])
    assert p.workout_type == "easy" and p.rationale[0].rule == "p1_safety"
    wp = WorkoutProposal(workout_type="interval", target_zone=5)
    assert wp.target_zone == 5


def test_can_persist_coach_rows(db_session):
    user = make_user(db_session, chat_id=90002, email="coachrows@example.com")
    rec = Recommendation(user_id=user.id, workout_type="easy", status="proposed",
                         target_json={"pace": "6:00"}, confidence=0.7)
    um = UserModel(user_id=user.id, params_json={"hrv_baseline": 65})
    db_session.add_all([rec, um])
    db_session.commit()
    assert db_session.query(Recommendation).filter_by(user_id=user.id).first().target_json == {"pace": "6:00"}
    assert db_session.query(UserModel).filter_by(user_id=user.id).first().params_json["hrv_baseline"] == 65


def test_stub_entrypoints_raise_not_implemented():
    # assess_state реализован в C1; движок/прескрайбер/оркестратор — заглушки до C2/C4.
    from src.coach import engine, prescriber, orchestrator
    for call in (
        lambda: engine.decide(None),
        lambda: prescriber.prescribe(None),
        lambda: orchestrator.morning_check(1),
    ):
        with pytest.raises(NotImplementedError):
            call()


def test_fixture_athlete_with_history(athlete_with_history, db_session):
    from src.models import DailyMetrics, TrainingSession
    uid = athlete_with_history.id
    assert db_session.query(DailyMetrics).filter_by(user_id=uid).count() == 14
    assert db_session.query(TrainingSession).filter_by(user_id=uid).count() == 5
