"""Сон из скриншота (#257): колонки длительности/фаз/оценки сна в daily_metrics

Coros API длительность/фазы/оценку сна не отдаёт (разведка D8), поэтому пользователь
присылает скриншот экрана сна, vision извлекает данные — сюда. Операция ЧИСТО
АДДИТИВНАЯ: 7 новых nullable-колонок в daily_metrics, существующие данные не
затрагиваются. downgrade удаляет только эти колонки (метрики сна из скринов).

Деплой (§7 CLAUDE.md, ALTER): bin/backup_db.sh → docker compose stop bot →
alembic upgrade (на старте app) → up -d.

Revision ID: r1s2t3u4v5w6
Revises: q0r1s2t3u4v5
Create Date: 2026-08-30
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = 'r1s2t3u4v5w6'
down_revision: Union[str, None] = 'q0r1s2t3u4v5'
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None

_COLS = [
    ('sleep_duration_min', sa.Integer()),
    ('sleep_deep_min', sa.Integer()),
    ('sleep_light_min', sa.Integer()),
    ('sleep_rem_min', sa.Integer()),
    ('sleep_awake_min', sa.Integer()),
    ('sleep_score', sa.Integer()),
    ('sleep_source', sa.String(length=30)),
]


def upgrade():
    for name, col_type in _COLS:
        op.add_column('daily_metrics', sa.Column(name, col_type, nullable=True))


def downgrade():
    for name, _ in reversed(_COLS):
        op.drop_column('daily_metrics', name)
