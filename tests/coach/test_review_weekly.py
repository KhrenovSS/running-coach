# Тесты C8: LLM-разбор тренировки + недельный отчёт + гейт инициативы
# (C8 tests: LLM workout review, weekly report, initiative gate) — DEV_PLAN §9 C8

from src.coach import orchestrator
from src.coach.llm.client import LLMResponse
from src.models import CoachMessage, Recommendation, TrainingSession
from src.services.repositories_coach import CoachRepository
from src.services.sync import activities
from tests.coach.fakes import FailingLLM, ScriptedLLM

REVIEW_TURN = {
    "message": "Хорошая работа — тренировка легла ровно.",
    "proposal": None,
    "followup_question": "Как колено после пробежки?",
    "log_suggestion": None,
}

TURN_WITH_PROPOSAL = {
    "message": "Отличная тренировка, завтра можно интервалы!",
    "proposal": {"workout_type": "interval", "target_zone": 5,
                 "duration_min": 60, "distance_km": 10.0,
                 "structure": "10×400/400", "rationale": ["форма хорошая"]},
    "followup_question": None,
    "log_suggestion": None,
}

WEEKLY_TURN = {
    "message": "Неделя ровная: объём держится, лёгкий бег в норме.",
    "proposal": None,
    "followup_question": "Какие цели на неделю?",
    "log_suggestion": None,
}


def _latest_session_id(user_id: int, db) -> int:
    s = db.query(TrainingSession).filter_by(user_id=user_id).order_by(
        TrainingSession.begin_ts.desc()).first()
    return s.id


def test_review_via_llm(athlete_with_history, db_session):
    """LLM-разбор: проза + followup; детали сессии в контексте; kind=review записан."""
    sid = _latest_session_id(athlete_with_history.id, db_session)
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=REVIEW_TURN)])
    text = orchestrator.on_workout_completed(athlete_with_history.id, sid,
                                             db=db_session, llm=llm)
    assert "Хорошая работа" in text
    assert "Как колено" in text
    # Детали тренировки инлайнены в последний user-блок (bridge: tool-цикл неактивен)
    last_user_content = llm.calls[0]["messages"][-1]["content"]
    assert "workout_detail" in last_user_content
    msgs = db_session.query(CoachMessage).filter_by(
        user_id=athlete_with_history.id, kind="review").all()
    assert {m.role for m in msgs} == {"user", "assistant"}


def test_review_proposal_dropped(athlete_with_history, db_session):
    """Proposal в разборе отбрасывается: без карточки, clamp и Recommendation."""
    sid = _latest_session_id(athlete_with_history.id, db_session)
    recs_before = db_session.query(Recommendation).filter_by(
        user_id=athlete_with_history.id).count()
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=TURN_WITH_PROPOSAL)])
    text = orchestrator.on_workout_completed(athlete_with_history.id, sid,
                                             db=db_session, llm=llm)
    assert "Ограничение по безопасности" not in text
    assert "Интервалы" not in text  # карточка не рендерится вовсе
    recs_after = db_session.query(Recommendation).filter_by(
        user_id=athlete_with_history.id).count()
    assert recs_after == recs_before


def test_review_failing_llm_falls_back(athlete_with_history, db_session):
    """LLM падает → детерминированный render_review, meta=fallback, без исключения."""
    sid = _latest_session_id(athlete_with_history.id, db_session)
    text = orchestrator.on_workout_completed(athlete_with_history.id, sid,
                                             db=db_session, llm=FailingLLM())
    assert "Разбор тренировки" in text
    msg = db_session.query(CoachMessage).filter_by(
        user_id=athlete_with_history.id, kind="review", role="assistant").order_by(
        CoachMessage.id.desc()).first()
    assert msg.meta_json == {"fallback": True}


def test_review_budget_exhausted_no_llm_call(athlete_with_history, db_session):
    """Дневной бюджет исчерпан → детерминированный разбор БЕЗ вызова LLM."""
    from src.coach.llm.config import COACH_MAX_TURNS_PER_DAY
    for _ in range(COACH_MAX_TURNS_PER_DAY):
        CoachRepository.save_message(athlete_with_history.id, "assistant", "x",
                                     db=db_session)
    sid = _latest_session_id(athlete_with_history.id, db_session)
    llm = ScriptedLLM([])
    text = orchestrator.on_workout_completed(athlete_with_history.id, sid,
                                             db=db_session, llm=llm)
    assert "Разбор тренировки" in text
    assert len(llm.calls) == 0


