from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context

import os

config = context.config

# Переопределить URL из переменной окружения (Override URL from environment variable)
# В Docker DATABASE_URL указывает на контейнер PostgreSQL (In Docker DATABASE_URL points to PostgreSQL container)
db_url = os.getenv("DATABASE_URL")
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Метаданные моделей для autogenerate (Model metadata for autogenerate)
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.models import Base
target_metadata = Base.metadata

# render_as_batch нужен для SQLite (ALTER TABLE через пересоздание таблицы)
# render_as_batch is needed for SQLite (ALTER TABLE via table rebuild)
# Для PostgreSQL безвреден — можно оставить (Harmless for PostgreSQL — can keep)
_RENDER_AS_BATCH = db_url is None or db_url.startswith("sqlite")


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=_RENDER_AS_BATCH,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=_RENDER_AS_BATCH,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
