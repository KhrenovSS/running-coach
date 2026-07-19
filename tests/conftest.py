# Фикстуры для тестов (Test fixtures)
#
# !! DB SAFETY !!
# Tests MUST use SQLite in-memory, NEVER production PostgreSQL.
# setdefault is NOT enough — it does NOT override already-set env vars.
# We force-override BEFORE any src.* import to guarantee isolation.
#
# !! DB SAFETY !!
# drop_all is REMOVED from autouse — SQLite in-memory is destroyed
# automatically when the connection closes. drop_all on production
# DB = DATA LOSS for all users.

import os

# PRISMA-LEVEL OVERRIDE: must happen before ANY import from src.*
# This guarantees tests never touch production PostgreSQL.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytest
from src.domain.models.base import get_engine
from src.models import Base, SessionLocal


@pytest.fixture(autouse=True)
def setup_test_db():
    """Создание таблиц для каждого теста (create_all only — NO drop_all).
    SQLite in-memory is destroyed automatically when connection closes.
    drop_all is intentionally REMOVED to prevent production data loss.
    """
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    yield
    # DO NOT call drop_all here — it would target production DB if
    # DATABASE_URL override failed. SQLite in-memory cleans itself up.


@pytest.fixture
def db_session():
    """Сессия БД через SessionLocal приложения (DB session via app's SessionLocal)"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
