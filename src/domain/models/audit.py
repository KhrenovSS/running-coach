# Модель события аудита (Audit event model)

from sqlalchemy import Column, Integer, String, Text, JSON, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from src.domain.models.base import Base, utcnow


class AuditEvent(Base):
    __tablename__ = 'audit_events'

    id = Column(Integer, primary_key=True)
    event_type = Column(String(100), nullable=False, index=True)
    severity = Column(String(20), nullable=False, default='info')  # info, warning, error, critical
    message = Column(Text, nullable=False)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    ip_address = Column(String(45), nullable=True)
    metadata_json = Column(JSON, nullable=True)  # JSON object
    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)

    user = relationship("User")
