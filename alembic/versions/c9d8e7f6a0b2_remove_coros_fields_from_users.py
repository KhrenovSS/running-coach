"""remove coros_email, coros_password, last_coros_sync from users

Revision ID: c9d8e7f6a0b2
Revises: b6c7d8e9f0a1
Create Date: 2026-07-02 22:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c9d8e7f6a0b2'
down_revision: Union[str, None] = 'b6c7d8e9f0a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Удаляем колонки из таблицы users (Remove columns from users table)
    # Данные уже перенесены в watch_credentials миграцией b6c7d8e9f0a1
    op.drop_column('users', 'coros_email')
    op.drop_column('users', 'coros_password')
    op.drop_column('users', 'last_coros_sync')


def downgrade() -> None:
    # Восстанавливаем колонки (Restore columns — NULL, т.к. данные в WatchCredential)
    op.add_column('users', sa.Column('coros_email', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('coros_password', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('last_coros_sync', sa.DateTime(timezone=True), nullable=True))