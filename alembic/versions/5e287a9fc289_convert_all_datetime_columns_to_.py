"""convert all DateTime columns to TIMESTAMPTZ

Revision ID: 5e287a9fc289
Revises: a1b2c3d4e5f6
Create Date: 2026-07-02 11:27:42.573257

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5e287a9fc289'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Convert TIMESTAMP columns to TIMESTAMP WITH TIME ZONE.
# Existing naive values are treated as UTC (the previous code stored them as naive UTC).
def _to_tz(table: str, column: str) -> None:
    op.execute(
        f"ALTER TABLE {table} ALTER COLUMN {column} "
        f"TYPE TIMESTAMP WITH TIME ZONE USING {column} AT TIME ZONE 'UTC'"
    )


def _to_naive(table: str, column: str) -> None:
    op.execute(
        f"ALTER TABLE {table} ALTER COLUMN {column} "
        f"TYPE TIMESTAMP WITHOUT TIME ZONE USING {column} AT TIME ZONE 'UTC'"
    )


def upgrade() -> None:
    """Upgrade schema: all DateTime columns → TIMESTAMPTZ."""
    # users
    _to_tz("users", "created_at")
    _to_tz("users", "registered_at")
    _to_tz("users", "last_coros_sync")
    _to_tz("users", "last_health_sync_at")
    # training_sessions
    _to_tz("training_sessions", "begin_ts")
    # deleted_trainings
    _to_tz("deleted_trainings", "begin_ts")
    _to_tz("deleted_trainings", "deleted_at")
    # daily_metrics
    _to_tz("daily_metrics", "synced_at")
    # weight_measurements
    _to_tz("weight_measurements", "measured_at")
    # training_feedback
    _to_tz("training_feedback", "created_at")
    # audit_events
    _to_tz("audit_events", "created_at")
    # auth_tokens
    _to_tz("auth_tokens", "expires_at")
    _to_tz("auth_tokens", "used_at")
    _to_tz("auth_tokens", "created_at")


def downgrade() -> None:
    """Downgrade schema: all TIMESTAMPTZ columns → TIMESTAMP."""
    # users
    _to_naive("users", "created_at")
    _to_naive("users", "registered_at")
    _to_naive("users", "last_coros_sync")
    _to_naive("users", "last_health_sync_at")
    # training_sessions
    _to_naive("training_sessions", "begin_ts")
    # deleted_trainings
    _to_naive("deleted_trainings", "begin_ts")
    _to_naive("deleted_trainings", "deleted_at")
    # daily_metrics
    _to_naive("daily_metrics", "synced_at")
    # weight_measurements
    _to_naive("weight_measurements", "measured_at")
    # training_feedback
    _to_naive("training_feedback", "created_at")
    # audit_events
    _to_naive("audit_events", "created_at")
    # auth_tokens
    _to_naive("auth_tokens", "expires_at")
    _to_naive("auth_tokens", "used_at")
    _to_naive("auth_tokens", "created_at")
