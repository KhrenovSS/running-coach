# Brand-agnostic сервис синхронизации (Brand-agnostic sync service)

import json
import os
import tempfile
import threading
from datetime import timedelta, date, datetime, timezone
from typing import Optional

from src.utils.logger import get_logger
from src.services.audit import AuditService
from src.services.async_utils import run_async_in_thread
from src.crypto import decrypt
from src.config.constants import (
    MIN_ACTIVITY_SYNC_INTERVAL_MIN,
    MIN_HEALTH_SYNC_INTERVAL_MIN,
    MAX_SYNC_INTERVAL_MIN,
    DEFAULT_ACTIVITY_SYNC_INTERVAL_MIN,
    DEFAULT_HEALTH_SYNC_INTERVAL_MIN,
)
from src.models import SessionLocal, User, DailyMetrics, TrainingSession, DeletedTraining, WatchCredential
from src.services.telegram_notify import telegram_notify
from src.watch import get_watch_client, BaseWatchClient

logger = get_logger("app")

# Статус автосинхронизации (Auto-sync status tracking)
_auto_sync_status = {
    'health': {'last_run': None, 'status': 'idle', 'message': '', 'next_run': None},
    'activity': {'last_run': None, 'status': 'idle', 'message': '', 'next_run': None},
}
_auto_sync_status_lock = threading.Lock()

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
    client = get_watch_client(cred.brand, email=cred.encrypted_user, password=plain_password, timeout=15)
    if client is None:
        logger.warning("Unknown watch brand: %s", cred.brand)
        return None
    try:
        await client.authenticate()
    except Exception as e:
        logger.warning("Auth failed for brand=%s user=%s: %s", cred.brand, cred.encrypted_user, e)
        return None
    return client


# Сохранить dashboard данные в today's запись DailyMetrics (Save dashboard data to today's DailyMetrics)
async def save_dashboard_data(client: BaseWatchClient, db, user_id: int, brand: str):
    try:
        dashboard = await client.get_dashboard()
        if not dashboard:
            return
        info = dashboard.get('summaryInfo')
        if not info:
            return
        today = date.today()
        dm = db.query(DailyMetrics).filter(
            DailyMetrics.user_id == user_id,
            DailyMetrics.date == today
        ).first()
        if not dm:
            dm = DailyMetrics(user_id=user_id, date=today, source_brand=brand)
            db.add(dm)
            db.flush()
        dm.recovery_pct = info.get('recoveryPct')
        dm.rhr = info.get('rhr')
        sleep_data = info.get('sleepHrvData', {})
        hrv_list = sleep_data.get('sleepHrvList', [])
        if hrv_list:
            latest = hrv_list[-1]
            if dm.avg_sleep_hrv is None:
                dm.avg_sleep_hrv = latest.get('avgSleepHrv')
            if dm.sleep_hrv_baseline is None:
                dm.sleep_hrv_baseline = latest.get('sleepHrvBase')
            if dm.sleep_hrv_sd is None:
                dm.sleep_hrv_sd = latest.get('sleepHrvSd')
        intervals = sleep_data.get('lastSleepHrvIntervalList')
        if intervals:
            dm.sleep_hrv_interval_list = json.dumps(intervals)
        if not dm.source_brand:
            dm.source_brand = brand
        db.commit()
    except Exception as e:
        logger.warning("Dashboard save error: %s", e)


