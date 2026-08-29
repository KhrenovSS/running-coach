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


def test_today_block_has_local_now_and_no_utc_leak(athlete_with_history, db_session):
    """Инцидент 28.08: LLM назвал вечернюю тренировку «утренней» — времени в промпте
    не было. Теперь: «Сейчас:» с локальным временем и поясом, started_at_local у
    тренировок, earliest_next_hard без голого UTC (+00:00).
    """
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn",
                                   parsed={"message": "ок", "proposal": None,
                                           "followup_question": None,
                                           "log_suggestion": None})])
    orchestrator.handle_chat(athlete_with_history.id, "как дела?",
                             db=db_session, llm=llm)
    content = llm.calls[0]["messages"][-1]["content"]
    assert "Сейчас: " in content
    assert "(Europe/Moscow)" in content        # make_user: timezone Moscow
    assert "started_at_local" in content
    assert "+00:00" not in content             # earliest_next_hard — локальное время


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


EASY_TURN = {
    "message": "Сегодня лёгкий бег — восстанавливаемся.",
    "proposal": {"workout_type": "easy", "target_zone": 2,
                 "duration_min": 40, "distance_km": 5.5,
                 "structure": None, "rationale": ["восстановление"]},
    "followup_question": None,
    "log_suggestion": None,
}


def test_chat_unchanged_proposal_renders_reminder_not_card(athlete_with_history,
                                                           db_session):
    """Инцидент 26.08: повтор того же proposal в чате дублировал карточку и
    плодил строки recommendations. Теперь — строка-напоминание без новой записи."""
    resp = LLMResponse(stop_reason="end_turn", parsed=EASY_TURN)
    llm = ScriptedLLM([resp, resp])
    uid = athlete_with_history.id

    first = orchestrator.handle_chat(uid, "что сегодня?", db=db_session, llm=llm)
    assert "Лёгкий бег" in first.text
    n_recs = db_session.query(Recommendation).filter_by(user_id=uid).count()
    assert n_recs >= 1

    second = orchestrator.handle_chat(uid, "какой пульс допустим?",
                                      db=db_session, llm=llm)
    assert "План на сегодня без изменений" in second.text
    assert "пульс до 141" in second.text          # max_hr=177 → потолок Z2
    assert "и ниже" not in second.text            # полная карточка не повторяется
    assert db_session.query(Recommendation).filter_by(
        user_id=uid).count() == n_recs            # дубль-записи нет


def test_chat_changed_proposal_gets_full_card(athlete_with_history, db_session):
    """Изменённое назначение → полная карточка и новая запись recommendations."""
    changed = dict(EASY_TURN)
    changed["proposal"] = dict(EASY_TURN["proposal"], duration_min=30,
                               distance_km=4.0)
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=EASY_TURN),
                       LLMResponse(stop_reason="end_turn", parsed=changed)])
    uid = athlete_with_history.id

    orchestrator.handle_chat(uid, "что сегодня?", db=db_session, llm=llm)
    n_recs = db_session.query(Recommendation).filter_by(user_id=uid).count()
    second = orchestrator.handle_chat(uid, "давай покороче",
                                      db=db_session, llm=llm)
    assert "30 мин" in second.text
    assert "План на сегодня без изменений" not in second.text
    assert db_session.query(Recommendation).filter_by(
        user_id=uid).count() == n_recs + 1


def test_morning_kind_not_deduped(athlete_with_history, db_session):
    """Дедуп — только для kind=chat: утренний вердикт всегда с полной карточкой."""
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=EASY_TURN),
                       LLMResponse(stop_reason="end_turn", parsed=EASY_TURN)])
    uid = athlete_with_history.id

    orchestrator.handle_chat(uid, "что сегодня?", db=db_session, llm=llm)
    n_recs = db_session.query(Recommendation).filter_by(user_id=uid).count()
    morning = orchestrator.handle_chat(uid, "утренний вердикт", db=db_session,
                                       llm=llm, kind="morning")
    assert "Лёгкий бег" in morning.text
    assert "План на сегодня без изменений" not in morning.text
    assert db_session.query(Recommendation).filter_by(
        user_id=uid).count() == n_recs + 1


def test_llm_card_contains_bpm_ceiling(athlete_with_history, db_session):
    """Карточка LLM-хода содержит потолок пульса зоны в уд/мин (инцидент 26.08)."""
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=EASY_TURN)])
    reply = orchestrator.handle_chat(athlete_with_history.id, "что сегодня?",
                                     db=db_session, llm=llm)
    assert "пульс до 141 уд/мин" in reply.text    # max_hr=177, Z2 → 141


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
