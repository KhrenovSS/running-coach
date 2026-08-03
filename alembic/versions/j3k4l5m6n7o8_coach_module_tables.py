"""coach module tables: recommendations, prediction_logs, user_models, lessons (Этап 0)

Revision ID: j3k4l5m6n7o8
Revises: i2j3k4l5m6n7
Create Date: 2026-08-03
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = 'j3k4l5m6n7o8'
down_revision: Union[str, None] = 'i2j3k4l5m6n7'
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade():
    op.create_table(
        'recommendations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('for_date', sa.Date(), nullable=True),
        sa.Column('workout_type', sa.String(length=30), nullable=True),
        sa.Column('target_json', sa.JSON(), nullable=True),
        sa.Column('volume_json', sa.JSON(), nullable=True),
        sa.Column('rationale_json', sa.JSON(), nullable=True),
        sa.Column('predicted_json', sa.JSON(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('linked_session_id', sa.Integer(), sa.ForeignKey('training_sessions.id', ondelete='SET NULL'), nullable=True),
    )
    op.create_index('ix_recommendations_user_id', 'recommendations', ['user_id'])
    op.create_index('ix_recommendations_user_for_date', 'recommendations', ['user_id', 'for_date'])

    op.create_table(
        'prediction_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('session_id', sa.Integer(), sa.ForeignKey('training_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('predicted_json', sa.JSON(), nullable=True),
        sa.Column('actual_json', sa.JSON(), nullable=True),
        sa.Column('residual_effort', sa.Float(), nullable=True),
        sa.Column('residual_hr', sa.Float(), nullable=True),
        sa.Column('residual_load', sa.Float(), nullable=True),
        sa.Column('flagged_hard', sa.Boolean(), nullable=True),
        sa.UniqueConstraint('session_id', name='uq_prediction_session'),
    )
    op.create_index('ix_prediction_logs_user_id', 'prediction_logs', ['user_id'])

    op.create_table(
        'user_models',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('params_json', sa.JSON(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('user_id', name='uq_user_model_user'),
    )
    op.create_index('ix_user_models_user_id', 'user_models', ['user_id'])

    op.create_table(
        'lessons',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('trigger_json', sa.JSON(), nullable=True),
        sa.Column('cause', sa.String(length=20), nullable=True),
        sa.Column('adjustment_json', sa.JSON(), nullable=True),
        sa.Column('source', sa.String(length=20), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=True),
    )
    op.create_index('ix_lessons_user_id', 'lessons', ['user_id'])
    op.create_index('ix_lessons_user_active', 'lessons', ['user_id', 'active'])


def downgrade():
    op.drop_table('lessons')
    op.drop_table('user_models')
    op.drop_table('prediction_logs')
    op.drop_table('recommendations')