# Синхронизация метрик здоровья для пользователя (Sync health metrics for a user)
async def sync_health_for_user(cred: WatchCredential, brand: str,
                               progress: dict | None = None) -> int:
    """Возвращает количество новых синхронизированных записей (Return count of new synced records).

    progress — dict для отслеживания прогресса (web UI); None для автосинхронизации.
    """
    client = await _make_client(cred)
    if not client:
        logger.warning("Health sync: brand=%s user=%s — не удалось создать клиент (auth failed)", brand, cred.user_id)
        if progress is not None:
            progress['step'] = 'error'
            progress['message'] = f'Ошибка аутентификации {brand.capitalize()}'
            progress['done'] = True
        return -1

    db = SessionLocal()
    try:
        if progress is not None:
            progress['step'] = 'fetch'
            progress['message'] = 'Получение дневных метрик...'
        existing_dates = {r[0] for r in db.query(DailyMetrics.date).filter(DailyMetrics.user_id == cred.user_id).all()}
        today = date.today()
        start_day = (today - timedelta(days=120)).strftime("%Y%m%d")
        end_day = today.strftime("%Y%m%d")

        metrics_list = await client.get_daily_metrics(start_day, end_day)
        logger.info("Health sync for brand=%s user=%s: got %d records from API", brand, cred.user_id, len(metrics_list))
        if not metrics_list:
            await save_dashboard_data(client, db, cred.user_id, brand)
            logger.info("Health sync: brand=%s user=%s — API вернул пустой список (нет данных)", brand, cred.user_id)
            if progress is not None:
                progress['step'] = 'done'
                progress['message'] = 'Нет данных о восстановлении'
                progress['done'] = True
            return 0

        if progress is not None:
            progress['total_found'] = len(metrics_list)
            progress['total'] = len(metrics_list)

        analytics_by_date = {}
        try:
            analytics_list = await client.get_analytics()
            for a in analytics_list:
                ad = a.get('happenDay')
                if ad:
                    try:
                        d = datetime.strptime(str(ad), "%Y%m%d").date()
                        analytics_by_date[d] = a
                    except (ValueError, TypeError):
                        pass
        except Exception as e:
            logger.warning("Analytics fetch error: %s", e)

        synced = 0
        for i, entry in enumerate(metrics_list):
            if progress is not None:
                progress['current'] = i + 1
            happen_day = entry.get('happenDay')
            if not happen_day:
                continue
            happen_day = str(happen_day)
            try:
                entry_date = datetime.strptime(happen_day, "%Y%m%d").date()
            except (ValueError, TypeError):
                continue
            if entry_date in existing_dates:
                continue

            ana = analytics_by_date.get(entry_date, {})
            dm = DailyMetrics(
                user_id=cred.user_id,
                date=entry_date,
                source_brand=brand,
                avg_sleep_hrv=entry.get('avgSleepHrv'),
                sleep_hrv_baseline=entry.get('sleepHrvBase'),
                sleep_hrv_sd=entry.get('sleepHrvSd'),
                rhr=entry.get('rhr'),
                tired_rate=entry.get('tiredRateNew'),
                training_load=entry.get('trainingLoad'),
                training_load_ratio=entry.get('trainingLoadRatio'),
                performance=entry.get('performance'),
                ati=entry.get('ati'),
                cti=entry.get('cti'),
                vo2max=entry.get('vo2max') or ana.get('vo2max'),
                lthr=entry.get('lthr') or ana.get('lthr'),
                stamina_level=entry.get('staminaLevel') or ana.get('staminaLevel'),
                ltsp=ana.get('ltsp'),
                stamina_level_7d=ana.get('staminaLevel7d'),
            )
            db.add(dm)
            synced += 1
            if progress is not None:
                progress['synced'] = synced
                progress['message'] = f'Синхронизировано: {synced}/{len(metrics_list)}'

        if synced:
            db.commit()
            logger.info("Health sync: brand=%s user=%s — добавлено %d новых записей", brand, cred.user_id, synced)
        else:
            logger.info("Health sync: brand=%s user=%s — все %d записей уже существуют (пропущены)", brand, cred.user_id, len(metrics_list))

        # Fill analytics gaps
        if analytics_by_date:
            updated = 0
            for entry_date, ana in analytics_by_date.items():
                existing = db.query(DailyMetrics).filter(DailyMetrics.user_id == cred.user_id, DailyMetrics.date == entry_date).first()
                if not existing:
                    continue
                changed = False
                if existing.vo2max is None and ana.get('vo2max') is not None:
                    existing.vo2max = ana.get('vo2max'); changed = True
                if existing.lthr is None and ana.get('lthr') is not None:
                    existing.lthr = ana.get('lthr'); changed = True
                if existing.stamina_level is None and ana.get('staminaLevel') is not None:
                    existing.stamina_level = ana.get('staminaLevel'); changed = True
                if existing.ltsp is None and ana.get('ltsp') is not None:
                    existing.ltsp = ana.get('ltsp'); changed = True
                if existing.stamina_level_7d is None and ana.get('staminaLevel7d') is not None:
                    existing.stamina_level_7d = ana.get('staminaLevel7d'); changed = True
                if changed:
                    updated += 1
            if updated:
                db.commit()
                logger.info("Health sync: brand=%s user=%s — заполнено аналитикой %d записей", brand, cred.user_id, updated)

        await save_dashboard_data(client, db, cred.user_id, brand)
        if progress is not None:
            progress['step'] = 'done'
            progress['message'] = f'Синхронизировано: {synced}'
            progress['done'] = True
        return synced
    except Exception as e:
        logger.exception("Health sync error for brand=%s user=%s", brand, cred.user_id)
        if progress is not None:
            progress['step'] = 'error'
            progress['message'] = f'Ошибка: {type(e).__name__}: {e}'
            progress['done'] = True
        return 0
    finally:
        db.close()
        try:
            await client.close()
        except Exception:
            pass


