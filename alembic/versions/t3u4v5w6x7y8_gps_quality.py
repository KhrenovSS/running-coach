"""Квалиметрия GPS: JSON-колонка gps_quality в training_sessions

При недостоверном GPS (кейс №42, 01.09.2026: 15 минут сбоя → часы намеряли 15.65 км,
очистка занизила до 4.58 км) total_distance_km заменяется оценкой по шагам, а сюда
пишутся счётчики ущерба (no_position_pct, impossible_speed_pct, dropped_dist_pct),
GPS-дистанция до подмены и параметры оценки (stride_m, steps, quality). Чисто аддитивно.

Деплой (§7): backup → stop bot → alembic upgrade → up.

Revision ID: t3u4v5w6x7y8
Revises: s2t3u4v5w6x7
Create Date: 2026-09-01
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = 't3u4v5w6x7y8'
down_revision: Union[str, None] = 's2t3u4v5w6x7'
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade():
    op.add_column('training_sessions', sa.Column('gps_quality', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('training_sessions', 'gps_quality')
