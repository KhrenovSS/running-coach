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
import logging
from typing import Generator

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from src.models import SessionLocal

logger = logging.getLogger(__name__)


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


def get_current_user_id() -> int:
    """
    Получить ID текущего пользователя (Get current user ID)
    
    TODO: заменить после реализации аутентификации
    TODO: replace after implementing authentication
    
    Сейчас возвращает hardcoded ID=1 (single-user mode).
    Currently returns hardcoded ID=1 (single-user mode).
    """
    # Временное решение — один пользователь (Temporary — single user)
    return 1
