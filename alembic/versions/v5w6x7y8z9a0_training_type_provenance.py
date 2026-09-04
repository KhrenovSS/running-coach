"""Провенанс ярлыка тренировки (plan-aware training type, 04.09.2026)

training_type_auto — сырой ответ классификатора (размеченная выборка для #222, откат резолвера);
training_type_source — auto | plan | manual (кто дал итоговый training_type). Backfill: у существующих
строк auto = текущий ярлык, source = manual при override, иначе auto. Чисто аддитивно, обратимо.

Деплой (§7): backup → stop bot → alembic upgrade (старт app) → up bot.

Revision ID: v5w6x7y8z9a0
Revises: u4v5w6x7y8z9
Create Date: 2026-09-04
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = 'v5w6x7y8z9a0'
down_revision: Union[str, None] = 'u4v5w6x7y8z9'
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade():
    op.add_column('training_sessions', sa.Column('training_type_auto', sa.String(50), nullable=True))
    op.add_column('training_sessions', sa.Column('training_type_source', sa.String(20), nullable=True))
    op.execute(
        "UPDATE training_sessions SET training_type_auto = training_type, "
        "training_type_source = CASE WHEN training_type_override IS NOT NULL "
        "AND training_type_override <> '' THEN 'manual' ELSE 'auto' END "
        "WHERE training_type_auto IS NULL"
    )


def downgrade():
    # Вернуть сырой ярлык в training_type до удаления колонки — иначе старый код увидит
    # переразмеченные типы как результат классификатора (db-safety ревью 04.09.2026)
    op.execute(
        "UPDATE training_sessions SET training_type = training_type_auto "
        "WHERE training_type_auto IS NOT NULL "
        "AND (training_type_override IS NULL OR training_type_override = '')"
    )
    op.drop_column('training_sessions', 'training_type_source')
    op.drop_column('training_sessions', 'training_type_auto')
