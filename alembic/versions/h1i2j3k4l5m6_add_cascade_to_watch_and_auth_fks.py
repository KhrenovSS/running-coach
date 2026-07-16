"""add ON DELETE CASCADE to watch_credentials and auth_tokens

revision ID: h1i2j3k4l5m6
revises: g9h0i1j2k3l4
create date: 2026-07-16
"""

from typing import Union

from alembic import op

revision: str = 'h1i2j3k4l5m6'
down_revision: Union[str, None] = 'g9h0i1j2k3l4'
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade():
    op.drop_constraint(
        'watch_credentials_user_id_fkey',
        'watch_credentials',
        type_='foreignkey',
    )
    op.create_foreign_key(
        'watch_credentials_user_id_fkey',
        'watch_credentials',
        'users',
        ['user_id'],
        ['id'],
        ondelete='CASCADE',
    )
    op.drop_constraint(
        'auth_tokens_user_id_fkey',
        'auth_tokens',
        type_='foreignkey',
    )
    op.create_foreign_key(
        'auth_tokens_user_id_fkey',
        'auth_tokens',
        'users',
        ['user_id'],
        ['id'],
        ondelete='CASCADE',
    )


def downgrade():
    op.drop_constraint(
        'auth_tokens_user_id_fkey',
        'auth_tokens',
        type_='foreignkey',
    )
    op.create_foreign_key(
        'auth_tokens_user_id_fkey',
        'auth_tokens',
        'users',
        ['user_id'],
        ['id'],
    )
    op.drop_constraint(
        'watch_credentials_user_id_fkey',
        'watch_credentials',
        type_='foreignkey',
    )
    op.create_foreign_key(
        'watch_credentials_user_id_fkey',
        'watch_credentials',
        'users',
        ['user_id'],
        ['id'],
    )
