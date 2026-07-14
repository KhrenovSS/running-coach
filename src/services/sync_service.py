# Shim для обратной совместимости: всё вынесено в src/services/sync/ (Backward compat shim: src/services/sync/)

import warnings

warnings.warn(
    "Import from src.services.sync instead of src.services.sync_service. "
    "This shim will be removed in a future sprint.",
    DeprecationWarning,
    stacklevel=2,
)

from src.services.sync import (  # noqa: F401, E402
    SYNC_TICK_INTERVAL, _auto_sync_status, _auto_sync_status_lock,
    get_activity_interval_seconds, get_health_interval_seconds, _is_sync_due,
    sync_health_for_user, sync_activities_for_user,
    run_sync_for_user, auto_sync_health, auto_sync_activities,
)
