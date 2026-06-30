"""add auth_tokens table

Revision ID: 69f28e182276
Revises: eb50c256201f
Create Date: 2026-06-30 23:00:00.941328

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '69f28e182276'
down_revision: Union[str, Sequence[str], None] = 'eb50c256201f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Идемпотентное создание таблицы auth_tokens (Idempotent auth_tokens table creation)
    op.execute("""
        CREATE TABLE IF NOT EXISTS auth_tokens (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            token VARCHAR(64) NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            used_at DATETIME,
            expires_at DATETIME NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users (id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_auth_tokens_token ON auth_tokens (token)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_auth_tokens_user_id ON auth_tokens (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_auth_tokens_expires_at ON auth_tokens (expires_at)")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_auth_tokens_expires_at")
    op.execute("DROP INDEX IF EXISTS ix_auth_tokens_user_id")
    op.execute("DROP INDEX IF EXISTS ix_auth_tokens_token")
    op.execute("DROP TABLE IF EXISTS auth_tokens")
