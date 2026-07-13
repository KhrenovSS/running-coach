"""add interval detection and reanalysis columns

Revision ID: d1e2f3a4b5c6
Revises: c9d8e7f6a0b2
Create Date: 2026-07-13
"""
from alembic import op
import sqlalchemy as sa

revision = 'd1e2f3a4b5c6'
down_revision = 'c9d8e7f6a0b2'
branch_labels = None
depends_on = None


def upgrade():
    # training_sessions: добавить колонки для override и хранения трекпоинтов
    op.add_column('training_sessions', sa.Column('training_type_override', sa.String(50), nullable=True))
    op.add_column('training_sessions', sa.Column('trackpoints_json', sa.JSON(), nullable=True))

    # users: добавить пороги детекции интервалов
    op.add_column('users', sa.Column('interval_oscillation_amplitude', sa.Float(), nullable=True))
    op.add_column('users', sa.Column('interval_min_phase_duration', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('interval_hr_lag_sec', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('interval_min_oscillations', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('users', 'interval_min_oscillations')
    op.drop_column('users', 'interval_hr_lag_sec')
    op.drop_column('users', 'interval_min_phase_duration')
    op.drop_column('users', 'interval_oscillation_amplitude')
    op.drop_column('training_sessions', 'trackpoints_json')
    op.drop_column('training_sessions', 'training_type_override')
