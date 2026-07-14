"""data integrity: NOT NULL FKs, ON DELETE CASCADE, Text to JSON

Revision ID: f7g8h9i0j1k2
Revises: e5f6a7b8c9d0
Create Date: 2026-07-14

DI-01: nullable FK → NOT NULL + ON DELETE CASCADE (user_id)
DI-02: daily_metrics.sleep_hrv_interval_list Text → JSON
DI-03: audit_events.metadata_json Text → JSON
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'f7g8h9i0j1k2'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _delete_orphan_rows(table: str, column: str = 'user_id'):
    """Delete rows where FK column is NULL or references non-existent parent."""
    conn = op.get_bind()
    conn.execute(
        sa.text(
            f"DELETE FROM {table} "
            f"WHERE {column} IS NULL "
            f"OR NOT EXISTS (SELECT 1 FROM users WHERE users.id = {table}.{column})"
        )
    )


def upgrade() -> None:
    # === Step 1: Delete orphan rows ===
    _delete_orphan_rows('training_sessions')
    _delete_orphan_rows('deleted_trainings')
    _delete_orphan_rows('training_feedback')
    _delete_orphan_rows('daily_metrics')
    _delete_orphan_rows('weight_measurements')
    _delete_orphan_rows('audit_events')

    # === Step 2: NOT NULL + ON DELETE CASCADE on user_id FKs ===
    # TrainingSession
    with op.batch_alter_table('training_sessions', schema=None) as batch_op:
        batch_op.alter_column('user_id', nullable=False)
        batch_op.drop_constraint('training_sessions_user_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key('training_sessions_user_id_fkey', 'users', ['user_id'], ['id'], ondelete='CASCADE')

    # DeletedTraining
    with op.batch_alter_table('deleted_trainings', schema=None) as batch_op:
        batch_op.alter_column('user_id', nullable=False)
        batch_op.drop_constraint('deleted_trainings_user_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key('deleted_trainings_user_id_fkey', 'users', ['user_id'], ['id'], ondelete='CASCADE')

    # TrainingFeedback
    with op.batch_alter_table('training_feedback', schema=None) as batch_op:
        batch_op.alter_column('user_id', nullable=False)
        batch_op.drop_constraint('training_feedback_user_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key('training_feedback_user_id_fkey', 'users', ['user_id'], ['id'], ondelete='CASCADE')

    # DailyMetrics
    with op.batch_alter_table('daily_metrics', schema=None) as batch_op:
        batch_op.alter_column('user_id', nullable=False)
        batch_op.drop_constraint('daily_metrics_user_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key('daily_metrics_user_id_fkey', 'users', ['user_id'], ['id'], ondelete='CASCADE')

    # WeightMeasurement
    with op.batch_alter_table('weight_measurements', schema=None) as batch_op:
        batch_op.alter_column('user_id', nullable=False)
        batch_op.drop_constraint('weight_measurements_user_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key('weight_measurements_user_id_fkey', 'users', ['user_id'], ['id'], ondelete='CASCADE')

    # AuditEvent
    with op.batch_alter_table('audit_events', schema=None) as batch_op:
        batch_op.alter_column('user_id', nullable=False)
        batch_op.drop_constraint('audit_events_user_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key('audit_events_user_id_fkey', 'users', ['user_id'], ['id'], ondelete='CASCADE')

    # === Step 3: Text → JSON ===
    op.alter_column('daily_metrics', 'sleep_hrv_interval_list',
                    existing_type=sa.Text(),
                    type_=sa.JSON(),
                    postgresql_using='sleep_hrv_interval_list::json')

    op.alter_column('audit_events', 'metadata_json',
                    existing_type=sa.Text(),
                    type_=sa.JSON(),
                    postgresql_using='metadata_json::json')


def downgrade() -> None:
    # JSON → Text (reverse)
    op.alter_column('audit_events', 'metadata_json',
                    existing_type=sa.JSON(), type_=sa.Text())
    op.alter_column('daily_metrics', 'sleep_hrv_interval_list',
                    existing_type=sa.JSON(), type_=sa.Text())

    # Restore nullable FKs without CASCADE
    with op.batch_alter_table('audit_events', schema=None) as batch_op:
        batch_op.drop_constraint('audit_events_user_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key('audit_events_user_id_fkey', 'users', ['user_id'], ['id'])
        batch_op.alter_column('user_id', nullable=True)

    with op.batch_alter_table('weight_measurements', schema=None) as batch_op:
        batch_op.drop_constraint('weight_measurements_user_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key('weight_measurements_user_id_fkey', 'users', ['user_id'], ['id'])
        batch_op.alter_column('user_id', nullable=True)

    with op.batch_alter_table('daily_metrics', schema=None) as batch_op:
        batch_op.drop_constraint('daily_metrics_user_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key('daily_metrics_user_id_fkey', 'users', ['user_id'], ['id'])
        batch_op.alter_column('user_id', nullable=True)

    with op.batch_alter_table('training_feedback', schema=None) as batch_op:
        batch_op.drop_constraint('training_feedback_user_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key('training_feedback_user_id_fkey', 'users', ['user_id'], ['id'])
        batch_op.alter_column('user_id', nullable=True)

    with op.batch_alter_table('deleted_trainings', schema=None) as batch_op:
        batch_op.drop_constraint('deleted_trainings_user_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key('deleted_trainings_user_id_fkey', 'users', ['user_id'], ['id'])
        batch_op.alter_column('user_id', nullable=True)

    with op.batch_alter_table('training_sessions', schema=None) as batch_op:
        batch_op.drop_constraint('training_sessions_user_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key('training_sessions_user_id_fkey', 'users', ['user_id'], ['id'])
        batch_op.alter_column('user_id', nullable=True)
