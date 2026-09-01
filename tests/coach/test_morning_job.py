# Тесты джобы утреннего вердикта: отложенный повтор при транзиентном сбое моста
# (инцидент 01.09.2026). Драйвим корутины через asyncio.run (как test_sleep_photo).
import asyncio
import types

from src.coach.llm.config import COACH_MORNING_RETRY_MAX
from src.coach.orchestrator import ChatReply
from src.telegram.jobs import coach_morning
from tests.coach.conftest import _unique_user


class _FakeBot:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))


class _FakeJobQueue:
    def __init__(self):
        self.scheduled: list[tuple] = []

    def run_once(self, cb, delay, data=None):
        self.scheduled.append((cb, delay, data))


class _FakeContext:
    def __init__(self, job_data=None):
        self.bot = _FakeBot()
        self.job_queue = _FakeJobQueue()
        self.job = types.SimpleNamespace(data=job_data)


def _patch_turn(monkeypatch, reply: ChatReply):
    monkeypatch.setattr(coach_morning, "_morning_turn_blocking", lambda uid: reply)
    monkeypatch.setattr(coach_morning, "_within_retry_window", lambda: True)


def test_job_reschedules_on_transient(monkeypatch, db_session):
    """Транзиентная деградация → вердикт доставлен + ОДИН отложенный повтор (upgrade)."""
    user = _unique_user(db_session)
    _patch_turn(monkeypatch, ChatReply(text="вердикт", source="fallback", retriable=True))
    ctx = _FakeContext()
    asyncio.run(coach_morning.morning_verdict_job(ctx))

    assert any(cid == user.telegram_chat_id for cid, _ in ctx.bot.sent)  # доставлен
    assert len(ctx.job_queue.scheduled) == 1                             # ровно один повтор
    cb, _delay, data = ctx.job_queue.scheduled[0]
    assert cb is coach_morning._morning_upgrade_job
    assert data["attempt"] == 1
    assert (user.id, user.telegram_chat_id) in data["targets"]


def test_job_no_reschedule_on_permanent(monkeypatch, db_session):
    """Постоянный сбой (retriable=False) → повтор не ставим (бессмыслен)."""
    _unique_user(db_session)
    _patch_turn(monkeypatch, ChatReply(text="вердикт", source="fallback", retriable=False))
    ctx = _FakeContext()
    asyncio.run(coach_morning.morning_verdict_job(ctx))
    assert ctx.job_queue.scheduled == []


def test_job_no_reschedule_on_llm(monkeypatch, db_session):
    """Нормальный LLM-вердикт → повтор не нужен."""
    _unique_user(db_session)
    _patch_turn(monkeypatch, ChatReply(text="вердикт", source="llm"))
    ctx = _FakeContext()
    asyncio.run(coach_morning.morning_verdict_job(ctx))
    assert ctx.job_queue.scheduled == []


def test_upgrade_sends_on_llm_recovery(monkeypatch, db_session):
    """Мост поднялся → upgrade шлёт уточнённый вердикт с префиксом, дальше не переносит."""
    user = _unique_user(db_session)
    monkeypatch.setattr(coach_morning, "_morning_turn_blocking",
                        lambda uid: ChatReply(text="точный вердикт", source="llm"))
    monkeypatch.setattr(coach_morning, "_within_retry_window", lambda: True)
    ctx = _FakeContext(job_data={"targets": [(user.id, user.telegram_chat_id)],
                                 "attempt": 1})
    asyncio.run(coach_morning._morning_upgrade_job(ctx))

    assert len(ctx.bot.sent) == 1
    chat_id, text = ctx.bot.sent[0]
    assert chat_id == user.telegram_chat_id
    assert text.startswith("🔄 Мост восстановился")
    assert "точный вердикт" in text
    assert ctx.job_queue.scheduled == []


def test_upgrade_stops_at_max_attempts(monkeypatch, db_session):
    """Всё ещё транзиентно и attempt == MAX → тихо стоп, нового повтора нет."""
    user = _unique_user(db_session)
    monkeypatch.setattr(coach_morning, "_morning_turn_blocking",
                        lambda uid: ChatReply(text="x", source="fallback", retriable=True))
    monkeypatch.setattr(coach_morning, "_within_retry_window", lambda: True)
    ctx = _FakeContext(job_data={"targets": [(user.id, user.telegram_chat_id)],
                                 "attempt": COACH_MORNING_RETRY_MAX})
    asyncio.run(coach_morning._morning_upgrade_job(ctx))
    assert ctx.bot.sent == []                 # LLM не поднялся — уточнения нет
    assert ctx.job_queue.scheduled == []      # лимит попыток исчерпан


def test_upgrade_reschedules_when_attempts_left(monkeypatch, db_session):
    """Транзиентно и attempt < MAX → ставим следующий повтор с attempt+1."""
    user = _unique_user(db_session)
    monkeypatch.setattr(coach_morning, "_morning_turn_blocking",
                        lambda uid: ChatReply(text="x", source="fallback", retriable=True))
    monkeypatch.setattr(coach_morning, "_within_retry_window", lambda: True)
    ctx = _FakeContext(job_data={"targets": [(user.id, user.telegram_chat_id)],
                                 "attempt": 1})
    asyncio.run(coach_morning._morning_upgrade_job(ctx))
    assert len(ctx.job_queue.scheduled) == 1
    _cb, _delay, data = ctx.job_queue.scheduled[0]
    assert data["attempt"] == 2