# Синхронизация тренировок для пользователя (Sync activities for a user)
async def sync_activities_for_user(cred: WatchCredential, brand: str,
                                  progress: dict | None = None,
                                  pending: dict | None = None) -> int:
    """Возвращает количество новых синхронизированных тренировок (Return count of synced activities).

    progress — dict для отслеживания прогресса (web UI); None для автосинхронизации.
    pending  — dict для кэширования pending-deleted тренировок (web UI); None для автосинхронизации.
    """
    from src.parsers.fit_parser import parse_fit
    from src.analysis.utils import format_pace, format_duration

    async def _download_parse(act):
        """Скачать FIT и распарсить; вернуть data dict или None (Download+parse FIT; return data or None)."""
        fit_data = await client.download_activity(act['id'], act['sport_type'])
        if not fit_data:
            return None
        with tempfile.NamedTemporaryFile(delete=False, suffix=".fit") as tmp:
            tmp.write(fit_data)
            tmp_path = tmp.name
        try:
            return parse_fit(tmp_path, max_hr=us.max_hr,
                             max_credible_pace=us.max_credible_pace,
                             max_gps_jump_m=us.max_gps_jump_m,
                             min_hr_for_fast_pace=us.min_hr_for_fast_pace)
        except Exception as e:
            logger.warning("Parse error for %s: %s", act.get('name'), e)
            return None
        finally:
            os.unlink(tmp_path)

    client = await _make_client(cred)
    if not client:
        logger.warning("Activity sync: brand=%s user=%s — не удалось создать клиент (auth failed)", brand, cred.user_id)
        if progress is not None:
            progress['step'] = 'error'
            progress['message'] = f'Ошибка аутентификации {brand.capitalize()}'
            progress['done'] = True
        return -1

    if progress is not None:
        progress['step'] = 'fetch'
        progress['message'] = f'Получение списка активностей из {brand.capitalize()}...'

    db = SessionLocal()
    audit = AuditService(db)
    try:
        us = db.query(User).filter(User.id == cred.user_id).first()
        if not us:
            logger.warning("Activity sync: brand=%s user=%s — пользователь не найден", brand, cred.user_id)
            return -1

        # Буфер 2ч чтобы не пропустить активности, которые Coros обработал с задержкой (2h lookback buffer to catch delayed Coros activities)
        since = cred.last_activity_sync_at - timedelta(hours=2) if cred.last_activity_sync_at else None
        logger.info("Activity sync: brand=%s user=%s last_activity_sync_at=%s since=%s",
                     brand, cred.user_id, cred.last_activity_sync_at, since)
        activities = await client.list_activities(since=since)
        if not activities:
            logger.info("Activity sync: brand=%s user=%s — API вернул пустой список", brand, cred.user_id)
            if progress is not None:
                progress['step'] = 'done'
                progress['message'] = 'Нет новых беговых активностей'
                progress['done'] = True
            return 0

        logger.info("Activity sync: brand=%s user=%s — API вернул %d активностей, фильтрация...", brand, cred.user_id, len(activities))
        if progress is not None:
            progress['total_found'] = len(activities)

        existing_begin = {r[0] for r in db.query(TrainingSession.begin_ts).filter(TrainingSession.user_id == cred.user_id).all()}
        all_deleted = db.query(DeletedTraining).filter(DeletedTraining.user_id == cred.user_id).all()

        new_acts = [a for a in activities if a.get('start_time') and a['start_time'] not in existing_begin]

        # Фильтруем already-deleted, кэшируем в pending если предоставлен (Filter already-deleted, cache in pending if provided)
        acts_to_sync = []
        skipped_deleted = 0
        for act in new_acts:
            bt = act.get('start_time')
            deleted_match = None
            for d in all_deleted:
                if d.begin_ts and abs((d.begin_ts - bt).total_seconds()) < 120:
                    deleted_match = d
                    break
            if deleted_match:
                skipped_deleted += 1
                if pending is not None:
                    # Скачиваем и парсим FIT, чтобы confirm_deleted мог восстановить (Download+parse FIT so confirm_deleted can restore)
                    data = await _download_parse(act)
                    if data and data.get('training_type') not in ('invalid', None):
                        import uuid as _uuid
                        tid = str(_uuid.uuid4())
                        pending[tid] = {
                            'path': '', 'filename': act.get('name', 'activity'),
                            'data': data,
                        }
                        if 'pending_deleted' not in progress:
                            progress['pending_deleted'] = []
                            progress['has_pending_deleted'] = True
                        progress['pending_deleted'].append({
                            'temp_id': tid,
                            'date': deleted_match.begin_ts.strftime('%d.%m.%Y %H:%M'),
                            'distance': round(deleted_match.total_distance_km, 1) if deleted_match.total_distance_km else '—',
                            'distance_display': f'{deleted_match.total_distance_km:.1f} км' if deleted_match.total_distance_km else '—',
                            'pace': format_pace(deleted_match.avg_pace) if deleted_match.avg_pace else '—',
                            'duration': format_duration(deleted_match.duration_minutes) if deleted_match.duration_minutes else '—',
                            'type': deleted_match.training_type or '—',
                            'hr': f'{deleted_match.avg_heart_rate}' if deleted_match.avg_heart_rate else '—',
                        })
                continue
            acts_to_sync.append(act)

        if not acts_to_sync:
            logger.info("Activity sync: brand=%s user=%s — новых тренировок нет (всего=%d, already_exist=%d, deleted=%d)",
                         brand, cred.user_id, len(activities), len(new_acts) - skipped_deleted + len(activities) - len(new_acts), skipped_deleted)
            if progress is not None:
                progress['step'] = 'done'
                progress['message'] = 'Все активности уже импортированы'
                progress['total'] = 0
                progress['done'] = True
            return 0

        if progress is not None:
            progress['total'] = len(acts_to_sync)

        synced = 0
        skipped_existing = len(activities) - len(new_acts)
        new_trainings = []  # Собираем данные для per-training уведомлений (Collect data for per-training notifications)
        for i, act in enumerate(acts_to_sync):
            if progress is not None:
                progress['step'] = 'download'
                progress['current'] = i + 1
                progress['message'] = f'Скачивание {i+1}/{len(acts_to_sync)}: {act.get("name", "activity")}'

            bt = act.get('start_time')

            if progress is not None:
                progress['step'] = 'parse'
                progress['message'] = f'Обработка {i+1}/{len(acts_to_sync)}: {act.get("name", "activity")}'

            data = await _download_parse(act)
            if not data:
                if progress is not None:
                    progress['errors'].append(f"{act.get('name', '?')}: download/parse failed")
                continue

            if data.get('training_type') in ('invalid', None):
                if progress is not None:
                    progress['errors'].append(f"{act.get('name', '?')}: invalid data")
                continue

            session = TrainingSession(**data)
            session.user_id = cred.user_id
            tz = data.get('timezone')
            if tz and not us.timezone:
                us.timezone = tz
            db.add(session)
            db.flush()  # Получаем session.id до commit (Get session.id before commit)
            new_trainings.append({
                'session_id': session.id,
                'distance': data.get('total_distance_km', 0),
                'training_type': data.get('training_type', ''),
                'begin_ts': data.get('begin_ts', datetime.now(timezone.utc)),
            })
            synced += 1
            if progress is not None:
                progress['synced'] = synced
            audit.log_training_uploaded(user_id=cred.user_id, training_id=session.id, filename=act.get('name', ''),
                                        distance_km=session.total_distance_km, training_type=session.training_type,
                                        source=f"{brand}_sync")

        if synced:
            db.commit()
            logger.info("Activity sync: brand=%s user=%s — синхронизировано %d новых тренировок (skipped_existing=%d, skipped_deleted=%d)",
                         brand, cred.user_id, synced, skipped_existing, skipped_deleted)
            # Уведомление по каждой тренировке с inline-клавиатурой оценки (Per-training notification with rating inline keyboard)
            for nt in new_trainings:
                sid = nt['session_id']
                dist = nt['distance']
                ttype = nt['training_type']
                begin = nt['begin_ts']
                date_str = begin.strftime("%d.%m.%Y") if begin else ""
                time_str = begin.strftime("%H:%M") if begin else ""
                row1 = [{"text": str(i), "callback_data": f"feedback:{sid}:{i}"} for i in range(0, 6)]
                row2 = [{"text": str(i), "callback_data": f"feedback:{sid}:{i}"} for i in range(6, 11)]
                telegram_notify(
                    user_id=cred.user_id,
                    text=f"🏃 *Новая тренировка синхронизирована!*\n"
                         f"▫️ {date_str} в {time_str}\n"
                         f"▫️ {dist:.1f} км\n"
                         f"▫️ {ttype or '—'}\n\n"
                         f"Насколько тяжёлой была тренировка?\n"
                         f"`0` — легко\n"
                         f"`10` — очень тяжело",
                    reply_markup={"inline_keyboard": [row1, row2]},
                )
        else:
            logger.info("Activity sync: brand=%s user=%s — новых тренировок нет (всего=%d, already_exist=%d, deleted=%d)",
                         brand, cred.user_id, len(activities), skipped_existing, skipped_deleted)

        if progress is not None:
            progress['step'] = 'done'
            progress['message'] = f'Синхронизировано: {synced}'
            progress['done'] = True
        return synced
    except Exception as e:
        logger.exception("Activity sync error for brand=%s user=%s", brand, cred.user_id)
        if progress is not None:
            progress['step'] = 'error'
            progress['message'] = f'Ошибка: {type(e).__name__}: {e}'
            progress['done'] = True
        return 0
    finally:
        db.close()
        try:
            await client.close()
        except Exception:
            pass


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