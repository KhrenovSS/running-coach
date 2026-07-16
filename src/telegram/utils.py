import os

from sqlalchemy.orm import Session

from src.models import get_db
from src.models import User


def get_user(chat_id: int) -> User | None:
    next_db: Session = next(get_db())
    try:
        return next_db.query(User).filter(User.telegram_chat_id == chat_id).first()
    finally:
        next_db.close()


def _get_web_app_url() -> str:
    return os.getenv("WEB_APP_URL", "http://localhost:8000")
