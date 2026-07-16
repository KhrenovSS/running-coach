# Модель пользователя (User model — multi-user support)

from sqlalchemy import Column, Integer, Float, String, BigInteger, Boolean, DateTime
from sqlalchemy.orm import relationship

from src.domain.models.base import Base, utcnow
from src.config import settings


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)                    # ID пользователя (user ID)
    email = Column(String(255), unique=True, nullable=True)   # email для входа (login email)
    password_hash = Column(String(255), nullable=True)        # bcrypt-хеш пароля (bcrypt password hash)
    telegram_chat_id = Column(BigInteger, unique=True, nullable=True)
    telegram_username = Column(String(255), nullable=True)
    name = Column(String(255), nullable=True)
    age = Column(Integer, nullable=True)
    height_cm = Column(Integer, nullable=True)
    weight_kg = Column(Float, nullable=True)
    sport_level = Column(String(50), nullable=True)  # beginner / intermediate / advanced
    goal_type = Column(String(50), nullable=True)  # lose_weight / 10k / half_marathon / marathon / general
    goal_target = Column(String(255), nullable=True)  # e.g. "sub 60 min 10k"
    last_health_sync_at = Column(DateTime(timezone=True), nullable=True)
    max_hr = Column(Integer, default=settings.default_max_hr)
    max_credible_pace = Column(Float, default=3.0)
    max_gps_jump_m = Column(Float, default=100.0)
    min_hr_for_fast_pace = Column(Integer, default=130)
    is_active = Column(Boolean, default=True)
    timezone = Column(String(50), nullable=True)  # Часовой пояс пользователя (User timezone, e.g. "Europe/Moscow")
    interval_pace_threshold = Column(Float, nullable=True)        # Порог темпа: разница с базовым (мин/км)
    interval_min_phase_duration = Column(Integer, nullable=True)  # Мин. длительность фазы (сек)
    interval_hr_lag_sec = Column(Integer, nullable=True)          # Лаг пульса (сек)
    interval_min_oscillations = Column(Integer, nullable=True)    # Мин. число осцилляций для interval
    created_at = Column(DateTime(timezone=True), default=utcnow)
    registered_at = Column(DateTime(timezone=True), nullable=True)

    training_sessions = relationship("TrainingSession", back_populates="user")
    daily_metrics = relationship("DailyMetrics", back_populates="user")
    weight_measurements = relationship("WeightMeasurement", back_populates="user")
    deleted_trainings = relationship("DeletedTraining", back_populates="user")
    watch_credentials = relationship("WatchCredential", back_populates="user")
