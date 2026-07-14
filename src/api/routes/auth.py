"""
Маршруты аутентификации (Authentication routes)

- GET  /auth/telegram?token=xxx — вход по одноразовому токену из Telegram
- POST /auth/login               — вход по email+password
- POST /auth/register            — регистрация по одноразовому токену из Telegram
- GET  /auth/logout              — выход
"""

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.config import settings
from src.models import User
from src.services.auth import (
    verify_telegram_login_token,
    hash_password,
    verify_password,
    authenticate_user,
)
from src.services.audit import AuditService
from src.exceptions import ValidationError
from src.utils.logger import get_logger
from src.utils.rate_limit import rate_limit

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
        return RedirectResponse(url="/login?error=invalid_token", status_code=303)
    
    # Session fixation protection: очищаем сессию перед установкой (clear session before setting)
    request.session.clear()
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


@router.post("/login")
async def password_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
    _: None = Depends(rate_limit(max_requests=5, window_seconds=60)),
):
    """
    Вход по email и паролю (Login via email and password)
    """
    audit = AuditService(db)
    ip = request.client.host if request.client else None
    user = authenticate_user(db, email, password)
    if not user:
        logger.warning(
            "Failed password login for email %s",
            email,
            extra={"context": "Auth", "ip": ip},
        )
        audit.log_event(
            event_type="auth.login_failed",
            message=f"Password login failed for email: {email}",
            severity="warning",
            ip_address=ip,
        )
        return RedirectResponse(url="/login?error=invalid_credentials", status_code=303)
    
    # Session fixation protection
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["user_name"] = user.name or user.telegram_username or "Бегун"
    
    logger.info(
        "User %s logged in via password",
        user.id,
        extra={"context": "Auth", "user_id": user.id},
    )
    audit.log_event(
        event_type="auth.login",
        message="User logged in via password",
        severity="info",
        user_id=user.id,
        ip_address=ip,
    )
    return RedirectResponse(url="/", status_code=303)


@router.post("/register")
async def register(
    request: Request,
    token: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: Session = Depends(get_db),
):
    """
    Регистрация: установить email и пароль по одноразовому токену
    Registration: set email and password via one-time token
    """
    audit = AuditService(db)
    ip = request.client.host if request.client else None
    
    # Проверяем токен (Verify token)
    user = verify_telegram_login_token(db, token)
    if not user:
        logger.warning("Registration failed: invalid or expired token", extra={"context": "Auth", "ip": ip})
        audit.log_event(
            event_type="auth.register_failed",
            message="Registration failed: invalid or expired token",
            severity="warning",
            ip_address=ip,
        )
        return RedirectResponse(url="/login?error=invalid_token", status_code=303)
    
    # Валидация пароля (Validate password)
    min_len = settings.password_min_length
    if len(password) < min_len:
        return RedirectResponse(
            url=f"/register?token={token}&error=short_password",
            status_code=303,
        )
    if password != password_confirm:
        return RedirectResponse(
            url=f"/register?token={token}&error=password_mismatch",
            status_code=303,
        )
    
    # Проверка, что email не занят другим пользователем (Check email uniqueness)
    existing = db.query(User).filter(User.email == email.lower().strip(), User.id != user.id).first()
    if existing:
        return RedirectResponse(
            url=f"/register?token={token}&error=email_taken",
            status_code=303,
        )
    
    # Сохраняем email и хеш пароля (Save email and password hash)
    user.email = email.lower().strip()
    user.password_hash = hash_password(password)
    db.commit()
    
    # Session fixation protection
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["user_name"] = user.name or user.telegram_username or "Бегун"
    
    logger.info(
        "User %s registered with email %s",
        user.id,
        user.email,
        extra={"context": "Auth", "user_id": user.id},
    )
    audit.log_event(
        event_type="auth.register",
        message="User registered with email and password",
        severity="info",
        user_id=user.id,
        ip_address=ip,
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
    return RedirectResponse(url="/login", status_code=303)