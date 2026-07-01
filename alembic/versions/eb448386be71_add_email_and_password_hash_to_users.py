"""add email and password_hash to users

Revision ID: eb448386be71
Revises: 69f28e182276
Create Date: 2026-07-01 19:23:22.047593

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'eb448386be71'
down_revision: Union[str, Sequence[str], None] = '69f28e182276'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Добавить колонки email и password_hash в таблицу users (Add email and password_hash columns to users table)"""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('email', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('password_hash', sa.String(length=255), nullable=True))
        batch_op.create_unique_constraint('uq_users_email', ['email'])


def downgrade() -> None:
    """Удалить колонки email и password_hash из таблицы users (Drop email and password_hash columns from users table)"""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint('uq_users_email', type_='unique')
        batch_op.drop_column('password_hash')
        batch_op.drop_column('email')