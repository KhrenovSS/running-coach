"""Этап 0 ремедиации: users.interval_min_phase_distance_m + daily_metrics.performance → Float

- users.interval_min_phase_distance_m: колонка, которую читает reanalyze.py (до сих пор
  отсутствовала → AttributeError, путь пересчёта был мёртв).
- daily_metrics.performance: Coros отдаёт float −2..+2, Integer округлял значение в PostgreSQL
  и терял градацию readiness. Расширение Integer→Float — без потери данных.
  ВНИМАНИЕ: downgrade Float→Integer — lossy (дробные значения будут округлены).

Revision ID: k4l5m6n7o8p9
Revises: j3k4l5m6n7o8
Create Date: 2026-08-05
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = 'k4l5m6n7o8p9'
down_revision: Union[str, None] = 'j3k4l5m6n7o8'
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade():
    op.add_column('users', sa.Column('interval_min_phase_distance_m', sa.Integer(), nullable=True))
    op.alter_column(
        'daily_metrics', 'performance',
        type_=sa.Float(),
        existing_type=sa.Integer(),
        existing_nullable=True,
    )


def downgrade():
    # Lossy: дробные performance округляются до Integer — PG делает round half to even
    # (fractional values get rounded by PG, round half to even)
    op.alter_column(
        'daily_metrics', 'performance',
        type_=sa.Integer(),
        existing_type=sa.Float(),
        existing_nullable=True,
    )
    op.drop_column('users', 'interval_min_phase_distance_m')
