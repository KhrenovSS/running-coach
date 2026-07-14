# Оркестрация синхронизации: run_sync_for_user, auto_sync_* (Sync orchestration)

from datetime import timedelta, datetime, timezone

from src.utils.logger import get_logger
from src.models import SessionLocal, WatchCredential
from src.services.audit import AuditService
from src.services.async_utils import run_async_in_thread
from src.services.sync.utils import (
    _auto_sync_status, _auto_sync_status_lock, SYNC_TICK_INTERVAL,
    get_activity_interval_seconds, get_health_interval_seconds, _is_sync_due,
)
from src.services.sync.health import sync_health_for_user
from src.services.sync.activities import sync_activities_for_user

logger = get_logger("app")


# Единая точка входа для синхронизации из web и Telegram (Unified sync entry point for web and Telegram)
def run_sync_for_user(user_id: int, brand: str, sync_type: str,
                      progress: dict | None = None,
                      pending: dict | None = None) -> None:
    """
    Запускает синхронизацию для конкретного пользователя и бренда.
    Runs sync for a specific user and brand.

    sync_type: 'activity' или 'health'.
    progress:  dict для отслеживания прогресса (web UI); None для автосинхронизации.
    pending:   dict для кэширования pending-deleted (web UI); None для авто/Telegram.
    """
    db = SessionLocal()
    audit = AuditService(db)
    try:
        cred = db.query(WatchCredential).filter(
            WatchCredential.user_id == user_id,
            WatchCredential.brand == brand,
            WatchCredential.is_active == True,
        ).first()
        if not cred or not cred.encrypted_password:
            if progress is not None:
                progress['step'] = 'error'
                progress['message'] = f'{brand.capitalize()} credentials not configured.'
                progress['done'] = True
            return

        audit.log_sync_started(brand=brand, user_id=user_id, source=f"web_{brand}_sync")

        if sync_type == 'activity':
            result = run_async_in_thread(sync_activities_for_user(cred, brand, progress=progress, pending=pending))
        elif sync_type == 'health':
            result = run_async_in_thread(sync_health_for_user(cred, brand, progress=progress))
        else:
            if progress is not None:
                progress['step'] = 'error'
                progress['message'] = f'Unknown sync type: {sync_type}'
                progress['done'] = True
            return

        if result >= 0:
            # Обновляем timestamp последней синхронизации (Update last sync timestamp)
            if sync_type == 'activity':
                cred.last_activity_sync_at = datetime.now(timezone.utc)
            else:
                cred.last_health_sync_at = datetime.now(timezone.utc)
            db.commit()
            audit.log_sync_completed(brand=brand, user_id=user_id, found=result, processed=result,
                                     source=f"web_{brand}_sync")
        else:
            audit.log_sync_failed(brand=brand, user_id=user_id, error='Authentication failed',
                                   source=f"web_{brand}_sync")
    except Exception as e:
        logger.error("run_sync_for_user error (user=%s brand=%s): %s", user_id, brand, e, exc_info=True)
        audit.log_sync_failed(brand=brand, user_id=user_id, error=str(e), source=f"web_{brand}_sync")
        if progress is not None:
            progress['step'] = 'error'
            progress['message'] = f'Ошибка: {type(e).__name__}: {e}'
            progress['done'] = True
    finally:
        db.close()


# Автосинхронизация здоровья всех пользователей с per-user интервалами (Auto health sync with per-user intervals)
def auto_sync_health():
    with _auto_sync_status_lock:
        _auto_sync_status['health']['status'] = 'syncing'
        _auto_sync_status['health']['message'] = 'Синхронизация...'
    try:
        now = datetime.now(timezone.utc)
        db = SessionLocal()
        try:
            credentials = db.query(WatchCredential).filter(
                WatchCredential.is_active == True,
                WatchCredential.encrypted_password.isnot(None),
            ).all()
        finally:
            db.close()

        if not credentials:
            logger.info("Health sync: нет учётных данных WatchCredential")
            with _auto_sync_status_lock:
                s = _auto_sync_status['health']
                s['status'] = 'ok'
                s['last_run'] = now
                s['message'] = 'Нет учётных данных'
                s['next_run'] = now + timedelta(seconds=SYNC_TICK_INTERVAL)
            return

        total_synced = 0
        total_empty = 0
        total_failed = 0
        # Минимальное время до следующей синхронизации (Minimum time to next sync)
        min_next = None
        for cred in credentials:
            interval = get_health_interval_seconds(cred)
            if not _is_sync_due(cred.last_health_sync_at, interval):
                # Рассчитываем, когда будет пора синхронизироваться (Calculate when sync is due)
                due = (cred.last_health_sync_at + timedelta(seconds=interval) - now).total_seconds()
                if min_next is None or due < min_next:
                    min_next = due
                continue
            try:
                result = run_async_in_thread(sync_health_for_user(cred, cred.brand))
                if result > 0:
                    total_synced += result
                    cred.last_health_sync_at = datetime.now(timezone.utc)
                    logger.info("Health sync: brand=%s user=%s synced=%d", cred.brand, cred.user_id, result)
                elif result == 0:
                    total_empty += 1
                    cred.last_health_sync_at = datetime.now(timezone.utc)
                    logger.info("Health sync: brand=%s user=%s — нет новых данных", cred.brand, cred.user_id)
                elif result == -1:
                    total_failed += 1
                    logger.warning("Health sync: brand=%s user=%s — ошибка аутентификации", cred.brand, cred.user_id)
            except Exception as e:
                total_failed += 1
                logger.error("Health sync: brand=%s user=%s — исключение: %s", cred.brand, cred.user_id, e)

        with _auto_sync_status_lock:
            s = _auto_sync_status['health']
            s['status'] = 'ok'
            s['last_run'] = now
            if total_synced > 0:
                s['message'] = f'✓ Синхронизировано: {total_synced}'
            elif total_empty > 0 and total_failed == 0:
                s['message'] = '🟡 Синхронизация прошла, но данных о сне нет'
            elif total_failed > 0:
                s['message'] = f'⚠ Ошибок: {total_failed}, пусто: {total_empty}'
            else:
                s['message'] = 'Нет учётных данных'
            # Следующий запуск — через минимальный интервал (Next run — at minimum interval)
            next_seconds = min_next if min_next is not None else SYNC_TICK_INTERVAL
            s['next_run'] = now + timedelta(seconds=int(next_seconds))
        logger.info("Health sync: итого — synced=%d, empty=%d, failed=%d, next=%ds", total_synced, total_empty, total_failed, int(next_seconds))
    except Exception as e:
        logger.exception("Health sync: глобальная ошибка")
        with _auto_sync_status_lock:
            s = _auto_sync_status['health']
            s['status'] = 'error'
            s['last_run'] = now
            s['message'] = str(e)[:80]
            s['next_run'] = now + timedelta(seconds=SYNC_TICK_INTERVAL)


