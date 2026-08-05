# Утилиты синхронизации: интервалы, статус, клиент (Sync utilities: intervals, status, client)

import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.utils.logger import get_logger
from src.crypto import decrypt, safe_decrypt
from src.config import settings
from src.config.constants import (
    MIN_ACTIVITY_SYNC_INTERVAL_MIN,
    MIN_HEALTH_SYNC_INTERVAL_MIN,
    MAX_SYNC_INTERVAL_MIN,
    DEFAULT_ACTIVITY_SYNC_INTERVAL_MIN,
    DEFAULT_HEALTH_SYNC_INTERVAL_MIN,
    SYNC_BACKOFF_MAX_EXP,
    WATCH_TOKEN_TTL_HOURS,
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


# Нормализовать naive datetime к aware-UTC (Normalize naive datetime to aware UTC).
# PG отдаёт aware для TIMESTAMPTZ, но SQLite (тесты) и легаси-данные могут быть naive.
def ensure_aware_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# Проверить, пора ли синхронизироваться по интервалу (Check if sync is due based on interval)
def _is_sync_due(last_sync_at, interval_seconds: int) -> bool:
    if last_sync_at is None:
        return True  # Никогда не синхронизировалось — пора (Never synced — due)
    elapsed = (datetime.now(timezone.utc) - ensure_aware_utc(last_sync_at)).total_seconds()
    return elapsed >= interval_seconds


# Эффективный интервал с экспоненциальным backoff по числу подряд сбоев
# (Effective interval with exponential backoff by consecutive failure count)
def effective_interval_seconds(base_seconds: int, failures: int) -> int:
    exp = min(max(failures or 0, 0), SYNC_BACKOFF_MAX_EXP)
    return min(base_seconds * (2 ** exp), MAX_SYNC_INTERVAL_MIN * 60)


# Создать клиента для бренда по WatchCredential (Create a brand client from WatchCredential)
async def _make_client(cred: WatchCredential) -> Optional[BaseWatchClient]:
    plain_password = decrypt(cred.encrypted_password) if cred.encrypted_password else None
    if not plain_password:
        return None
    email = safe_decrypt(cred.encrypted_user) or cred.encrypted_user or ''
    client = get_watch_client(cred.brand, email=email, password=plain_password, timeout=settings.http_timeout)
    if client is None:
        logger.warning("Unknown watch brand: %s", cred.brand)
        return None

    # Кэш токена (reuse until failure): свежий токен → без повторного логина.
    # При сбое синка оркестратор сбрасывает кэш → следующая попытка логинится заново.
    # (Token cache, reuse-until-failure: orchestrator clears it on sync failure.)
    now = datetime.now(timezone.utc)
    token_expires = ensure_aware_utc(cred.token_expires_at)  # legacy/SQLite могут отдать naive
    if (cred.access_token and token_expires and token_expires > now
            and client.resume_session(cred.access_token, cred.api_user_id)):
        logger.debug("Resumed cached token for brand=%s user=%s", cred.brand, cred.user_id)
        return client

    try:
        await client.authenticate()
    except Exception as e:
        logger.warning("Auth failed for brand=%s user=%s: %s", cred.brand, email, e)
        return None

    # Персистим свежий токен на cred (in-memory) — commit делает вызывающий код
    # (Persist fresh token onto cred in-memory — caller commits)
    token, api_user_id = client.session_token()
    if token:
        cred.access_token = token
        cred.api_user_id = api_user_id
        cred.token_expires_at = now + timedelta(hours=WATCH_TOKEN_TTL_HOURS)
    return client
