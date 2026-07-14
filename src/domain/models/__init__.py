# Реэкспорт всех моделей для обратной совместимости (Re-export all models for backward compatibility)
from src.domain.models.base import Base, utcnow, get_engine, SessionLocal, get_db, init_db
from src.domain.models.user import User
from src.domain.models.training import TrainingSession, TrainingFeedback, DeletedTraining
from src.domain.models.watch import WatchCredential
from src.domain.models.health import DailyMetrics, WeightMeasurement
from src.domain.models.auth import AuthToken
from src.domain.models.audit import AuditEvent

__all__ = [
    'Base', 'utcnow', 'get_engine', 'SessionLocal', 'get_db', 'init_db',
    'User', 'TrainingSession', 'TrainingFeedback', 'DeletedTraining',
    'WatchCredential', 'DailyMetrics', 'WeightMeasurement',
    'AuthToken', 'AuditEvent',
]
