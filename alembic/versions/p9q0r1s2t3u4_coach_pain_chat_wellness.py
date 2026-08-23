"""Гибридный коуч C3: боль, wellness-отчёты, история чата, наблюдаемость решений

DEV_PLAN §6. Все операции АДДИТИВНЫЕ (nullable-колонки + новые таблицы) —
существующие данные не затрагиваются:
- training_feedback += pain_level/pain_location/pain_phase (боль по тренировке;
  pain_phase ∈ start/middle/end/after/none — «дискомфорт первые 400–800 м»);
- wellness_reports — вечерний самоотчёт, в т.ч. в дни без тренировки;
- coach_messages — история диалога с коучем + учёт токенов/стоимости LLM;
- recommendations += proposal_json/safety_json/clamped/source — предложение LLM
  ДО урезания safety-границей (метрика дрейфа).

⚠️ ВНИМАНИЕ: downgrade() НЕОБРАТИМО удаляет накопленные данные о боли,
wellness-отчёты и историю чата. Перед откатом — bin/backup_db.sh.
(Downgrade irreversibly drops pain data, wellness reports and chat history.)

Деплой: миграция содержит ALTER → сначала `docker compose stop bot`
(docs/CHECKLIST_MIGRATION.md, инцидент 05.08.2026).

Revision ID: p9q0r1s2t3u4
Revises: o8p9q0r1s2t3
Create Date: 2026-08-23
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = 'p9q0r1s2t3u4'
down_revision: Union[str, None] = 'o8p9q0r1s2t3'
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade():
    # 1. Боль по конкретной тренировке (per-session pain)
    op.add_column('training_feedback', sa.Column('pain_level', sa.Integer(), nullable=True))
    op.add_column('training_feedback', sa.Column('pain_location', sa.String(30), nullable=True))
    op.add_column('training_feedback', sa.Column('pain_phase', sa.String(20), nullable=True))

    # 2. Вечерний самоотчёт (evening self-report — pain comes on rest days too)
    op.create_table(
        'wellness_reports',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('report_date', sa.Date(), nullable=False),
        sa.Column('pain_level', sa.Integer(), nullable=True),
        sa.Column('pain_location', sa.String(30), nullable=True),
        sa.Column('soreness', sa.Integer(), nullable=True),
        sa.Column('mood', sa.Integer(), nullable=True),
        sa.Column('sleep_quality_self', sa.Integer(), nullable=True),
        sa.Column('note', sa.String(300), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('user_id', 'report_date', name='uq_wellness_user_date'),
    )
    op.create_index('ix_wellness_reports_user_id', 'wellness_reports', ['user_id'])

    # 3. История диалога с коучем (chat history + LLM cost accounting)
    op.create_table(
        'coach_messages',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('role', sa.String(10), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False, server_default='chat'),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('meta_json', sa.JSON(), nullable=True),
        sa.Column('tokens_in', sa.Integer(), nullable=True),
        sa.Column('tokens_out', sa.Integer(), nullable=True),
        sa.Column('cost_usd', sa.Float(), nullable=True),
    )
    op.create_index('ix_coach_messages_user_id', 'coach_messages', ['user_id'])
    op.create_index('ix_coach_messages_user_created', 'coach_messages',
                    ['user_id', 'created_at'])

    # 4. Наблюдаемость решений (decision observability — proposal BEFORE clamp)
    op.add_column('recommendations', sa.Column('proposal_json', sa.JSON(), nullable=True))
    op.add_column('recommendations', sa.Column('safety_json', sa.JSON(), nullable=True))
    op.add_column('recommendations', sa.Column('clamped', sa.Boolean(), nullable=True))
    op.add_column('recommendations', sa.Column('source', sa.String(20), nullable=True))


def downgrade():
    # ⚠️ Необратимая потеря данных о боли/wellness/чате (irreversible data loss)
    op.drop_column('recommendations', 'source')
    op.drop_column('recommendations', 'clamped')
    op.drop_column('recommendations', 'safety_json')
    op.drop_column('recommendations', 'proposal_json')
    op.drop_index('ix_coach_messages_user_created', table_name='coach_messages')
    op.drop_index('ix_coach_messages_user_id', table_name='coach_messages')
    op.drop_table('coach_messages')
    op.drop_index('ix_wellness_reports_user_id', table_name='wellness_reports')
    op.drop_table('wellness_reports')
    op.drop_column('training_feedback', 'pain_phase')
    op.drop_column('training_feedback', 'pain_location')
    op.drop_column('training_feedback', 'pain_level')
