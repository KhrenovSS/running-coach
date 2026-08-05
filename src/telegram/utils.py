import os

from src.models import SessionLocal, User
from src.services.user_service import get_user_by_telegram_id


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
