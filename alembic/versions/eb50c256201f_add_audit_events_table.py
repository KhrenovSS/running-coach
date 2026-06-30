"""add audit_events table

Revision ID: eb50c256201f
Revises: 0bba2c2badec
Create Date: 2026-06-30 22:35:43.006706

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'eb50c256201f'
down_revision: Union[str, Sequence[str], None] = '0bba2c2badec'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Идемпотентное создание таблицы audit_events (Idempotent audit_events table creation)
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type VARCHAR(100) NOT NULL,
            severity VARCHAR(20) NOT NULL DEFAULT 'info',
            message TEXT NOT NULL,
            user_id INTEGER,
            ip_address VARCHAR(45),
            metadata_json TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    
    # Создаём индексы если их нет (Create indexes if not exist)
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_events_created_at ON audit_events (created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_events_event_type ON audit_events (event_type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_events_user_id ON audit_events (user_id)")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_audit_events_user_id")
    op.execute("DROP INDEX IF EXISTS ix_audit_events_event_type")
    op.execute("DROP INDEX IF EXISTS ix_audit_events_created_at")
    op.execute("DROP TABLE IF EXISTS audit_events")
