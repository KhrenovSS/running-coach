"""baseline

Revision ID: c3f51ae84837
Revises: 
Create Date: 2026-06-30 09:13:15.514268

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'c3f51ae84837'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Индексы для user_id (ускорение запросов по пользователю)
    with op.batch_alter_table('daily_metrics', schema=None) as batch_op:
        batch_op.create_unique_constraint('uq_user_date', ['user_id', 'date'])
    with op.batch_alter_table('deleted_trainings', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_deleted_trainings_user_id'), ['user_id'], unique=False)
    with op.batch_alter_table('training_sessions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_training_sessions_user_id'), ['user_id'], unique=False)
    with op.batch_alter_table('weight_measurements', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_weight_measurements_user_id'), ['user_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('weight_measurements', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_weight_measurements_user_id'))
    with op.batch_alter_table('training_sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_training_sessions_user_id'))
    with op.batch_alter_table('deleted_trainings', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_deleted_trainings_user_id'))
    with op.batch_alter_table('daily_metrics', schema=None) as batch_op:
        batch_op.drop_constraint('uq_user_date', type_='unique')
