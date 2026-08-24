"""Разбор v2 (D1): таблица workout_insights — итог разбора + очередь отложенного разбора

DEV_PLAN §9 D-серия. Операция ЧИСТО АДДИТИВНАЯ (одна новая таблица, существующие
таблицы не затрагиваются): строка = персистентный итог разбора тренировки
(computed_json — детерминированные метрики; assessment_json/carry_forward — оценка LLM)
И элемент очереди отложенного разбора (status: pending → running → done/none/expired/error,
атомарный claim — ADR «Решение 4» в docs/coach/ARCHITECTURE.md).

⚠️ ВНИМАНИЕ: downgrade() удаляет накопленные итоги разборов (пользовательские
данные тренировок не затрагиваются). Перед откатом — bin/backup_db.sh.
(Downgrade drops accumulated review insights; raw training data is untouched.)

Деплой: только CREATE TABLE (без ALTER существующих), но по дисциплине §7 CLAUDE.md —
`docker compose stop bot` → `up -d app` → `up -d bot`.

Revision ID: q0r1s2t3u4v5
Revises: p9q0r1s2t3u4
Create Date: 2026-08-24
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = 'q0r1s2t3u4v5'
down_revision: Union[str, None] = 'p9q0r1s2t3u4'
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade():
    op.create_table(
        'workout_insights',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('session_id', sa.Integer(),
                  sa.ForeignKey('training_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(16), nullable=False, server_default='pending'),
        sa.Column('source', sa.String(16), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('schema_version', sa.Integer(), nullable=True),
        sa.Column('computed_json', sa.JSON(), nullable=True),
        sa.Column('assessment_json', sa.JSON(), nullable=True),
        sa.Column('effort_match', sa.String(10), nullable=True),
        sa.Column('carry_forward', sa.String(300), nullable=True),
        sa.Column('coach_message_id', sa.Integer(),
                  sa.ForeignKey('coach_messages.id', ondelete='SET NULL'), nullable=True),
        sa.UniqueConstraint('session_id', name='uq_workout_insight_session'),
    )
    op.create_index('ix_workout_insights_user_id', 'workout_insights', ['user_id'])
    op.create_index('ix_workout_insights_user_created', 'workout_insights',
                    ['user_id', 'created_at'])
    op.create_index('ix_workout_insights_status', 'workout_insights', ['status'])


def downgrade():
    # ⚠️ Удаляет накопленные итоги разборов (drops accumulated review insights)
    op.drop_index('ix_workout_insights_status', table_name='workout_insights')
    op.drop_index('ix_workout_insights_user_created', table_name='workout_insights')
    op.drop_index('ix_workout_insights_user_id', table_name='workout_insights')
    op.drop_table('workout_insights')
