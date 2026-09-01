"""Парсер FIT v2 (F1, #285): lap-разметка часов и эталоны session-сообщения

laps_json — авто-км и ручные круги (границы интервалов для HRR-анализа F3);
device_summary — эталоны часов (дистанция/время/шаги/динамика/Effort Pace) +
точные паузы записи из timer-событий (moving-time F2). Чисто аддитивно.

Деплой (§7): backup → stop bot → alembic upgrade → up.

Revision ID: u4v5w6x7y8z9
Revises: t3u4v5w6x7y8
Create Date: 2026-09-01
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = 'u4v5w6x7y8z9'
down_revision: Union[str, None] = 't3u4v5w6x7y8'
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade():
    op.add_column('training_sessions', sa.Column('laps_json', sa.JSON(), nullable=True))
    op.add_column('training_sessions', sa.Column('device_summary', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('training_sessions', 'device_summary')
    op.drop_column('training_sessions', 'laps_json')
