# Реэкспорт для обратной совместимости (Re-export for backward compatibility)
from src.services.sync.utils import (  # noqa: F401
    SYNC_TICK_INTERVAL, _auto_sync_status, _auto_sync_status_lock,
    get_activity_interval_seconds, get_health_interval_seconds, _is_sync_due,
)
from src.services.sync.health import sync_health_for_user  # noqa: F401
from src.services.sync.activities import sync_activities_for_user  # noqa: F401
from src.services.sync.orchestrator import (  # noqa: F401
    run_sync_for_user, auto_sync_health, auto_sync_activities,
)
