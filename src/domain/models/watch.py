# Модель учётных данных часов (Watch credential model — multi-brand)

from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship

from src.domain.models.base import Base, utcnow


class WatchCredential(Base):
    __tablename__ = 'watch_credentials'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    brand = Column(String(50), nullable=False)  # e.g. 'coros', 'garmin', 'polar'
    encrypted_user = Column(String(255), nullable=True)   # encrypted email/username
    encrypted_password = Column(String(255), nullable=True)  # encrypted password
    access_token = Column(String(512), nullable=True)  # cached API token
    token_expires_at = Column(DateTime(timezone=True), nullable=True)
    api_user_id = Column(String(64), nullable=True)  # ID пользователя в API бренда — нужен для resume токена (brand API user id for token resume)
    last_activity_sync_at = Column(DateTime(timezone=True), nullable=True)
    last_health_sync_at = Column(DateTime(timezone=True), nullable=True)
    # Счётчики ПОДРЯД идущих сбоев авто-синка: в БД, т.к. синкают два процесса — app и bot
    # (Consecutive auto-sync failure counters: DB-backed — two processes sync: app and bot)
    activity_sync_failures = Column(Integer, nullable=False, default=0, server_default='0')
    health_sync_failures = Column(Integer, nullable=False, default=0, server_default='0')
    activity_sync_interval = Column(Integer, nullable=True)  # minutes, NULL = default 60
    health_sync_interval = Column(Integer, nullable=True)  # minutes, NULL = default 480
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user = relationship("User", back_populates="watch_credentials")
