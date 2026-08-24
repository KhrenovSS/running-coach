# Тесты D5: отложенный разбор — claim, гейты, восстановление
# (D5 tests: deferred review flow) — DEV_PLAN §9 D-серия

from src.coach import orchestrator, review_flow
from src.coach.llm.client import LLMResponse
from src.models import TrainingSession
from src.services.repositories_insights import InsightRepository
from tests.coach.fakes import ScriptedLLM

REVIEW_TURN = {
    "message": "Разобрал: ровно и по делу.",
    "proposal": None,
    "followup_question": None,
    "log_suggestion": None,
    "assessment": {"effort_match": "ok", "causes": [], "flags": [],
                   "carry_forward": None},
}


def _two_sessions(user_id, db):
    return db.query(TrainingSession).filter_by(user_id=user_id).order_by(
        TrainingSession.begin_ts.desc()).limit(2).all()


def _make_pending(user_id, db):
    latest, older = _two_sessions(user_id, db)
    trainings = [
        {"session_id": latest.id, "begin_ts": latest.begin_ts},
        {"session_id": older.id, "begin_ts": older.begin_ts},
    ]
    pending_sid = review_flow.ensure_insights_for_batch(
        user_id, trainings, db=db, initiative="high")
    return pending_sid, older.id


def test_ensure_batch_statuses(athlete_with_history, db_session):
    """normal/high: свежая → pending, старая → none (с метриками)."""
    pending_sid, older_sid = _make_pending(athlete_with_history.id, db_session)
    fresh = InsightRepository.for_session(athlete_with_history.id, pending_sid,
                                          db=db_session)
    old = InsightRepository.for_session(athlete_with_history.id, older_sid,
                                        db=db_session)
    assert fresh.status == "pending"
    assert old.status == "none"
    assert old.computed_json is not None


def test_ensure_batch_off_all_none(athlete_with_history, db_session):
    """off/low: pending не ставится вовсе."""
    latest, older = _two_sessions(athlete_with_history.id, db_session)
    trainings = [{"session_id": s.id, "begin_ts": s.begin_ts}
                 for s in (latest, older)]
    assert review_flow.ensure_insights_for_batch(
        athlete_with_history.id, trainings, db=db_session, initiative="off") is None


def test_run_pending_review_claims_once(athlete_with_history, db_session):
    """Дедуп: первый триггер разбирает, второй молча выходит (claim)."""
    pending_sid, _ = _make_pending(athlete_with_history.id, db_session)
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=REVIEW_TURN)])
    text = review_flow.run_pending_review(pending_sid, db=db_session, llm=llm)
    assert "Разобрал" in text
    row = InsightRepository.for_session(athlete_with_history.id, pending_sid,
                                        db=db_session)
    assert row.status == "done"
    assert row.source == "llm"
    # Конкурирующий триггер (джоба/тап): claim проигран → None, LLM не вызван
    again = review_flow.run_pending_review(pending_sid, db=db_session,
                                           llm=ScriptedLLM([]))
    assert again is None


def test_run_pending_review_initiative_reread_off(athlete_with_history, db_session):
    """Пользователь выключил коуча после синка → тишина, строка выведена из очереди."""
    pending_sid, _ = _make_pending(athlete_with_history.id, db_session)
    orchestrator.set_initiative(athlete_with_history.id, "off", db=db_session)
    text = review_flow.run_pending_review(pending_sid, db=db_session,
                                          llm=ScriptedLLM([]))
    assert text is None
    row = InsightRepository.for_session(athlete_with_history.id, pending_sid,
                                        db=db_session)
    assert row.status == "none"


def test_run_pending_review_low_deterministic(athlete_with_history, db_session):
    """Смена на low между синком и таймаутом → детерминированная карточка без LLM."""
    pending_sid, _ = _make_pending(athlete_with_history.id, db_session)
    orchestrator.set_initiative(athlete_with_history.id, "low", db=db_session)
    llm = ScriptedLLM([])
    text = review_flow.run_pending_review(pending_sid, db=db_session, llm=llm)
    assert "Разбор тренировки" in text
    assert len(llm.calls) == 0
    row = InsightRepository.for_session(athlete_with_history.id, pending_sid,
                                        db=db_session)
    assert row.status == "done"
    assert row.source == "fallback"


def test_run_pending_review_releases_on_crash(athlete_with_history, db_session,
                                              monkeypatch):
    """Неожиданный сбой → строка возвращается в pending (retry), не теряется."""
    pending_sid, _ = _make_pending(athlete_with_history.id, db_session)

    def boom(*a, **kw):
        raise RuntimeError("db went away")

    monkeypatch.setattr(orchestrator, "on_workout_completed", boom)
    assert review_flow.run_pending_review(pending_sid, db=db_session) is None
    row = InsightRepository.for_session(athlete_with_history.id, pending_sid,
                                        db=db_session)
    assert row.status == "pending"
    assert row.attempts == 1


def test_run_pending_review_missing_row(db_session):
    """Строки нет (legacy) → None без исключений."""
    assert review_flow.run_pending_review(987654, db=db_session) is None
