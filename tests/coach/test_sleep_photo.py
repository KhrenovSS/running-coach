# Тесты хендлера скриншота сна: ok-флаг и удаление сообщения (#257-follow-up)
import asyncio

import telegram.error

from src.coach.vision import SleepShot
from src.telegram.handlers import sleep_photo


class _FakeMsg:
    def __init__(self, delete_raises=False):
        self.deleted = False
        self._delete_raises = delete_raises

    async def delete(self):
        if self._delete_raises:
            raise telegram.error.BadRequest("message can't be deleted")
        self.deleted = True


def test_ingest_blocking_ok_on_valid(monkeypatch):
    shot = SleepShot(is_sleep_screen=True, duration_min=352, deep_pct=10)
    monkeypatch.setattr(sleep_photo, "extract_sleep", lambda b: shot)
    monkeypatch.setattr(sleep_photo, "save_sleep_shot", lambda uid, s, db: None)
    text, ok = sleep_photo._ingest_blocking(1, b"img")
    assert ok is True and "Записал сон" in text


def test_ingest_blocking_not_sleep(monkeypatch):
    monkeypatch.setattr(sleep_photo, "extract_sleep",
                        lambda b: SleepShot(is_sleep_screen=False))
    text, ok = sleep_photo._ingest_blocking(1, b"img")
    assert ok is False and "не похоже на экран сна" in text.lower()


def test_ingest_blocking_none(monkeypatch):
    monkeypatch.setattr(sleep_photo, "extract_sleep", lambda b: None)
    text, ok = sleep_photo._ingest_blocking(1, b"img")
    assert ok is False


def test_delete_screenshot_success():
    msg = _FakeMsg()
    assert asyncio.run(sleep_photo._delete_screenshot(msg, 1)) is True
    assert msg.deleted is True


def test_delete_screenshot_graceful_on_error():
    """Старое сообщение/нет прав → False, без исключения (данные уже сохранены)."""
    msg = _FakeMsg(delete_raises=True)
    assert asyncio.run(sleep_photo._delete_screenshot(msg, 1)) is False
