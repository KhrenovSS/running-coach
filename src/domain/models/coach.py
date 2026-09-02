# Модели модуля аналитики/коучинга (Coach module models — Этап 0)
# По decision_module_design.md §11. Все таблицы per-user (FK user_id, CASCADE).

from sqlalchemy import (
    Column, Integer, Float, String, Text, DateTime, Date, JSON, Boolean,
    ForeignKey, UniqueConstraint, Index,
)

from src.domain.models.base import Base, utcnow


class Recommendation(Base):
    """Что система рекомендовала (What the system recommended)."""
    __tablename__ = 'recommendations'
    __table_args__ = (
        Index('ix_recommendations_user_for_date', 'user_id', 'for_date'),
    )
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    for_date = Column(Date, nullable=True)                  # на какую дату (target date)
    workout_type = Column(String(30), nullable=True)        # interval/tempo/long/recovery/easy/rest
    target_json = Column(JSON, nullable=True)               # целевой темп/пульс/зоны
    volume_json = Column(JSON, nullable=True)               # объём (км/время/повторы)
    rationale_json = Column(JSON, nullable=True)            # трасса рассуждений (ReasoningTrace)
    predicted_json = Column(JSON, nullable=True)            # прогноз effort/HR/load
    confidence = Column(Float, nullable=True)
    status = Column(String(20), default='proposed')         # proposed/planned/confirmed/adjusted/superseded
    linked_session_id = Column(Integer, ForeignKey('training_sessions.id', ondelete='SET NULL'), nullable=True)
    # C3 (DEV_PLAN §6): наблюдаемость гибрида — предложение LLM ДО урезания + вердикт.
    # (Hybrid observability: the raw proposal BEFORE clamp + the safety verdict.)
    proposal_json = Column(JSON, nullable=True)             # WorkoutProposal до clamp
    safety_json = Column(JSON, nullable=True)               # SafetyVerdict на момент решения
    clamped = Column(Boolean, nullable=True)                # safety урезал предложение
    source = Column(String(20), nullable=True)              # llm | fallback


class PredictionLog(Base):
    """Прогноз против факта — для обучения (Prediction vs actual, for learning)."""
    __tablename__ = 'prediction_logs'
    __table_args__ = (
        UniqueConstraint('session_id', name='uq_prediction_session'),  # идемпотентность калибровки
    )
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    session_id = Column(Integer, ForeignKey('training_sessions.id', ondelete='CASCADE'), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    predicted_json = Column(JSON, nullable=True)
    actual_json = Column(JSON, nullable=True)
    residual_effort = Column(Float, nullable=True)
    residual_hr = Column(Float, nullable=True)
    residual_load = Column(Float, nullable=True)
    flagged_hard = Column(Boolean, default=False)           # «неожиданно тяжело»


class UserModel(Base):
    """Персональные откалиброванные параметры — 1 строка на пользователя (per-user calibrated params)."""
    __tablename__ = 'user_models'
    __table_args__ = (
        UniqueConstraint('user_id', name='uq_user_model_user'),
    )
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    params_json = Column(JSON, nullable=True)               # baselines/efficiency/tolerance/preferences/injuries
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Lesson(Base):
    """Извлечённый «урок» — корректирует поведение движка (Extracted lesson, consumed by rule P5)."""
    __tablename__ = 'lessons'
    __table_args__ = (
        Index('ix_lessons_user_active', 'user_id', 'active'),
    )
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    trigger_json = Column(JSON, nullable=True)              # условия срабатывания
    cause = Column(String(20), nullable=True)              # confirmed/hypothesized
    adjustment_json = Column(JSON, nullable=True)          # как корректировать поведение
    source = Column(String(20), nullable=True)            # user/auto
    active = Column(Boolean, default=True)


class WorkoutInsight(Base):
    """Итог разбора тренировки + очередь отложенного разбора (review v2, DEV_PLAN D1).

    Строка создаётся синком (любой контейнер), исполняется разбор только ботом
    через атомарный claim по status — ADR «Решение 4» в docs/coach/ARCHITECTURE.md.
    (Persistent review outcome AND the deferred-review queue in one row.)
    """
    __tablename__ = 'workout_insights'
    __table_args__ = (
        UniqueConstraint('session_id', name='uq_workout_insight_session'),
        Index('ix_workout_insights_user_created', 'user_id', 'created_at'),
        Index('ix_workout_insights_status', 'status'),  # выборка pending джобой
    )
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    session_id = Column(Integer, ForeignKey('training_sessions.id', ondelete='CASCADE'), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    status = Column(String(16), nullable=False, default='pending', server_default='pending')
        # pending | running | done | none | expired | error
    source = Column(String(16), nullable=True)              # llm | fallback (NULL пока не done)
    attempts = Column(Integer, nullable=False, default=0, server_default='0')
    claimed_at = Column(DateTime(timezone=True), nullable=True)   # re-claim зависших running
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    schema_version = Column(Integer, nullable=True)         # версия computed_json (D2)
    computed_json = Column(JSON, nullable=True)             # детерминированные метрики (drift/GAP/baseline/heat)
    assessment_json = Column(JSON, nullable=True)           # провалидированный ReviewAssessment (D3)
    effort_match = Column(String(10), nullable=True)        # ok|harder|easier|unknown — дубль для агрегаций
    carry_forward = Column(String(300), nullable=True)      # заметка «на завтра» — читает утренний вердикт
    coach_message_id = Column(Integer, ForeignKey('coach_messages.id', ondelete='SET NULL'), nullable=True)


class CoachMessage(Base):
    """История диалога с коучем + учёт стоимости LLM (chat history + cost accounting)."""
    __tablename__ = 'coach_messages'
    __table_args__ = (
        Index('ix_coach_messages_user_created', 'user_id', 'created_at'),
    )
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    role = Column(String(10), nullable=False)               # user/assistant/system
    kind = Column(String(20), nullable=False, default='chat', server_default='chat')  # chat/morning/evening/review/plan/weekly
    text = Column(Text, nullable=False)
    meta_json = Column(JSON, nullable=True)                 # usage/cache/tool_calls/stop_reason
    tokens_in = Column(Integer, nullable=True)
    tokens_out = Column(Integer, nullable=True)
    cost_usd = Column(Float, nullable=True)
