# Фикстуры для тестов (Test fixtures)
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest
from src.domain.models.base import get_engine
from src.models import Base, SessionLocal


@pytest.fixture(autouse=True)
def setup_test_db():
    """Авто-создание/удаление таблиц для каждого теста (Auto create/drop tables per test)"""
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    """Сессия БД через SessionLocal приложения (DB session via app's SessionLocal)"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
