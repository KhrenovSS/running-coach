# Модели модуля аналитики/коучинга (Coach module models — Этап 0)
# По decision_module_design.md §11. Все таблицы per-user (FK user_id, CASCADE).

from sqlalchemy import (
    Column, Integer, Float, String, DateTime, Date, JSON, Boolean,
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
    status = Column(String(20), default='proposed')         # proposed/accepted/done/skipped
    linked_session_id = Column(Integer, ForeignKey('training_sessions.id', ondelete='SET NULL'), nullable=True)


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
