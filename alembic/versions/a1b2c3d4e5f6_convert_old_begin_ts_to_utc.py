"""Convert old naive-local begin_ts to naive UTC and set timezone

Revision ID: a1b2c3d4e5f6
Revises: 4201426df9cc
Create Date: 2026-07-02 10:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from datetime import timezone
from zoneinfo import ZoneInfo


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '4201426df9cc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FALLBACK_TZ = "Europe/Moscow"


def upgrade() -> None:
    connection = op.get_bind()

    # Convert old naive-local begin_ts to naive UTC for sessions without timezone
    # Old sessions stored begin_ts as local time (e.g. 10:00 MSK).
    # New code stores begin_ts as naive UTC (e.g. 07:00 UTC for 10:00 MSK).
    # Since GPS data is not stored in the DB, we fall back to Europe/Moscow.
    sessions = connection.execute(
        sa.text(
            "SELECT id, begin_ts FROM training_sessions "
            "WHERE timezone IS NULL AND begin_ts IS NOT NULL"
        )
    ).fetchall()

    for sid, begin_ts in sessions:
        if begin_ts is None:
            continue
        local_aware = begin_ts.replace(tzinfo=ZoneInfo(FALLBACK_TZ))
        utc_naive = local_aware.astimezone(timezone.utc).replace(tzinfo=None)
        connection.execute(
            sa.text(
                "UPDATE training_sessions SET begin_ts = :utc_ts, timezone = :tz WHERE id = :sid"
            ),
            {"utc_ts": utc_naive, "tz": FALLBACK_TZ, "sid": sid},
        )

    # Set User.timezone from most recent training session (if not already set)
    connection.execute(
        sa.text(
            "UPDATE users SET timezone = :tz "
            "WHERE timezone IS NULL AND EXISTS ("
            "  SELECT 1 FROM training_sessions "
            "  WHERE training_sessions.user_id = users.id"
            ")"
        ),
        {"tz": FALLBACK_TZ},
    )


def downgrade() -> None:
    # Reverse is not possible without storing original local times
    pass