def test_review_use_llm_false_skips_llm(athlete_with_history, db_session):
    """use_llm=False (гейт low / старая тренировка батча) → LLM не вызывается."""
    sid = _latest_session_id(athlete_with_history.id, db_session)
    llm = ScriptedLLM([])
    text = orchestrator.on_workout_completed(athlete_with_history.id, sid,
                                             db=db_session, llm=llm, use_llm=False)
    assert "Разбор тренировки" in text
    assert len(llm.calls) == 0


def test_sync_reviews_initiative_off_is_silent(athlete_with_history, db_session,
                                               monkeypatch):
    """initiative=off → тишина, но insight с метриками записан молча (D5)."""
    from src.services.repositories_insights import InsightRepository
    orchestrator.set_initiative(athlete_with_history.id, "off", db=db_session)
    sid = _latest_session_id(athlete_with_history.id, db_session)
    sent = []
    monkeypatch.setattr(activities, "telegram_notify",
                        lambda **kw: sent.append(kw))
    db_session.commit()  # вернуть соединение в пул: хелпер откроет свою сессию
    activities._coach_reviews(athlete_with_history.id,
                              [{"session_id": sid, "begin_ts": None}])
    assert sent == []
    row = InsightRepository.for_session(athlete_with_history.id, sid, db=db_session)
    assert row.status == "none"          # сырьё для отчётов при включении
    assert row.computed_json is not None


def test_sync_batch_latest_pending_older_deterministic(athlete_with_history,
                                                       db_session, monkeypatch):
    """Батч (D5): свежая → pending (молчит, ждёт тапа), старая → карточка сразу."""
    from src.services.repositories_insights import InsightRepository
    orchestrator.set_initiative(athlete_with_history.id, "high", db=db_session)
    sessions = db_session.query(TrainingSession).filter_by(
        user_id=athlete_with_history.id).order_by(
        TrainingSession.begin_ts.desc()).limit(2).all()
    latest, older = sessions[0], sessions[1]
    calls = []

    def fake_review(user_id, session_id, *, db, llm=None, use_llm=True):
        calls.append((session_id, use_llm))
        return "разбор"

    monkeypatch.setattr(orchestrator, "on_workout_completed", fake_review)
    sent = []
    monkeypatch.setattr(activities, "telegram_notify",
                        lambda **kw: sent.append(kw))
    trainings = [
        {"session_id": latest.id, "begin_ts": latest.begin_ts},
        {"session_id": older.id, "begin_ts": older.begin_ts},
    ]
    db_session.commit()  # вернуть соединение в пул: хелпер откроет свою сессию
    activities._coach_reviews(athlete_with_history.id, trainings)
    assert calls == [(older.id, False)]  # свежая НЕ разобрана — ждёт тапа/таймаута
    assert len(sent) == 1
    fresh_row = InsightRepository.for_session(athlete_with_history.id, latest.id,
                                              db=db_session)
    assert fresh_row.status == "pending"


def test_weekly_report_via_llm(athlete_with_history, db_session):
    """Недельный отчёт: kind=weekly, effort=plan, weekly_summary в контексте."""
    from src.coach.llm.config import COACH_EFFORT_PLAN
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=WEEKLY_TURN)])
    reply = orchestrator.weekly_report(athlete_with_history.id, db=db_session, llm=llm)
    assert reply.source == "llm"
    assert "Неделя ровная" in reply.text
    assert llm.calls[0]["effort"] == COACH_EFFORT_PLAN
    assert "weekly_summary" in llm.calls[0]["messages"][-1]["content"]
    msg = db_session.query(CoachMessage).filter_by(
        user_id=athlete_with_history.id, kind="weekly", role="assistant").first()
    assert msg is not None


def test_weekly_report_fallback_digest(athlete_with_history, db_session):
    """LLM падает → детерминированный дайджест «Итоги недели», meta=fallback."""
    reply = orchestrator.weekly_report(athlete_with_history.id, db=db_session,
                                       llm=FailingLLM())
    assert reply.source == "fallback"
    assert "Итоги недели" in reply.text
    msg = db_session.query(CoachMessage).filter_by(
        user_id=athlete_with_history.id, kind="weekly", role="assistant").order_by(
        CoachMessage.id.desc()).first()
    assert msg.meta_json == {"fallback": True}


def test_weekly_job_gate_below_normal(athlete_with_history, db_session):
    """Гейт джобы: off и low → None (отчёт не шлём) — решение владельца 24.08."""
    from src.telegram.jobs.coach_weekly import _weekly_turn_blocking
    for level in ("off", "low"):
        orchestrator.set_initiative(athlete_with_history.id, level, db=db_session)
        db_session.commit()  # вернуть соединение в пул: хелпер откроет свою сессию
        assert _weekly_turn_blocking(athlete_with_history.id) is None
