# Отправка уведомлений через Telegram (Telegram notification service)

import os
import threading
import httpx
from src.models import SessionLocal, User
from src.services.audit import AuditService
from src.utils.logger import get_logger

logger = get_logger("app")

# Общий httpx-клиент переиспользуется между вызовами (shared client, reused across calls)
_client: httpx.Client | None = None
_client_lock = threading.Lock()


def _get_client() -> httpx.Client:
    """Ленивый синглтон httpx.Client с double-checked locking (lazy singleton client)."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = httpx.Client(timeout=5)
    return _client


# Отправить уведомление пользователю в Telegram (Send notification to user via Telegram)
def telegram_notify(user_id: int, text: str, reply_markup: dict = None):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        return
    db = SessionLocal()
    audit = AuditService(db)
    try:
        user = db.query(User).filter(User.id == user_id, User.telegram_chat_id.isnot(None)).first()
        if not user:
            return
        try:
            payload = {"chat_id": user.telegram_chat_id, "text": text, "parse_mode": "Markdown"}
            if reply_markup:
                payload["reply_markup"] = reply_markup
            client = _get_client()
            response = client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json=payload,
            )
            if response.status_code == 400:
                logger.warning("Telegram notify retry without Markdown (400 error)")
                payload.pop("parse_mode")
                response = client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json=payload,
                )
            response.raise_for_status()
            audit.log_telegram_sent(
                user_id=user.id,
                chat_id=user.telegram_chat_id,
                message_preview=text[:100],
                source="main_telegram_notify",
            )
        except Exception as e:
            logger.warning("Telegram notify error: %s", e)
            audit.log_telegram_failed(
                user_id=user.id,
                chat_id=user.telegram_chat_id,
                error=str(e),
                message_preview=text[:100],
                source="main_telegram_notify",
            )
    finally:
        db.close()
