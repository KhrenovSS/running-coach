"""Адаптивный max_hr: сглаженный пик пульса тренировки

training_sessions.hr_peak_smoothed — пик пульса по скользящей медиане (окно 5):
одиночные выбросы датчика отбрасываются, устойчивый высокий пульс сохраняется.
Используется сервисом hr_max для авто-повышения / предложения снижения User.max_hr.
Аддитивная nullable-колонка, потери данных нет; для legacy-строк NULL —
потребители делают coalesce(hr_peak_smoothed, max_heart_rate).
(Additive nullable column: rolling-median HR peak for the adaptive max HR service;
legacy rows stay NULL, consumers coalesce to max_heart_rate.)

Revision ID: o8p9q0r1s2t3
Revises: n7o8p9q0r1s2
Create Date: 2026-08-06
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = 'o8p9q0r1s2t3'
down_revision: Union[str, None] = 'n7o8p9q0r1s2'
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade():
    op.add_column('training_sessions', sa.Column('hr_peak_smoothed', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('training_sessions', 'hr_peak_smoothed')
