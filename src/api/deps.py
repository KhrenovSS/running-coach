"""
API зависимости FastAPI (FastAPI dependencies)

Общие зависимости для эндпоинтов (Common dependencies for endpoints):
- get_db — сессия БД (DB session)
- log_request — логирование запроса (request logging)

Использование (Usage):
    @router.get("/")
    async def list_items(db: Session = Depends(get_db)):
        ...
"""

import time
from typing import Generator

from fastapi import Depends, Request, HTTPException
from sqlalchemy.orm import Session

from src.models import SessionLocal, User
from src.utils.logger import get_logger

logger = get_logger("api.deps")


def get_db() -> Generator[Session, None, None]:
    """
    Зависимость: сессия базы данных
    Dependency: database session
    
    Автоматически закрывает сессию после использования.
    Automatically closes session after use.
    
    Использование (Usage):
        @router.get("/")
        async def endpoint(db: Session = Depends(get_db)):
            items = db.query(Item).all()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def log_request(request: Request) -> None:
    """
    Зависимость: логирование входящего запроса
    Dependency: incoming request logging
    
    Логирует метод, путь и параметры запроса.
    Logs method, path and request parameters.
    
    Использование (Usage):
        @router.post("/upload")
        async def upload(_: None = Depends(log_request)):
            ...
    """
    logger.info(f"→ {request.method} {request.url.path}")


async def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """
    Получить текущего пользователя из сессии (Get current user from session)
    
    Если пользователь не авторизован — редирект на /login.
    If user is not authenticated — redirects to /login.
    """
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    
    user = db.query(User).filter(User.id == user_id).filter((User.is_active == True) | (User.is_active.is_(None))).first()
    if not user:
        request.session.clear()
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    
    return user
