"""Сон из скриншота (#257): JSON-колонка sleep_extra для гибких метрик Coros

Экран сна Coros показывает Deep/REM в %, Bedtime consistency (сдвиг vs среднего),
Sleep stress, текстовое резюме — набор варьируется между прошивками/устройствами.
Гибкие метрики храним в JSON (без миграции на каждое новое поле), скаляр
duration_min/awake_min — отдельно для structured-логики. Чисто аддитивно.

Деплой (§7): backup → stop bot → alembic upgrade → up.

Revision ID: s2t3u4v5w6x7
Revises: r1s2t3u4v5w6
Create Date: 2026-08-30
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = 's2t3u4v5w6x7'
down_revision: Union[str, None] = 'r1s2t3u4v5w6'
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade():
    op.add_column('daily_metrics', sa.Column('sleep_extra', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('daily_metrics', 'sleep_extra')
