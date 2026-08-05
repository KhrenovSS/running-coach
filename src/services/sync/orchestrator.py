# Оркестрация синхронизации: run_sync_for_user, auto_sync_* (Sync orchestration)

from datetime import timedelta, datetime, timezone

from src.utils.logger import get_logger
from src.config.constants import with_jitter, SYNC_FAILURE_NOTIFY_THRESHOLD
from src.models import SessionLocal, WatchCredential
from src.services.audit import AuditService
from src.services.async_utils import run_async_in_thread
from src.services.sync.utils import (
    _auto_sync_status, _auto_sync_status_lock, SYNC_TICK_INTERVAL,
    get_activity_interval_seconds, get_health_interval_seconds, _is_sync_due,
    effective_interval_seconds, ensure_aware_utc,
)
from src.services.sync.health import sync_health_for_user
from src.services.sync.activities import sync_activities_for_user
from src.services.telegram_notify import telegram_notify

logger = get_logger("app")


SYNC_CONFIG = {
    'health': {
        'key': 'health',
        'sync_fn': sync_health_for_user,
        'last_field': 'last_health_sync_at',
        'failures_field': 'health_sync_failures',
        'interval_fn': get_health_interval_seconds,
        'label': 'Health',
        'label_ru': 'здоровья',
        'empty_msg': 'нет новых данных',
        'empty_label': 'данных о сне нет',
    },
    'activity': {
        'key': 'activity',
        'sync_fn': sync_activities_for_user,
        'last_field': 'last_activity_sync_at',
        'failures_field': 'activity_sync_failures',
        'interval_fn': get_activity_interval_seconds,
        'label': 'Activity',
        'label_ru': 'тренировок',
        'empty_msg': 'нет новых тренировок',
        'empty_label': 'новых тренировок нет',
    },
}


def _record_sync_success(db, cred, cfg) -> None:
    """Успех: двигаем таймстемп, сбрасываем счётчик сбоев (Success: advance timestamp, reset failures)."""
    setattr(cred, cfg['last_field'], datetime.now(timezone.utc))
    if getattr(cred, cfg['failures_field'], 0):
        setattr(cred, cfg['failures_field'], 0)
    db.commit()


