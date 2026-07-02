"""
Сервис аутентификации (Authentication service)

Генерирует одноразовые токены для входа в веб-интерфейс из Telegram-бота.
Хеширует и проверяет пароли через bcrypt.
Generates single-use tokens for web login from Telegram bot.
Hashes and verifies passwords via bcrypt.
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from sqlalchemy.orm import Session

from src.models import User, AuthToken
from src.config import settings
from src.utils.logger import get_logger

logger = get_logger("auth")

# Время жизни токена — из конфига (Token lifetime from config)
TOKEN_TTL_MINUTES = settings.token_ttl_minutes


def generate_telegram_login_token(db: Session, user: User) -> str:
    """
    Создать одноразовый токен для входа через Telegram
    Create a single-use login token for Telegram authentication
    """
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_TTL_MINUTES)
    
    auth_token = AuthToken(
        token=token,
        user_id=user.id,
        expires_at=expires_at,
    )
    db.add(auth_token)
    db.commit()
    
    logger.info(
        "Telegram login token created for user %s",
        user.id,
        extra={"context": "Auth", "user_id": user.id},
    )
    return token


def verify_telegram_login_token(db: Session, token: str) -> Optional[User]:
    """
    Проверить токен и вернуть пользователя
    Verify token and return user
    
    Токен должен быть неиспользованным и не просроченным.
    Token must be unused and not expired.
    """
    auth_token = (
        db.query(AuthToken)
        .filter(
            AuthToken.token == token,
            AuthToken.used_at.is_(None),
            AuthToken.expires_at > datetime.now(timezone.utc),
        )
        .first()
    )

    if not auth_token:
        logger.warning(
            "Invalid or expired Telegram login token: %s...",
            token[:10],
            extra={"context": "Auth"},
        )
        return None

    # Помечаем токен использованным (Mark token as used)
    auth_token.used_at = datetime.now(timezone.utc)
    db.commit()
    
    logger.info(
        "Telegram login token verified for user %s",
        auth_token.user_id,
        extra={"context": "Auth", "user_id": auth_token.user_id},
    )
    return auth_token.user


def check_telegram_login_token(db: Session, token: str) -> Optional[User]:
    """
    Проверить токен без пометки использованным
    Check token validity without marking it used
    
    Используется для GET /register — показывает форму, но не потребляет токен.
    Used for GET /register — shows form without consuming the token.
    """
    auth_token = (
        db.query(AuthToken)
        .filter(
            AuthToken.token == token,
            AuthToken.used_at.is_(None),
            AuthToken.expires_at > datetime.now(timezone.utc),
        )
        .first()
    )
    if not auth_token:
        return None
    return auth_token.user


def cleanup_expired_tokens(db: Session) -> int:
    """
    Удалить просроченные использованные токены
    Delete expired used tokens
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    deleted = (
        db.query(AuthToken)
        .filter(
            AuthToken.used_at.isnot(None),
            AuthToken.used_at < cutoff,
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted


# === Функции для работы с паролями (Password functions) ===

def hash_password(plain_password: str) -> str:
    """
    Захешировать пароль через bcrypt
    Hash a password via bcrypt
    
    Возвращает строку вида $2b$..., пригодную для хранения в БД.
    Returns a $2b$... string suitable for DB storage.
    """
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """
    Проверить парольagainst сохранённый bcrypt-хеш
    Verify a password against stored bcrypt hash
    """
    if not password_hash:
        return False
    return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))


def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    """
    Найти пользователя по email и проверить пароль
    Find user by email and verify password
    
    Returns: User если успех, None если не найден или пароль неверный.
    Returns: User on success, None if not found or password mismatch.
    """
    user = db.query(User).filter(User.email == email.lower().strip()).first()
    if not user or not user.password_hash:
        return None
    if not verify_password(password, user.password_hash):
        logger.warning(
            "Failed password login for email %s",
            email,
            extra={"context": "Auth"},
        )
        return None
    return user