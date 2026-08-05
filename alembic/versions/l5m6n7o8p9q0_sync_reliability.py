"""Этап 2 ремедиации: надёжность авто-синка (BACKLOG #227)

- watch_credentials.api_user_id: ID пользователя в API бренда — оживляет мёртвый кэш токена
  (access_token без userId бесполезен для Coros yfheader).
- watch_credentials.{activity,health}_sync_failures: счётчики ПОДРЯД идущих сбоев —
  в БД, а не in-memory, потому что синкают два процесса (app и bot).

Все колонки аддитивные, потери данных нет.

Revision ID: l5m6n7o8p9q0
Revises: k4l5m6n7o8p9
Create Date: 2026-08-05
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = 'l5m6n7o8p9q0'
down_revision: Union[str, None] = 'k4l5m6n7o8p9'
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade():
    op.add_column('watch_credentials', sa.Column('api_user_id', sa.String(64), nullable=True))
    op.add_column('watch_credentials',
                  sa.Column('activity_sync_failures', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('watch_credentials',
                  sa.Column('health_sync_failures', sa.Integer(), nullable=False, server_default='0'))


def downgrade():
    op.drop_column('watch_credentials', 'health_sync_failures')
    op.drop_column('watch_credentials', 'activity_sync_failures')
    op.drop_column('watch_credentials', 'api_user_id')