def _record_sync_failure(db, cred, cfg) -> None:
    """Сбой: счётчик +1, сброс кэша токена (reuse-until-failure), уведомление на N-м подряд.
    (Failure: increment counter, drop token cache, notify user at Nth consecutive failure.)
    Таймстемп last_*_sync_at сознательно НЕ двигаем — иначе пропущенные данные теряются.
    """
    failures = (getattr(cred, cfg['failures_field'], 0) or 0) + 1
    setattr(cred, cfg['failures_field'], failures)
    # Токен мог протухнуть — следующая попытка логинится заново (token may be stale — force re-login)
    cred.access_token = None
    cred.token_expires_at = None
    db.commit()
    if failures == SYNC_FAILURE_NOTIFY_THRESHOLD:
        last_ok = getattr(cred, cfg['last_field'])
        last_str = last_ok.strftime('%d.%m.%Y %H:%M UTC') if last_ok else 'никогда'
        telegram_notify(
            user_id=cred.user_id,
            text=f"⚠️ *Синхронизация {cfg['label_ru']} ({cred.brand}) не работает*\n"
                 f"Подряд сбоев: {failures}. Последний успех: {last_str}.\n"
                 f"Данные могли устареть — проверь учётные данные часов "
                 f"или запусти синхронизацию вручную.",
        )


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

        cfg = SYNC_CONFIG.get(sync_type)
        if not cfg:
            if progress is not None:
                progress['step'] = 'error'
                progress['message'] = f'Unknown sync type: {sync_type}'
                progress['done'] = True
            return

        result = run_async_in_thread(cfg['sync_fn'](cred, brand, db, progress=progress, pending=pending if sync_type == 'activity' else None))

        if result >= 0:
            _record_sync_success(db, cred, cfg)
            audit.log_sync_completed(brand=brand, user_id=user_id, found=result, processed=result,
                                     source=f"web_{brand}_sync")
        else:
            # Ручной синк: ошибку пользователь видит в progress — счётчик авто-сбоев не трогаем,
            # но кэш токена сбрасываем (manual sync: user sees the error; drop token cache only)
            cred.access_token = None
            cred.token_expires_at = None
            db.commit()
            audit.log_sync_failed(brand=brand, user_id=user_id, error='Sync failed (result=-1)',
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


def _auto_sync(sync_type: str):
    """
    Единая функция автосинхронизации для health и activity.
    Unified auto-sync function for both health and activity.
    """
    cfg = SYNC_CONFIG[sync_type]
    label = cfg['label']
    key = cfg['key']

    with _auto_sync_status_lock:
        _auto_sync_status[key]['status'] = 'syncing'
        _auto_sync_status[key]['message'] = 'Синхронизация...'
    try:
        now = datetime.now(timezone.utc)
        # Сессия держится открытой на весь цикл, чтобы коммитить last_*_sync_at
        # (иначе detached-объекты + отсутствие commit → таймстемпы не двигаются → шторм ресинков).
        # Session stays open across the loop so last_*_sync_at actually commits.
        db = SessionLocal()
        try:
            credentials = db.query(WatchCredential).filter(
                WatchCredential.is_active == True,
                WatchCredential.encrypted_password.isnot(None),
            ).all()

            if not credentials:
                logger.info("%s sync: нет учётных данных WatchCredential", label)
                with _auto_sync_status_lock:
                    s = _auto_sync_status[key]
                    s['status'] = 'ok'
                    s['last_run'] = now
                    s['message'] = 'Нет учётных данных'
                    s['next_run'] = now + timedelta(seconds=with_jitter(SYNC_TICK_INTERVAL))
                return

            total_synced = 0
            total_empty = 0
            total_failed = 0
            min_next = None
            for cred in credentials:
                # Backoff: интервал растёт экспоненциально с числом подряд сбоев
                # (Backoff: interval grows exponentially with consecutive failures)
                failures = getattr(cred, cfg['failures_field'], 0) or 0
                interval = effective_interval_seconds(cfg['interval_fn'](cred), failures)
                last_sync = ensure_aware_utc(getattr(cred, cfg['last_field']))
                if not _is_sync_due(last_sync, interval):
                    due = (last_sync + timedelta(seconds=interval) - now).total_seconds()
                    if min_next is None or due < min_next:
                        min_next = due
                    continue
                try:
                    result = run_async_in_thread(cfg['sync_fn'](cred, cred.brand, db))
                    if result > 0:
                        total_synced += result
                        logger.info("%s sync: brand=%s user=%s synced=%d", label, cred.brand, cred.user_id, result)
                        _record_sync_success(db, cred, cfg)
                    elif result == 0:
                        total_empty += 1
                        logger.info("%s sync: brand=%s user=%s — %s", label, cred.brand, cred.user_id, cfg['empty_msg'])
                        _record_sync_success(db, cred, cfg)
                    elif result == -1:
                        total_failed += 1
                        logger.warning("%s sync: brand=%s user=%s — сбой синхронизации (result=-1), подряд: %d",
                                       label, cred.brand, cred.user_id, failures + 1)
                        _record_sync_failure(db, cred, cfg)
                except Exception as e:
                    db.rollback()
                    total_failed += 1
                    logger.error("%s sync: brand=%s user=%s — исключение: %s", label, cred.brand, cred.user_id, e)
                    _record_sync_failure(db, cred, cfg)

            with _auto_sync_status_lock:
                s = _auto_sync_status[key]
                s['status'] = 'ok'
                s['last_run'] = now
                if total_synced > 0:
                    s['message'] = f'✓ Синхронизировано: {total_synced}'
                elif total_empty > 0 and total_failed == 0:
                    s['message'] = f'🟡 Синхронизация прошла, но {cfg["empty_label"]}'
                elif total_failed > 0:
                    s['message'] = f'⚠ Ошибок: {total_failed}, пусто: {total_empty}'
                else:
                    s['message'] = 'Нет учётных данных'
                next_seconds = min_next if min_next is not None else SYNC_TICK_INTERVAL
                s['next_run'] = now + timedelta(seconds=with_jitter(int(next_seconds)))
            logger.info("%s sync: итого — synced=%d, empty=%d, failed=%d, next=%ds", label, total_synced, total_empty, total_failed, int(next_seconds))
        finally:
            db.close()
    except Exception as e:
        logger.exception("%s sync: глобальная ошибка", label)
        with _auto_sync_status_lock:
            s = _auto_sync_status[key]
            s['status'] = 'error'
            s['last_run'] = now
            s['message'] = str(e)[:80]
            s['next_run'] = now + timedelta(seconds=with_jitter(SYNC_TICK_INTERVAL))


def auto_sync_health():
    _auto_sync('health')


def auto_sync_activities():
    _auto_sync('activity')
