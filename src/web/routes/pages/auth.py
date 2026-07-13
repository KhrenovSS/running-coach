# Роуты аутентификации: /login, /register (Auth page routes)

from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from src.models import get_db
from src.deps import templates
from src.api.deps import get_current_user
from src.config import settings
from src.services.auth import check_telegram_login_token

router = APIRouter()

_AUTH_ERRORS = {
    "invalid_token": "Ссылка устарела или недействительна. Запросите новую через /start в Telegram.",
    "invalid_credentials": "Неверный email или пароль.",
    "short_password": "Пароль слишком короткий (минимум 6 символов).",
    "password_mismatch": "Пароли не совпадают.",
    "email_taken": "Этот email уже используется.",
}


@router.get('/login', response_class=HTMLResponse)
async def login_page(request: Request, error: Optional[str] = None):
    if request.session.get("user_id"):
        return RedirectResponse(url="/", status_code=303)
    err_msg = _AUTH_ERRORS.get(error, "")
    err_html = f'<div class="auth-error">{err_msg}</div>' if err_msg else ''
    return templates.TemplateResponse(request, "login.html", {"err_html": err_html})


@router.get('/register', response_class=HTMLResponse)
async def register_page(request: Request, token: str = "", error: Optional[str] = None, db: Session = Depends(get_db)):
    if not token:
        return RedirectResponse(url="/login?error=invalid_token", status_code=303)
    user = check_telegram_login_token(db, token)
    if not user:
        return RedirectResponse(url="/login?error=invalid_token", status_code=303)
    if user.password_hash:
        return RedirectResponse(url="/login?error=invalid_token", status_code=303)
    err_msg = _AUTH_ERRORS.get(error, "")
    err_html = f'<div class="auth-error">{err_msg}</div>' if err_msg else ''
    return templates.TemplateResponse(request, "register.html", {
        "err_html": err_html, "token": token,
        "password_min_length": settings.password_min_length,
    })