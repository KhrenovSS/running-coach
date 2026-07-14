# Утилиты синхронизации: интервалы, статус, клиент (Sync utilities: intervals, status, client)

import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.utils.logger import get_logger
from src.crypto import decrypt, safe_decrypt
from src.config.constants import (
    MIN_ACTIVITY_SYNC_INTERVAL_MIN,
    MIN_HEALTH_SYNC_INTERVAL_MIN,
    MAX_SYNC_INTERVAL_MIN,
    DEFAULT_ACTIVITY_SYNC_INTERVAL_MIN,
    DEFAULT_HEALTH_SYNC_INTERVAL_MIN,
)
from src.watch import get_watch_client, BaseWatchClient
from src.models import WatchCredential

logger = get_logger("app")

# Статус автосинхронизации (Auto-sync status tracking)
_auto_sync_status = {
    'health': {'last_run': None, 'status': 'idle', 'message': '', 'next_run': None},
    'activity': {'last_run': None, 'status': 'idle', 'message': '', 'next_run': None},
}
_auto_sync_status_lock = threading.Lock()


def get_auto_sync_status_snapshot() -> dict:
    """Thread-safe deep-copied snapshot of auto-sync status."""
    import copy
    with _auto_sync_status_lock:
        return copy.deepcopy(_auto_sync_status)

# Базовый интервал тика планировщика (Scheduler tick interval — 5 минут)
SYNC_TICK_INTERVAL: int = 300


# Получить эффективный интервал синхронизации тренировок для учётной записи (Get effective activity sync interval for credential)
def get_activity_interval_seconds(cred: WatchCredential) -> int:
    minutes = cred.activity_sync_interval or DEFAULT_ACTIVITY_SYNC_INTERVAL_MIN
    return max(MIN_ACTIVITY_SYNC_INTERVAL_MIN, min(minutes, MAX_SYNC_INTERVAL_MIN)) * 60


# Получить эффективный интервал синхронизации здоровья для учётной записи (Get effective health sync interval for credential)
def get_health_interval_seconds(cred: WatchCredential) -> int:
    minutes = cred.health_sync_interval or DEFAULT_HEALTH_SYNC_INTERVAL_MIN
    return max(MIN_HEALTH_SYNC_INTERVAL_MIN, min(minutes, MAX_SYNC_INTERVAL_MIN)) * 60


# Проверить, пора ли синхронизироваться по интервалу (Check if sync is due based on interval)
def _is_sync_due(last_sync_at, interval_seconds: int) -> bool:
    if last_sync_at is None:
        return True  # Никогда не синхронизировалось — пора (Never synced — due)
    elapsed = (datetime.now(timezone.utc) - last_sync_at).total_seconds()
    return elapsed >= interval_seconds


# Создать клиента для бренда по WatchCredential (Create a brand client from WatchCredential)
async def _make_client(cred: WatchCredential) -> Optional[BaseWatchClient]:
    plain_password = decrypt(cred.encrypted_password) if cred.encrypted_password else None
    if not plain_password:
        return None
    email = safe_decrypt(cred.encrypted_user) or cred.encrypted_user or ''
    client = get_watch_client(cred.brand, email=email, password=plain_password, timeout=15)
    if client is None:
        logger.warning("Unknown watch brand: %s", cred.brand)
        return None
    try:
        await client.authenticate()
    except Exception as e:
        logger.warning("Auth failed for brand=%s user=%s: %s", cred.brand, email, e)
        return None
    return client
