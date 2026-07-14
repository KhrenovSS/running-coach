# Модель тренировочной сессии + обратная связь + удалённые (Training session, feedback, deleted)

from sqlalchemy import Column, Integer, Float, String, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship

from src.domain.models.base import Base, utcnow


class TrainingSession(Base):
    __tablename__ = 'training_sessions'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)  # Для обратной совместимости nullable
    begin_ts = Column(DateTime(timezone=True), default=utcnow)
    total_distance_km = Column(Float)
    avg_heart_rate = Column(Integer)
    max_heart_rate = Column(Integer)
    training_type = Column(String(50))
    training_type_override = Column(String(50), nullable=True)  # Ручная установка типа (NULL = авто)
    trackpoints_json = Column(JSON, nullable=True)              # Сырые трекпоинты для пересчёта
    segments_count = Column(Integer, default=1)
    duration_minutes = Column(Float, default=0)
    segments_json = Column(JSON, default=list)
    hr_pace_series = Column(JSON, default=list)
    avg_temperature = Column(Integer, nullable=True)
    weather_code = Column(Integer, nullable=True)
    elevation_gain = Column(Integer, nullable=True)
    elevation_loss = Column(Integer, nullable=True)
    suspect_flags = Column(JSON, default=list)
    cleaning_log = Column(JSON, default=list)
    avg_cadence = Column(Integer, nullable=True)
    timezone = Column(String(50), nullable=True)  # Часовой пояс тренировки (Training timezone, e.g. "Europe/Moscow")
    training_effect = Column(Float, nullable=True)
    anaerobic_training_effect = Column(Float, nullable=True)
    vo2max = Column(Float, nullable=True)
    calories = Column(Integer, nullable=True)

    user = relationship("User", back_populates="training_sessions")


class DeletedTraining(Base):
    __tablename__ = 'deleted_trainings'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)
    begin_ts = Column(DateTime(timezone=True), nullable=False)
    total_distance_km = Column(Float, nullable=True)
    avg_heart_rate = Column(Integer, nullable=True)
    max_heart_rate = Column(Integer, nullable=True)
    training_type = Column(String(50), nullable=True)
    duration_minutes = Column(Float, nullable=True)
    avg_temperature = Column(Integer, nullable=True)
    elevation_gain = Column(Integer, nullable=True)
    avg_cadence = Column(Integer, nullable=True)
    training_effect = Column(Float, nullable=True)
    vo2max = Column(Float, nullable=True)
    calories = Column(Integer, nullable=True)
    avg_pace = Column(Float, nullable=True)
    deleted_at = Column(DateTime(timezone=True), default=utcnow)

    user = relationship("User", back_populates="deleted_trainings")


class TrainingFeedback(Base):
    __tablename__ = 'training_feedback'
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey('training_sessions.id'), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)
    rating = Column(Integer, nullable=False)  # 0–10 (тяжесть тренировки)
    notes = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    session = relationship("TrainingSession")
    user = relationship("User")
