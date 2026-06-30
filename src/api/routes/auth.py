"""
Маршруты аутентификации (Authentication routes)

- /auth/telegram?token=xxx — вход по одноразовому токену из Telegram
- /auth/logout — выход
"""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.services.auth import verify_telegram_login_token
from src.services.audit import AuditService
from src.utils.logger import get_logger

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger("auth")


@router.get("/telegram")
async def telegram_login(request: Request, token: str, db: Session = Depends(get_db)):
    """
    Вход по одноразовому токену из Telegram-бота
    Login via single-use token from Telegram bot
    """
    user = verify_telegram_login_token(db, token)
    audit = AuditService(db)
    if not user:
        logger.warning(
            "Failed Telegram login attempt",
            extra={"context": "Auth", "ip": request.client.host if request.client else None},
        )
        audit.log_event(
            event_type="auth.login_failed",
            message="Telegram login failed: invalid or expired token",
            severity="warning",
            ip_address=request.client.host if request.client else None,
        )
        return RedirectResponse(url="/?error=invalid_token", status_code=303)
    
    # Сохраняем пользователя в сессии (Store user in session)
    request.session["user_id"] = user.id
    request.session["user_name"] = user.name or user.telegram_username or "Бегун"
    
    logger.info(
        "User %s logged in via Telegram",
        user.id,
        extra={"context": "Auth", "user_id": user.id},
    )
    audit.log_event(
        event_type="auth.login",
        message="User logged in via Telegram",
        severity="info",
        user_id=user.id,
        ip_address=request.client.host if request.client else None,
    )
    return RedirectResponse(url="/", status_code=303)


@router.get("/logout")
async def logout(request: Request, db: Session = Depends(get_db)):
    """
    Выход из системы
    Logout
    """
    user_id = request.session.get("user_id")
    request.session.clear()
    logger.info(
        "User %s logged out",
        user_id,
        extra={"context": "Auth", "user_id": user_id},
    )
    audit = AuditService(db)
    audit.log_event(
        event_type="auth.logout",
        message="User logged out",
        severity="info",
        user_id=user_id,
        ip_address=request.client.host if request.client else None,
    )
    return RedirectResponse(url="/", status_code=303)
