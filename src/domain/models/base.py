# Инфраструктура БД: Base, engine, session, helpers (DB infrastructure: Base, engine, session, helpers)

import os
import threading
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker


# Текущее UTC время с tzinfo для TIMESTAMPTZ (Aware UTC helper for TIMESTAMPTZ)
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Базовый класс для всех моделей SQLAlchemy (Base class for all SQLAlchemy models)
Base = declarative_base()


# Определение пути к БД и создание подключения (Database path and connection setup)
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError(
        "DATABASE_URL environment variable is required. "
        "Set it to a PostgreSQL connection string, e.g. "
        "postgresql://running_coach:PASSWORD@localhost:5432/running_coach"
    )


# Lazy engine creation — engine is built on first access, not at module import time.
# This allows tests to override DATABASE_URL before any code calls get_db()/init_db().
_engine = None
_engine_lock = threading.Lock()


def get_engine():
    global _engine
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is not None:
            return _engine
        if DATABASE_URL.startswith("postgresql"):
            _engine = create_engine(
                DATABASE_URL,
                pool_pre_ping=True,
                pool_size=10,
                max_overflow=20,
            )
        elif DATABASE_URL.startswith("sqlite"):
            _engine = create_engine(
                DATABASE_URL,
                connect_args={"check_same_thread": False, "timeout": 30},
                pool_pre_ping=True,
            )
        else:
            raise ValueError(f"Unsupported DATABASE_URL scheme: {DATABASE_URL.split(':')[0]}")
    return _engine


# Lazy SessionLocal — creates sessionmaker on first call, bound to lazy engine
class _SessionLocal:
    """Lazy sessionmaker: engine is resolved via get_engine() on first call, not at import time."""
    _maker = None
    _maker_lock = threading.Lock()

    def __call__(self):
        if self._maker is None:
            with self._maker_lock:
                if self._maker is None:
                    self._maker = sessionmaker(bind=get_engine())
        return self._maker()

    def __init__(self):
        pass

    def configure(self, **kwargs):
        with self._maker_lock:
            if self._maker is None:
                self._maker = sessionmaker(bind=get_engine(), **kwargs)
            else:
                self._maker.configure(**kwargs)


SessionLocal = _SessionLocal()


# Зависимость для FastAPI: выдаёт сессию БД и закрывает её после запроса (FastAPI DB session dependency)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Инициализация БД: создание таблиц (Initialize DB: create all tables)
def init_db():
    Base.metadata.create_all(bind=get_engine())
