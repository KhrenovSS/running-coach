# Вердикт по скриншоту сна (19.09.2026): скрин за сегодня запускает утренний вердикт,
# джоба 09:30 остаётся резервом и дубля не шлёт. Корутины драйвим asyncio.run.
#
# «Сейчас» фиксируем утром: решение зависит от локального часа (стоп-час пересчёта),
# а прогон тестов идёт в любое время суток. (Freeze local now — the hour matters.)
import asyncio
from datetime import datetime, time, timedelta

import pytest

from src.coach import morning_state, orchestrator
from src.coach.orchestrator import ChatReply
from src.services.repositories_coach import CoachRepository
from src.services.sleep_ingest import SLEEP_SOURCE, has_sleep_for_date
from src.telegram.jobs import coach_morning
from src.utils.timeutils import user_now
from tests.coach.conftest import _unique_user
from tests.coach.test_morning_job import _FakeContext
from tests.helpers import build_daily_metrics

TODAY = datetime.now().date()


@pytest.fixture
def morning_now(monkeypatch):
    """08:10 локального времени для всех путей утреннего вердикта."""
    fixed = datetime.combine(TODAY, time(8, 10))
    monkeypatch.setattr(coach_morning, "user_now", lambda _user: fixed)
    return fixed


def _sleep_row(db_session, user, *, days_ago: int = 0, **extra):
    build_daily_metrics(db_session, user.id, metric_date=TODAY - timedelta(days=days_ago),
                        sleep_duration_min=430, sleep_source=SLEEP_SOURCE, **extra)


def _patch_turn(monkeypatch, text="вердикт", source="llm", retriable=False):
    prompts: list[str] = []

    def _turn(uid, prompt=None, suffix=None):
        prompts.append(prompt or "")
        return ChatReply(text=text + (suffix or ""), source=source, retriable=retriable)

    monkeypatch.setattr(coach_morning, "_morning_turn_blocking", _turn)
    return prompts


def _after_sleep(ctx, user):
    asyncio.run(coach_morning.maybe_deliver_after_sleep(
        ctx, user_id=user.id, chat_id=user.telegram_chat_id))


def _texts(ctx, user):
    return [t for cid, t in ctx.bot.sent if cid == user.telegram_chat_id]


def _mark_sent_without_sleep(db_session, user, now, text="вердикт"):
    """Состояние «вердикт за сегодня ушёл без данных сна» + запись в истории."""
    morning_state.claim(user.id, db=db_session, day=now.date(), with_sleep=False, now=now)
    morning_state.mark_sent(user.id, db=db_session, day=now.date(), with_sleep=False, now=now)
    CoachRepository.save_message(user.id, "assistant", text, db=db_session, kind="morning")


def test_screenshot_sends_verdict_and_job_stays_silent(monkeypatch, db_session, morning_now):
    """Скрин сна за сегодня → вердикт сразу; резерв 09:30 второго сообщения не шлёт."""
    user = _unique_user(db_session)
    _sleep_row(db_session, user)
    _patch_turn(monkeypatch)

    ctx = _FakeContext()
    _after_sleep(ctx, user)
    texts = _texts(ctx, user)
    assert texts[0] == coach_morning.PROGRESS_TEXT and "вердикт" in texts[-1]

    job_ctx = _FakeContext()
    asyncio.run(coach_morning.morning_verdict_job(job_ctx))
    assert _texts(job_ctx, user) == []


def test_job_sends_when_no_screenshot(monkeypatch, db_session, morning_now):
    """Скрина нет → резерв 09:30 работает как раньше."""
    user = _unique_user(db_session)
    _patch_turn(monkeypatch)
    ctx = _FakeContext()
    asyncio.run(coach_morning.morning_verdict_job(ctx))
    assert _texts(ctx, user) == ["вердикт"]


def test_screenshot_for_another_date_does_not_trigger(monkeypatch, db_session, morning_now):
    """Экран Coros с вчерашней датой → сигнала сна за сегодня нет, вердикт не шлём."""
    user = _unique_user(db_session)
    _sleep_row(db_session, user, days_ago=1)
    _patch_turn(monkeypatch)
    ctx = _FakeContext()
    _after_sleep(ctx, user)
    assert _texts(ctx, user) == []


