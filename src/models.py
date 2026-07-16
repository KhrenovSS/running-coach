# Shim для обратной совместимости: всё вынесено в src/domain/models/ (Backward compat shim: src/domain/models/)

# Re-export всех моделей и инфраструктуры (Re-export all models and infrastructure)
from src.domain.models import (  # noqa: F401
    Base, utcnow, get_engine, SessionLocal, get_db, init_db,
    User, TrainingSession, TrainingFeedback, DeletedTraining,
    WatchCredential, DailyMetrics, WeightMeasurement,
    AuthToken, AuditEvent,
)

# Deprecated: использовать src.services.user_service
from src.services.user_service import (  # noqa: F401
    get_user_settings as get_settings,
    get_user_by_telegram_id as get_user_by_telegram,
    get_or_create_user_by_telegram,
    get_user_by_id as get_user,
)
