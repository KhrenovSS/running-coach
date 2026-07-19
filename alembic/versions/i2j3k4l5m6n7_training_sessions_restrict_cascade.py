"""change training_sessions FK from CASCADE to RESTRICT

Revision ID: i2j3k4l5m6n7
Revises: h1i2j3k4l5m6
Create Date: 2026-07-19
"""

from typing import Union

from alembic import op

revision: str = 'i2j3k4l5m6n7'
down_revision: Union[str, None] = 'h1i2j3k4l5m6'
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade():
    op.drop_constraint(
        'training_sessions_user_id_fkey',
        'training_sessions',
        type_='foreignkey',
    )
    op.create_foreign_key(
        'training_sessions_user_id_fkey',
        'training_sessions',
        'users',
        ['user_id'],
        ['id'],
        ondelete='RESTRICT',
    )


def downgrade():
    op.drop_constraint(
        'training_sessions_user_id_fkey',
        'training_sessions',
        type_='foreignkey',
    )
    op.create_foreign_key(
        'training_sessions_user_id_fkey',
        'training_sessions',
        'users',
        ['user_id'],
        ['id'],
        ondelete='CASCADE',
    )
