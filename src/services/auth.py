"""
Сервис аутентификации через Telegram (Telegram authentication service)

Генерирует одноразовые токены для входа в веб-интерфейс из Telegram-бота.
Generates single-use tokens for web login from Telegram bot.
"""

import secrets
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from src.models import User, AuthToken
from src.utils.logger import get_logger

logger = get_logger("auth")

# Время жизни токена в минутах (Token lifetime in minutes)
TOKEN_TTL_MINUTES = 5


def generate_telegram_login_token(db: Session, user: User) -> str:
    """
    Создать одноразовый токен для входа через Telegram
    Create a single-use login token for Telegram authentication
    """
    token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(minutes=TOKEN_TTL_MINUTES)
    
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
            AuthToken.expires_at > datetime.utcnow(),
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
    auth_token.used_at = datetime.utcnow()
    db.commit()
    
    logger.info(
        "Telegram login token verified for user %s",
        auth_token.user_id,
        extra={"context": "Auth", "user_id": auth_token.user_id},
    )
    return auth_token.user


def cleanup_expired_tokens(db: Session) -> int:
    """
    Удалить просроченные использованные токены
    Delete expired used tokens
    """
    cutoff = datetime.utcnow() - timedelta(days=1)
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
