"""add watch_credentials table and source_brand to daily_metrics

Revision ID: b6c7d8e9f0a1
Revises: 5e287a9fc289
Create Date: 2026-07-02 20:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b6c7d8e9f0a1'
down_revision: Union[str, None] = '5e287a9fc289'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Создаём таблицу watch_credentials (Create watch_credentials table)
    op.create_table(
        'watch_credentials',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('brand', sa.String(length=50), nullable=False),
        sa.Column('encrypted_user', sa.String(length=255), nullable=True),
        sa.Column('encrypted_password', sa.String(length=255), nullable=True),
        sa.Column('access_token', sa.String(length=512), nullable=True),
        sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_activity_sync_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_health_sync_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('activity_sync_interval', sa.Integer(), nullable=True),
        sa.Column('health_sync_interval', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
    )

    # Добавляем колонку source_brand в daily_metrics (Add source_brand to daily_metrics)
    op.add_column('daily_metrics',
        sa.Column('source_brand', sa.String(length=50), nullable=True)
    )

    # Переносим существующие coros учётные данные в watch_credentials (Migrate existing coros credentials)
    conn = op.get_bind()
    users = conn.execute(
        sa.text("SELECT id, coros_email, coros_password, last_coros_sync, last_health_sync_at FROM users WHERE coros_email IS NOT NULL")
    ).fetchall()

    for user in users:
        conn.execute(
            sa.text(
                "INSERT INTO watch_credentials "
                "(user_id, brand, encrypted_user, encrypted_password, last_activity_sync_at, last_health_sync_at, is_active) "
                "VALUES (:uid, 'coros', :email, :pwd, :last_sync, :last_health, true)"
            ),
            {
                "uid": user[0],
                "email": user[1],
                "pwd": user[2],
                "last_sync": user[3],
                "last_health": user[4],
            }
        )


def downgrade() -> None:
    op.drop_table('watch_credentials')
    op.drop_column('daily_metrics', 'source_brand')