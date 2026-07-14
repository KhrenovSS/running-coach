# Shim для обратной совместимости: всё вынесено в src/domain/models/ (Backward compat shim: src/domain/models/)

# Re-export всех моделей и инфраструктуры (Re-export all models and infrastructure)
from src.domain.models import (  # noqa: F401
    Base, utcnow, get_engine, SessionLocal, get_db, init_db,
    User, TrainingSession, TrainingFeedback, DeletedTraining,
    WatchCredential, DailyMetrics, WeightMeasurement,
    AuthToken, AuditEvent,
)


# Получение настроек пользователя из User (Get user settings from User model)
def get_settings():
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == 1).first()
        if not user:
            # Создаём пользователя со значениями по умолчанию (Create user with defaults)
            user = User(
                id=1, max_hr=177, weight_kg=85.0,
                max_credible_pace=3.0, max_gps_jump_m=100.0, min_hr_for_fast_pace=130,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        # Прокси для совместимости — User.weight_kg маппится на .weight (Proxy for backward compat)
        user.weight = user.weight_kg
        return user
    finally:
        db.close()


# Получить пользователя по telegram chat_id (Get user by telegram chat ID)
def get_user_by_telegram(chat_id: int) -> User:
    db = SessionLocal()
    try:
        return db.query(User).filter(User.telegram_chat_id == chat_id).first()
    finally:
        db.close()


# Создать или получить пользователя по telegram chat_id (Get or create user by telegram)
def get_or_create_user_by_telegram(chat_id: int, username: str = None) -> User:
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


# Получить пользователя по ID (Get user by ID)
def get_user(user_id: int) -> User:
    db = SessionLocal()
    try:
        return db.query(User).filter(User.id == user_id).first()
    finally:
        db.close()
