"""analytics preparation: indexes + avg_pace

Revision ID: g9h0i1j2k3l4
Revises: f7g8h9i0j1k2
Create Date: 2026-07-16

PREP-02: Add indexes for time-range queries
PREP-08: Add avg_pace column to training_sessions
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'g9h0i1j2k3l4'
down_revision: Union[str, None] = 'f7g8h9i0j1k2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === PREP-08: avg_pace column ===
    op.add_column('training_sessions', sa.Column('avg_pace', sa.Float(), nullable=True))

    # === PREP-02: Indexes for time-range queries ===
    op.create_index('ix_training_user_begin', 'training_sessions', ['user_id', 'begin_ts'])
    op.create_index('ix_training_begin', 'training_sessions', ['begin_ts'])
    op.create_index('ix_daily_metrics_date', 'daily_metrics', ['date'])
    op.create_index('ix_feedback_user_created', 'training_feedback', ['user_id', 'created_at'])
    op.create_index('ix_weight_user_measured', 'weight_measurements', ['user_id', 'measured_at'])


def downgrade() -> None:
    # === PREP-02: Drop indexes ===
    op.drop_index('ix_weight_user_measured', table_name='weight_measurements')
    op.drop_index('ix_feedback_user_created', table_name='training_feedback')
    op.drop_index('ix_daily_metrics_date', table_name='daily_metrics')
    op.drop_index('ix_training_begin', table_name='training_sessions')
    op.drop_index('ix_training_user_begin', table_name='training_sessions')

    # === PREP-08: Drop avg_pace column ===
    op.drop_column('training_sessions', 'avg_pace')
