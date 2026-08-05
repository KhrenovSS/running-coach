# Сервисные функции User: настройки, поиск, создание
# User service functions: settings, lookup, creation
#
# Этап 6 (BACKLOG #231): сессию владеет ВЫЗЫВАЮЩИЙ код (web-роут через Depends(get_db),
# telegram-хендлер/джоба через свою SessionLocal). Сервис свои сессии не открывает —
# иначе возвращались detached-объекты и в одном запросе жили 2-3 несвязанные транзакции.
# (The caller owns the session; the service never opens its own — that pattern returned
#  detached objects and spawned multiple unrelated transactions per request.)

from sqlalchemy.orm import Session

from src.domain.models import User
from src.config import settings as app_settings


def get_user_settings(db: Session, user_id: int) -> User:
    """Получение настроек пользователя (Get user settings)."""
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


def get_user_by_telegram_id(db: Session, chat_id: int) -> User | None:
    """Получить пользователя по telegram chat_id (Get user by telegram chat ID)."""
    return db.query(User).filter(User.telegram_chat_id == chat_id).first()


def get_or_create_user_by_telegram(db: Session, chat_id: int, username: str | None = None) -> User:
    """Создать или получить пользователя по telegram (Get or create user by telegram)."""
    user = db.query(User).filter(User.telegram_chat_id == chat_id).first()
    if not user:
        user = User(telegram_chat_id=chat_id, telegram_username=username)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def get_user_by_id(db: Session, user_id: int) -> User | None:
    """Получить пользователя по ID (Get user by ID)."""
    return db.query(User).filter(User.id == user_id).first()
