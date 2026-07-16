# Модели метрик здоровья и веса (Health metrics and weight models)

from sqlalchemy import Column, Integer, Float, String, DateTime, Date, JSON, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship

from src.domain.models.base import Base, utcnow


class DailyMetrics(Base):
    __tablename__ = 'daily_metrics'
    __table_args__ = (
        UniqueConstraint('user_id', 'date', name='uq_user_date'),
        Index('ix_daily_metrics_date', 'date'),
    )
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    date = Column(Date, nullable=False)
    avg_sleep_hrv = Column(Float, nullable=True)
    sleep_hrv_baseline = Column(Float, nullable=True)
    sleep_hrv_sd = Column(Float, nullable=True)
    rhr = Column(Integer, nullable=True)
    tired_rate = Column(Integer, nullable=True)
    training_load = Column(Float, nullable=True)
    training_load_ratio = Column(Float, nullable=True)
    performance = Column(Integer, nullable=True)
    ati = Column(Float, nullable=True)
    cti = Column(Float, nullable=True)
    vo2max = Column(Float, nullable=True)
    lthr = Column(Integer, nullable=True)
    stamina_level = Column(Float, nullable=True)
    ltsp = Column(Float, nullable=True)
    stamina_level_7d = Column(Float, nullable=True)
    synced_at = Column(DateTime(timezone=True), default=utcnow)
    recovery_pct = Column(Integer, nullable=True)  # Coros recovery % (0-100)
    form_score = Column(Float, nullable=True)  # Coros "Базовая форма"
    load_impact = Column(Float, nullable=True)  # Coros "Влияние нагрузки"
    intensity_trend = Column(Float, nullable=True)  # Coros "Тренд интенсивности"
    sleep_hrv_interval_list = Column(JSON, nullable=True)  # Coros HRV intervals [min, low, normal_start, normal_end]
    source_brand = Column(String(50), nullable=True)  # e.g. 'coros', 'garmin' (source of metric)

    user = relationship("User", back_populates="daily_metrics")


class WeightMeasurement(Base):
    __tablename__ = 'weight_measurements'
    __table_args__ = (
        Index('ix_weight_user_measured', 'user_id', 'measured_at'),
    )
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    weight_kg = Column(Float, nullable=False)
    measured_at = Column(DateTime(timezone=True), default=utcnow)

    user = relationship("User", back_populates="weight_measurements")
