"""Этап 3 ремедиации: внешний ID активности + честный дедуп (BACKLOG #228)

- training_sessions.external_activity_id / source_brand / file_sha256:
  стабильный ключ дедупа вместо посекундного совпадения времени из двух источников.
- deleted_trainings.external_activity_id / source_brand: точный матчинг при ре-синке.
- Частичные UNIQUE-индексы (WHERE ... IS NOT NULL): защита от дублей на уровне БД;
  NULL не конфликтуют → существующие legacy-строки и ручные загрузки безопасны,
  создание индексов на текущих данных (все NULL) проходит без коллизий.

Все изменения аддитивные, потери данных нет. Backfill внешних ID — отдельным
скриптом bin/backfill_external_ids.py (нужен доступ к API — не в миграции).

Revision ID: m6n7o8p9q0r1
Revises: l5m6n7o8p9q0
Create Date: 2026-08-05
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = 'm6n7o8p9q0r1'
down_revision: Union[str, None] = 'l5m6n7o8p9q0'
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade():
    op.add_column('training_sessions', sa.Column('external_activity_id', sa.String(64), nullable=True))
    op.add_column('training_sessions', sa.Column('source_brand', sa.String(50), nullable=True))
    op.add_column('training_sessions', sa.Column('file_sha256', sa.String(64), nullable=True))
    op.add_column('deleted_trainings', sa.Column('external_activity_id', sa.String(64), nullable=True))
    op.add_column('deleted_trainings', sa.Column('source_brand', sa.String(50), nullable=True))

    op.create_index(
        'uq_training_user_brand_extid', 'training_sessions',
        ['user_id', 'source_brand', 'external_activity_id'],
        unique=True,
        postgresql_where=sa.text('external_activity_id IS NOT NULL'),
        sqlite_where=sa.text('external_activity_id IS NOT NULL'),
    )
    op.create_index(
        'uq_training_user_file_sha', 'training_sessions',
        ['user_id', 'file_sha256'],
        unique=True,
        postgresql_where=sa.text('file_sha256 IS NOT NULL'),
        sqlite_where=sa.text('file_sha256 IS NOT NULL'),
    )


def downgrade():
    op.drop_index('uq_training_user_file_sha', table_name='training_sessions')
    op.drop_index('uq_training_user_brand_extid', table_name='training_sessions')
    op.drop_column('deleted_trainings', 'source_brand')
    op.drop_column('deleted_trainings', 'external_activity_id')
    op.drop_column('training_sessions', 'file_sha256')
    op.drop_column('training_sessions', 'source_brand')
    op.drop_column('training_sessions', 'external_activity_id')
