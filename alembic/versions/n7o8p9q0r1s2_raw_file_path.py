"""Этап 4 ремедиации: хранение исходных FIT/TCX (BACKLOG #229)

training_sessions.raw_file_path — путь к сырому файлу в uploads/raw/<user_id>/<sha256>.<ext>.
Раньше FIT удалялся после парсинга, а trackpoints_json хранил только 7 полей уже после
GPS-очистки → улучшить очистку или добыть новые метрики (мощность, running dynamics)
было невозможно. Аддитивная колонка, потери данных нет. Backfill старых активностей —
bin/backfill_raw_fits.py (нужен API — не в миграции; история Coros конечна, запускать раньше).

Revision ID: n7o8p9q0r1s2
Revises: m6n7o8p9q0r1
Create Date: 2026-08-05
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = 'n7o8p9q0r1s2'
down_revision: Union[str, None] = 'm6n7o8p9q0r1'
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade():
    op.add_column('training_sessions', sa.Column('raw_file_path', sa.String(255), nullable=True))


def downgrade():
    op.drop_column('training_sessions', 'raw_file_path')
