# Тесты утреннего подтверждения плана (Morning plan confirmation tests)
from datetime import date

from src.coach import orchestrator
from src.coach.llm.client import LLMResponse
from src.models import Recommendation
from tests.coach.conftest import _unique_user
from tests.coach.fakes import ScriptedLLM

CONFIRM_TURN = {
    "message": "Состояние в норме — идём по плану.",
    "proposal": None,                     # подтверждение: план не меняется
    "followup_question": None,
    "log_suggestion": None,
}

CHANGE_TURN = {
    "message": "Восстановление слабое — вместо лёгкой сегодня отдых.",
    "proposal": {"workout_type": "recovery", "target_zone": 1,
                 "duration_min": 20, "distance_km": None,
                 "structure": None, "rationale": ["слабое восстановление"]},
    "followup_question": None,
    "log_suggestion": None,
}


def _plan_row(db, user_id, *, workout_type="easy", duration=40.0) -> Recommendation:
    rec = Recommendation(user_id=user_id, for_date=date.today(),
                         workout_type=workout_type,
                         target_json={"max_zone": 2},
                         volume_json={"duration_min": duration},
                         status="planned", source="llm")
    db.add(rec)
    db.commit()
    return rec


def test_morning_confirms_plan_without_new_row(athlete_with_history, db_session):
    """proposal=null + план дня есть → полная карточка, status='confirmed',
    новых строк на дату НЕТ (UPDATE, не INSERT)."""
    uid = athlete_with_history.id
    rec = _plan_row(db_session, uid)
    n_before = db_session.query(Recommendation).filter_by(user_id=uid).count()

    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=CONFIRM_TURN)])
    reply = orchestrator.handle_chat(uid, "утренний вердикт", db=db_session,
                                     llm=llm, kind="morning")
    assert "Лёгкий бег" in reply.text                     # карточка плановой
    assert "Изменил план" not in reply.text                # подтверждение — без строки замены
    db_session.refresh(rec)
    assert rec.status == "confirmed"
    assert db_session.query(Recommendation).filter_by(
        user_id=uid).count() == n_before                  # без дубля


def test_morning_llm_change_creates_adjusted_row(athlete_with_history, db_session):
    """LLM осознанно меняет план → новая строка status='adjusted'."""
    uid = athlete_with_history.id
    rec = _plan_row(db_session, uid)
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=CHANGE_TURN)])
    reply = orchestrator.handle_chat(uid, "утренний вердикт", db=db_session,
                                     llm=llm, kind="morning")
    assert "Восстановительный" in reply.text
    # Строка изменения над карточкой (решение владельца 03.09.2026)
    assert "Изменил план на " in reply.text and "(было: 🟢 Лёгкий бег · 40 мин)" in reply.text
    assert reply.text.index("Изменил план") < reply.text.index("*🚶")
    adjusted = db_session.query(Recommendation).filter_by(
        user_id=uid, status="adjusted").all()
    assert len(adjusted) == 1
    assert adjusted[0].workout_type == "recovery"
    db_session.refresh(rec)
    assert rec.status == "planned"                        # исходная не тронута


def test_morning_without_plan_keeps_old_behavior(athlete_with_history, db_session):
    """Плана на сегодня нет → прежнее поведение: строка со status='proposed'."""
    uid = _unique_user(db_session).id
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=CHANGE_TURN)])
    orchestrator.handle_chat(uid, "утренний вердикт", db=db_session,
                             llm=llm, kind="morning")
    rows = db_session.query(Recommendation).filter_by(user_id=uid).all()
    assert len(rows) == 1 and rows[0].status == "proposed"
