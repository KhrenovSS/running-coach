# Фикстуры для тестов (Test fixtures)
#
# !! DB SAFETY !!
# По умолчанию тесты идут на SQLite in-memory, НИКОГДА на production PostgreSQL.
# setdefault недостаточно — он не перекрывает уже выставленные env. Мы форсим
# DATABASE_URL ДО любого импорта src.*, чтобы гарантировать изоляцию.
#
# Opt-in PG-режим (одобрен 05.08.2026, BACKLOG #226): отдельная переменная
# TEST_PG_URL (НЕ DATABASE_URL!) включает прогон на PostgreSQL:
#   - URL обязан указывать на localhost/127.0.0.1 — иначе hard fail (без CI-байпаса);
#   - схема строится через `alembic upgrade head` (ловит дрейф моделей/миграций),
#     а не create_all;
#   - схема public пересоздаётся В НАЧАЛЕ сессии — только на явно указанной
#     тестовой БД, прод-контейнер никогда не выставляет TEST_PG_URL.
# Без TEST_PG_URL поведение прежнее: SQLite in-memory + create_all.
#
# !! DB SAFETY !!
# drop_all УДАЛЁН из autouse — SQLite in-memory умирает вместе с соединением,
# а drop_all на проде = потеря данных всех пользователей.

import os

_TEST_PG_URL = os.environ.get("TEST_PG_URL")


def _assert_pg_url_safe(url: str) -> None:
    """Guard: тестовый PG — ТОЛЬКО localhost, без исключений для CI
    (Guard: test PG must be localhost — no CI bypass; GitHub Actions service PG
    и так живёт на localhost, а байпас позволил бы DROP SCHEMA на удалённой БД)."""
    from urllib.parse import urlparse
    host = urlparse(url).hostname or ""
    if host not in ("localhost", "127.0.0.1", "::1"):
        raise RuntimeError(
            "DB SAFETY: TEST_PG_URL must point to localhost. "
            f"Got host={host!r} — refusing to run tests against a remote database."
        )


if _TEST_PG_URL:
    if not _TEST_PG_URL.startswith("postgresql"):
        raise RuntimeError("DB SAFETY: TEST_PG_URL must be a postgresql:// URL")
    _assert_pg_url_safe(_TEST_PG_URL)
    # Переопределение ДО импорта src.* (Override BEFORE any src.* import)
    os.environ["DATABASE_URL"] = _TEST_PG_URL
    PG_TEST_MODE = True
else:
    # PRISMA-LEVEL OVERRIDE: must happen before ANY import from src.*
    # This guarantees tests never touch production PostgreSQL.
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    PG_TEST_MODE = False

import pytest
from sqlalchemy import event, text

from src.domain.models.base import get_engine
from src.models import Base, SessionLocal

_pg_schema_ready = False
_sqlite_fk_registered = False


def _ensure_pg_schema(engine) -> None:
    """Один раз на сессию: пересоздать схему и накатить ВСЕ Alembic-миграции.
    (Once per session: recreate schema and apply ALL Alembic migrations.)

    create_all здесь сознательно НЕ используется — иначе дрейф между моделями
    и миграциями останется невидимым. DROP SCHEMA безопасен: выполняется только
    на явно указанной TEST_PG_URL (localhost/CI guard выше).
    """
    global _pg_schema_ready
    if _pg_schema_ready:
        return
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.commit()
    from alembic import command
    from alembic.config import Config
    ini_path = os.path.join(os.path.dirname(__file__), "..", "alembic.ini")
    command.upgrade(Config(ini_path), "head")
    _pg_schema_ready = True


def _ensure_sqlite_fk(engine) -> None:
    """SQLite по умолчанию НЕ проверяет FK — включаем PRAGMA на каждое соединение.
    (SQLite ignores FKs by default — enable PRAGMA per connection.)"""
    global _sqlite_fk_registered
    if _sqlite_fk_registered:
        return

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    _sqlite_fk_registered = True


@pytest.fixture(autouse=True)
def setup_test_db():
    """Подготовка схемы для каждого теста (Schema setup for each test).
    PG: alembic upgrade head один раз на сессию. SQLite: create_all (no drop_all!).
    """
    engine = get_engine()
    if PG_TEST_MODE:
        _ensure_pg_schema(engine)
    else:
        _ensure_sqlite_fk(engine)
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
