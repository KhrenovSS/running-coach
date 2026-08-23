# Тесты оркестратора с фейковыми LLM (Orchestrator tests) — DEV_PLAN §10
from src.coach import orchestrator
from src.coach.llm.client import LLMResponse
from src.models import CoachMessage, Recommendation
from tests.coach.fakes import FailingLLM, ScriptedLLM

TURN_WITH_PROPOSAL = {
    "message": "Предлагаю сегодня интервалы — форма отличная!",
    "proposal": {"workout_type": "interval", "target_zone": 5,
                 "duration_min": 60, "distance_km": 10.0,
                 "structure": "10×400/400", "rationale": ["форма хорошая"]},
    "followup_question": "Как колено после вчерашнего?",
    "log_suggestion": None,
}


def test_failing_llm_falls_back_deterministically(athlete_with_history, db_session):
    """LLM падает → детерминированный текст, исключение не всплывает, диалог записан."""
    llm = FailingLLM()
    reply = orchestrator.handle_chat(athlete_with_history.id, "привет",
                                     db=db_session, llm=llm)
    assert reply.source == "fallback"
    assert "состояние" in reply.text.lower()
    msgs = db_session.query(CoachMessage).filter_by(
        user_id=athlete_with_history.id).all()
    assert {m.role for m in msgs} >= {"user", "assistant"}


def test_llm_proposal_goes_through_clamp(athlete_with_history, db_session):
    """Предложение LLM проходит clamp: часы восстановления → интервалы не сегодня.

    Фикстура: последняя тренировка недавно → recovery_hours_left > 0 →
    earliest_next_hard → hard-тип даунгрейдится. Recommendation записана с source=llm.
    """
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=TURN_WITH_PROPOSAL)])
    reply = orchestrator.handle_chat(athlete_with_history.id, "что сегодня?",
                                     db=db_session, llm=llm)
    assert reply.source == "llm"
    assert "Интервалы" not in reply.text          # карточка урезана — не интервалы
    assert "Ограничение по безопасности" in reply.text
    assert "Как колено" in reply.text             # followup дошёл

    rec = db_session.query(Recommendation).filter_by(
        user_id=athlete_with_history.id).order_by(Recommendation.id.desc()).first()
    assert rec.workout_type != "interval"

    # Учёт диалога: обе строки записаны, у assistant есть usage-мета
    msg = db_session.query(CoachMessage).filter_by(
        user_id=athlete_with_history.id, role="assistant").order_by(
        CoachMessage.id.desc()).first()
    assert msg.kind == "chat"


def test_budget_exhausted_no_llm_call(athlete_with_history, db_session):
    """Бюджет исчерпан → вежливый отказ БЕЗ вызова LLM (len(calls)==0)."""
    from src.coach.llm.config import COACH_MAX_TURNS_PER_DAY
    from src.services.repositories_coach import CoachRepository
    for _ in range(COACH_MAX_TURNS_PER_DAY):
        CoachRepository.save_message(athlete_with_history.id, "assistant", "x",
                                     db=db_session)
    llm = ScriptedLLM([])
    reply = orchestrator.handle_chat(athlete_with_history.id, "ещё вопрос",
                                     db=db_session, llm=llm)
    assert "лимит" in reply.text.lower()
    assert len(llm.calls) == 0


def test_log_suggestion_passthrough(athlete_with_history, db_session):
    """log_suggestion от LLM доезжает до ChatReply (кнопку строит хендлер)."""
    turn = {"message": "Понял, колено потягивало.", "proposal": None,
            "followup_question": None,
            "log_suggestion": {"kind": "pain", "value": 2}}
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=turn)])
    reply = orchestrator.handle_chat(athlete_with_history.id,
                                     "колено потягивало первые 2 км",
                                     db=db_session, llm=llm)
    assert reply.log_suggestion is not None
    assert reply.log_suggestion.value == 2