# Автосинхронизация активностей всех пользователей с per-user интервалами (Auto activity sync with per-user intervals)
def auto_sync_activities():
    with _auto_sync_status_lock:
        _auto_sync_status['activity']['status'] = 'syncing'
        _auto_sync_status['activity']['message'] = 'Синхронизация...'
    try:
        now = datetime.now(timezone.utc)
        db = SessionLocal()
        try:
            credentials = db.query(WatchCredential).filter(
                WatchCredential.is_active == True,
                WatchCredential.encrypted_password.isnot(None),
            ).all()
        finally:
            db.close()

        if not credentials:
            logger.info("Activity sync: нет учётных данных WatchCredential")
            with _auto_sync_status_lock:
                s = _auto_sync_status['activity']
                s['status'] = 'ok'
                s['last_run'] = now
                s['message'] = 'Нет учётных данных'
                s['next_run'] = now + timedelta(seconds=SYNC_TICK_INTERVAL)
            return

        total_synced = 0
        total_empty = 0
        total_failed = 0
        min_next = None
        for cred in credentials:
            interval = get_activity_interval_seconds(cred)
            if not _is_sync_due(cred.last_activity_sync_at, interval):
                due = (cred.last_activity_sync_at + timedelta(seconds=interval) - now).total_seconds()
                if min_next is None or due < min_next:
                    min_next = due
                continue
            try:
                result = run_async_in_thread(sync_activities_for_user(cred, cred.brand))
                if result > 0:
                    total_synced += result
                    logger.info("Activity sync: brand=%s user=%s synced=%d", cred.brand, cred.user_id, result)
                elif result == 0:
                    total_empty += 1
                    logger.info("Activity sync: brand=%s user=%s — нет новых тренировок", cred.brand, cred.user_id)
                elif result == -1:
                    total_failed += 1
                    logger.warning("Activity sync: brand=%s user=%s — ошибка аутентификации", cred.brand, cred.user_id)
            except Exception as e:
                total_failed += 1
                logger.error("Activity sync: brand=%s user=%s — исключение: %s", cred.brand, cred.user_id, e)

        with _auto_sync_status_lock:
            s = _auto_sync_status['activity']
            s['status'] = 'ok'
            s['last_run'] = now
            if total_synced > 0:
                s['message'] = f'✓ Синхронизировано: {total_synced}'
            elif total_empty > 0 and total_failed == 0:
                s['message'] = '🟡 Синхронизация прошла, но новых тренировок нет'
            elif total_failed > 0:
                s['message'] = f'⚠ Ошибок: {total_failed}, пусто: {total_empty}'
            else:
                s['message'] = 'Нет учётных данных'
            next_seconds = min_next if min_next is not None else SYNC_TICK_INTERVAL
            s['next_run'] = now + timedelta(seconds=int(next_seconds))
        logger.info("Activity sync: итого — synced=%d, empty=%d, failed=%d, next=%ds", total_synced, total_empty, total_failed, int(next_seconds))
    except Exception as e:
        logger.exception("Activity sync: глобальная ошибка")
        with _auto_sync_status_lock:
            s = _auto_sync_status['activity']
            s['status'] = 'error'
            s['last_run'] = now
            s['message'] = str(e)[:80]
            s['next_run'] = now + timedelta(seconds=SYNC_TICK_INTERVAL)
