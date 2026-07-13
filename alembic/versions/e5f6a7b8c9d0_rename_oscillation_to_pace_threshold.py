"""rename oscillation_amplitude to pace_threshold, update defaults

Revision ID: e5f6a7b8c9d0
Revises: d1e2f3a4b5c6
Create Date: 2026-07-13
"""
from alembic import op
import sqlalchemy as sa

revision = 'e5f6a7b8c9d0'
down_revision = 'd1e2f3a4b5c6'
branch_labels = None
depends_on = None


def upgrade():
    # Переименовать колонку amplitude → pace_threshold
    op.alter_column('users', 'interval_oscillation_amplitude',
                     new_column_name='interval_pace_threshold')
    # Обновить данные: старое default 0.3 → новое default 1.0
    op.execute("UPDATE users SET interval_pace_threshold = 1.0 WHERE interval_pace_threshold = 0.3")
    # Обновить min_phase_duration default: 10 → 15
    op.execute("UPDATE users SET interval_min_phase_duration = 15 WHERE interval_min_phase_duration = 10")


def downgrade():
    op.execute("UPDATE users SET interval_oscillation_amplitude = 0.3 WHERE interval_oscillation_amplitude = 1.0")
    op.execute("UPDATE users SET interval_min_phase_duration = 10 WHERE interval_min_phase_duration = 15")
    op.alter_column('users', 'interval_pace_threshold',
                     new_column_name='interval_oscillation_amplitude')
