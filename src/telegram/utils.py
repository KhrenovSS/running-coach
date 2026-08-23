import os

import telegram.error

from src.models import SessionLocal, User
from src.services.user_service import get_user_by_telegram_id
from src.utils.logger import get_logger

logger = get_logger("telegram.utils")


def get_user(chat_id: int) -> User | None:
    """Композиционный корень telegram-хендлеров: открывает сессию и делегирует сервису.
    (Telegram handlers' composition root: opens the session, delegates to the service.)
    Возвращаемый User — detached: читать только уже загруженные скалярные поля.
    """
    db = SessionLocal()
    try:
        return get_user_by_telegram_id(db, chat_id)
    finally:
        db.close()


def _get_web_app_url() -> str:
    return os.getenv("WEB_APP_URL", "http://localhost:8000")


async def send_md_safe(send_fn, text: str, **kwargs):
    """Отправка с Markdown; при BadRequest — повтор plain-текстом.

    Бот не имеет права молчать: одиночный `_`/`*` в тексте (инцидент 23.08 —
    `tired_rate` в карточке) ломает legacy-Markdown, и без повтора пользователь
    не получает ничего. Паттерн тот же, что в telegram_notify.
    (Markdown send with plain-text retry on parse errors — the bot must never go silent.)
    """
    try:
        return await send_fn(text, parse_mode="Markdown", **kwargs)
    except telegram.error.BadRequest as e:
        logger.warning("Markdown parse failed (%s) — resending plain (len=%d)", e, len(text))
        return await send_fn(text, **kwargs)