def test_late_screenshot_resends_with_prefix(monkeypatch, db_session, morning_now):
    """Вердикт ушёл без сна → поздний скрин даёт пересчёт с префиксом, второй скрин — тишина."""
    user = _unique_user(db_session)
    _mark_sent_without_sleep(db_session, user, morning_now)
    _sleep_row(db_session, user)
    prompts = _patch_turn(monkeypatch, text="новый вердикт")

    ctx = _FakeContext()
    _after_sleep(ctx, user)
    assert _texts(ctx, user)[-1].startswith(coach_morning.RESEND_PREFIX)
    assert "новый вердикт" in _texts(ctx, user)[-1]
    assert prompts and "Пересчитай" in prompts[-1]
    assert morning_state.state(user.id, db=db_session)["with_sleep"] is True

    second = _FakeContext()
    _after_sleep(second, user)
    assert _texts(second, user) == []


def test_resend_identical_text_collapses_to_one_line(monkeypatch, db_session, morning_now):
    """Пересчёт слово в слово повторил вердикт → вместо копии одна строка."""
    user = _unique_user(db_session)
    _mark_sent_without_sleep(db_session, user, morning_now, text="вердикт")
    _sleep_row(db_session, user)
    _patch_turn(monkeypatch, text="вердикт", source="fallback")

    ctx = _FakeContext()
    _after_sleep(ctx, user)
    assert _texts(ctx, user)[-1] == coach_morning.UNCHANGED_TEXT


def test_after_stop_hour_only_stores_sleep(monkeypatch, db_session):
    """Скрин вечером → сон в БД, «утренний» вердикт не шлём."""
    user = _unique_user(db_session)
    _sleep_row(db_session, user)
    monkeypatch.setattr(coach_morning, "user_now",
                        lambda _user: datetime.combine(TODAY, time(22, 0)))
    _patch_turn(monkeypatch)
    ctx = _FakeContext()
    _after_sleep(ctx, user)
    assert _texts(ctx, user) == []


def test_turn_in_flight_schedules_recheck(monkeypatch, db_session, morning_now):
    """Ход 09:30 ещё в полёте → одна отложенная перепроверка, без дубля."""
    user = _unique_user(db_session)
    _sleep_row(db_session, user)
    morning_state.claim(user.id, db=db_session, day=TODAY, with_sleep=False, now=morning_now)
    _patch_turn(monkeypatch)

    ctx = _FakeContext()
    _after_sleep(ctx, user)
    assert _texts(ctx, user) == []
    assert len(ctx.job_queue.scheduled) == 1
    cb, _delay, data = ctx.job_queue.scheduled[0]
    assert cb is coach_morning._sleep_recheck_job and data["user_id"] == user.id


def test_initiative_off_keeps_day_free(monkeypatch, db_session, morning_now):
    """Инициатива off → вердикта нет и заявка снята (день остаётся свободным)."""
    user = _unique_user(db_session)
    _sleep_row(db_session, user)
    orchestrator.set_initiative(user.id, "off", db=db_session)
    monkeypatch.setattr(coach_morning, "_morning_turn_blocking",
                        lambda uid, prompt=None, suffix=None: None)

    ctx = _FakeContext()
    _after_sleep(ctx, user)
    assert _texts(ctx, user) == [coach_morning.PROGRESS_TEXT]
    assert morning_state.state(user.id, db=db_session) == {}


def test_has_sleep_for_date_only_counts_screenshot(db_session):
    """HRV из синка не считается сном: напоминание 09:00 и вердикт смотрят на скрин."""
    user = _unique_user(db_session)
    dm = build_daily_metrics(db_session, user.id, metric_date=TODAY, avg_sleep_hrv=62.0)
    assert has_sleep_for_date(user.id, TODAY, db=db_session) is False
    dm.sleep_duration_min, dm.sleep_source = 430, SLEEP_SOURCE
    db_session.commit()
    assert has_sleep_for_date(user.id, TODAY, db=db_session) is True
