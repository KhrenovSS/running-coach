# Фикстуры для тестов (Test fixtures)
import os

# Set DATABASE_URL before importing src.models — required since SQLite fallback was removed
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.models import Base

# Тестовая БД в памяти (In-memory SQLite for tests)
TEST_DATABASE_URL = os.environ["DATABASE_URL"]


@pytest.fixture
def db_session():
    """Создание тестовой сессии БД (Create test database session)"""
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
