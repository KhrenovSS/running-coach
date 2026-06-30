"""drop_user_settings_table

Revision ID: 0bba2c2badec
Revises: c3f51ae84837
Create Date: 2026-06-30 09:18:17.239146

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0bba2c2badec'
down_revision: Union[str, Sequence[str], None] = 'c3f51ae84837'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table('user_settings')


def downgrade() -> None:
    op.create_table('user_settings',
    sa.Column('id', sa.INTEGER(), nullable=False),
    sa.Column('max_hr', sa.INTEGER(), nullable=True),
    sa.Column('weight', sa.FLOAT(), nullable=True),
    sa.Column('max_credible_pace', sa.FLOAT(), nullable=True),
    sa.Column('max_gps_jump_m', sa.FLOAT(), nullable=True),
    sa.Column('min_hr_for_fast_pace', sa.INTEGER(), nullable=True),
    sa.Column('coros_email', sa.VARCHAR(length=255), nullable=True),
    sa.Column('coros_password', sa.VARCHAR(length=255), nullable=True),
    sa.Column('last_coros_sync', sa.DATETIME(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
