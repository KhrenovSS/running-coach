# Пометка «данных сна нет» в утреннем вердикте (решение владельца 19.09.2026):
# только перед качественным днём; в лёгкий день/отдых и при наличии сна её нет.
# Плюс: утро не отдаёт отписку про лимит ходов вместо плана дня.
from datetime import date, datetime, time, timedelta

import pytest

from src.coach import morning_state, orchestrator, planning
from src.coach.llm.config import COACH_MAX_TURNS_PER_DAY
from src.coach.orchestrator import ChatReply
from src.coach.render import SLEEP_MISSING_NOTE, render_sleep_missing_note
from src.models import Recommendation
from src.services.repositories_coach import CoachRepository
from src.services.sleep_ingest import SLEEP_SOURCE
from src.telegram.jobs import coach_morning
from tests.coach.conftest import _unique_user
from tests.coach.fakes import TransientFailingLLM
from tests.coach.test_morning_job import _FakeContext
from tests.helpers import build_daily_metrics

TODAY = datetime.now().date()


@pytest.fixture
def morning_now(monkeypatch):
    fixed = datetime.combine(TODAY, time(9, 30))
    monkeypatch.setattr(coach_morning, "user_now", lambda _user: fixed)
    return fixed


def _plan_row(db_session, user, workout_type: str, day: date | None = None):
    db_session.add(Recommendation(
        user_id=user.id, for_date=day or TODAY, workout_type=workout_type,
        status="planned", target_json={"max_zone": 3}, volume_json={"duration_min": 40},
        proposal_json={"workout_type": workout_type}))
    db_session.commit()


def _run_job(monkeypatch, user):
    """Резерв 09:30 с подменённым ходом: текст = вердикт + пришедший суффикс."""
    monkeypatch.setattr(coach_morning, "_morning_turn_blocking",
                        lambda uid, prompt=None, suffix=None: ChatReply(
                            text="вердикт" + (suffix or ""), source="llm"))
    import asyncio
    ctx = _FakeContext()
    asyncio.run(coach_morning.morning_verdict_job(ctx))
    return [t for cid, t in ctx.bot.sent if cid == user.telegram_chat_id]


def test_note_only_without_sleep_before_quality_day():
    """Чистая функция: пометка — только «сна нет» + качественный день."""
    assert render_sleep_missing_note(has_sleep=False, hard_today=True) == SLEEP_MISSING_NOTE
    assert render_sleep_missing_note(has_sleep=False, hard_today=False) is None
    assert render_sleep_missing_note(has_sleep=True, hard_today=True) is None


def test_hard_day_on_reads_the_day_not_the_week(db_session):
    """hard_day_on смотрит ровно на дату (в отличие от hard_day_planned на всю неделю)."""
    user = _unique_user(db_session)
    _plan_row(db_session, user, "tempo", day=TODAY + timedelta(days=2))
    assert planning.hard_day_on(user.id, db=db_session, day=TODAY) is False
    _plan_row(db_session, user, "easy")
    assert planning.hard_day_on(user.id, db=db_session, day=TODAY) is False
    _plan_row(db_session, user, "interval")
    assert planning.hard_day_on(user.id, db=db_session, day=TODAY) is True


def test_verdict_carries_note_before_quality_day(monkeypatch, db_session, morning_now):
    """Качественный день и скрина сна нет → вердикт несёт пометку."""
    user = _unique_user(db_session)
    _plan_row(db_session, user, "tempo")
    assert SLEEP_MISSING_NOTE in _run_job(monkeypatch, user)[-1]


def test_no_note_on_easy_day(monkeypatch, db_session, morning_now):
    """Лёгкий день → сон влияет слабо, пометки нет (решение владельца)."""
    user = _unique_user(db_session)
    _plan_row(db_session, user, "easy")
    assert SLEEP_MISSING_NOTE not in _run_job(monkeypatch, user)[-1]


def test_no_note_when_sleep_present(monkeypatch, db_session, morning_now):
    """Скрин сна за сегодня есть → пометке неоткуда взяться."""
    user = _unique_user(db_session)
    _plan_row(db_session, user, "tempo")
    build_daily_metrics(db_session, user.id, metric_date=TODAY,
                        sleep_duration_min=430, sleep_source=SLEEP_SOURCE)
    assert SLEEP_MISSING_NOTE not in _run_job(monkeypatch, user)[-1]


def test_note_reaches_deterministic_fallback(athlete_with_history, db_session):
    """Мост лёг → пометка приклеивается и к детерминированному вердикту."""
    reply = orchestrator.handle_chat(athlete_with_history.id, "утро", db=db_session,
                                     llm=TransientFailingLLM(), kind="morning",
                                     suffix="\n\n" + SLEEP_MISSING_NOTE)
    assert reply.source == "fallback" and reply.text.endswith(SLEEP_MISSING_NOTE)


def test_turn_budget_never_eats_the_verdict(athlete_with_history, db_session):
    """Бюджет ходов исчерпан → утро отдаёт вердикт, а не «лимит разговоров исчерпан»."""
    uid = athlete_with_history.id
    for _ in range(COACH_MAX_TURNS_PER_DAY):
        CoachRepository.save_message(uid, "assistant", "x", db=db_session, kind="chat")
    reply = orchestrator.handle_chat(uid, "утро", db=db_session, kind="morning")
    assert "лимит разговоров" not in reply.text
    assert reply.text.startswith("*Состояние*")


def test_claim_not_taken_when_day_already_sent(db_session):
    """Резерв 09:30 после раннего вердикта день не занимает (дедуп, а не перезапись)."""
    user = _unique_user(db_session)
    now = datetime.combine(TODAY, time(8, 0))
    morning_state.claim(user.id, db=db_session, day=TODAY, with_sleep=True, now=now)
    morning_state.mark_sent(user.id, db=db_session, day=TODAY, with_sleep=True, now=now)
    later = datetime.combine(TODAY, time(9, 30))
    assert morning_state.claim(user.id, db=db_session, day=TODAY, with_sleep=False,
                               now=later) is False
