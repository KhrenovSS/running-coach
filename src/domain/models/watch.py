# Модель учётных данных часов (Watch credential model — multi-brand)

from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship

from src.domain.models.base import Base, utcnow


class WatchCredential(Base):
    __tablename__ = 'watch_credentials'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    brand = Column(String(50), nullable=False)  # e.g. 'coros', 'garmin', 'polar'
    encrypted_user = Column(String(255), nullable=True)   # encrypted email/username
    encrypted_password = Column(String(255), nullable=True)  # encrypted password
    access_token = Column(String(512), nullable=True)  # cached API token
    token_expires_at = Column(DateTime(timezone=True), nullable=True)
    last_activity_sync_at = Column(DateTime(timezone=True), nullable=True)
    last_health_sync_at = Column(DateTime(timezone=True), nullable=True)
    activity_sync_interval = Column(Integer, nullable=True)  # minutes, NULL = default 60
    health_sync_interval = Column(Integer, nullable=True)  # minutes, NULL = default 480
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user = relationship("User", back_populates="watch_credentials")
