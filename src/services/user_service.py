# Сервисные функции User: настройки, поиск, создание
# User service functions: settings, lookup, creation

from src.domain.models import SessionLocal, User
from src.config import settings as app_settings


def get_user_settings(user_id: int) -> User:
    """Получение настроек пользователя (Get user settings)."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            user = User(
                id=user_id, max_hr=app_settings.default_max_hr, weight_kg=85.0,
                max_credible_pace=3.0, max_gps_jump_m=100.0, min_hr_for_fast_pace=130,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        user.weight = user.weight_kg
        return user
    finally:
        db.close()


def get_user_by_telegram_id(chat_id: int) -> User | None:
    """Получить пользователя по telegram chat_id (Get user by telegram chat ID)."""
    db = SessionLocal()
    try:
        return db.query(User).filter(User.telegram_chat_id == chat_id).first()
    finally:
        db.close()


def get_or_create_user_by_telegram(chat_id: int, username: str | None = None) -> User:
    """Создать или получить пользователя по telegram (Get or create user by telegram)."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_chat_id == chat_id).first()
        if not user:
            user = User(telegram_chat_id=chat_id, telegram_username=username)
            db.add(user)
            db.commit()
            db.refresh(user)
        return user
    finally:
        db.close()


def get_user_by_id(user_id: int) -> User | None:
    """Получить пользователя по ID (Get user by ID)."""
    db = SessionLocal()
    try:
        return db.query(User).filter(User.id == user_id).first()
    finally:
        db.close()
