# Brand-agnostic сервис синхронизации (Brand-agnostic sync service)

import json
import os
import tempfile
import threading
from datetime import timedelta, date, datetime, timezone
from typing import Optional

from src.logger import get_logger
from src.services.audit import AuditService
from src.crypto import decrypt
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

# Интервалы синхронизации из переменных окружения (Env-based sync intervals, will be per-credential in Sprint 6)
health_sync_interval = int(os.getenv("COROS_HEALTH_SYNC_INTERVAL", "21600"))
activity_sync_interval = int(os.getenv("COROS_ACTIVITY_SYNC_INTERVAL", "1800"))


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
async def sync_health_for_user(cred: WatchCredential, brand: str) -> int:
    """Возвращает количество новых синхронизированных записей (Return count of new synced records)"""
    client = await _make_client(cred)
    if not client:
        logger.warning("Health sync: brand=%s user=%s — не удалось создать клиент (auth failed)", brand, cred.user_id)
        return -1

    db = SessionLocal()
    try:
        existing_dates = {r[0] for r in db.query(DailyMetrics.date).filter(DailyMetrics.user_id == cred.user_id).all()}
        today = date.today()
        start_day = (today - timedelta(days=120)).strftime("%Y%m%d")
        end_day = today.strftime("%Y%m%d")

        metrics_list = await client.get_daily_metrics(start_day, end_day)
        logger.info("Health sync for brand=%s user=%s: got %d records from API", brand, cred.user_id, len(metrics_list))
        if not metrics_list:
            await save_dashboard_data(client, db, cred.user_id, brand)
            logger.info("Health sync: brand=%s user=%s — API вернул пустой список (нет данных)", brand, cred.user_id)
            return 0

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
        for entry in metrics_list:
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
        return synced
    except Exception as e:
        logger.exception("Health sync error for brand=%s user=%s", brand, cred.user_id)
        return 0
    finally:
        db.close()
        try:
            await client.close()
        except Exception:
            pass


# Синхронизация тренировок для пользователя (Sync activities for a user)
async def sync_activities_for_user(cred: WatchCredential, brand: str) -> int:
    """Возвращает количество новых синхронизированных тренировок (Return count of synced activities)"""
    from src.parsers.fit_parser import parse_fit

    client = await _make_client(cred)
    if not client:
        logger.warning("Activity sync: brand=%s user=%s — не удалось создать клиент (auth failed)", brand, cred.user_id)
        return -1

    db = SessionLocal()
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
            return 0

        logger.info("Activity sync: brand=%s user=%s — API вернул %d активностей, фильтрация...", brand, cred.user_id, len(activities))

        existing_begin = {r[0] for r in db.query(TrainingSession.begin_ts).filter(TrainingSession.user_id == cred.user_id).all()}
        all_deleted = db.query(DeletedTraining).filter(DeletedTraining.user_id == cred.user_id).all()

        synced = 0
        skipped_existing = 0
        skipped_deleted = 0
        for act in activities:
            bt = act.get('start_time')
            if not bt:
                continue
            if bt in existing_begin:
                skipped_existing += 1
                continue

            fit_data = await client.download_activity(act['id'], act['sport_type'])
            if not fit_data:
                continue

            # Check deleted
            deleted_match = None
            for d in all_deleted:
                if d.begin_ts and abs((d.begin_ts - bt).total_seconds()) < 120:
                    deleted_match = d
                    break
            if deleted_match:
                skipped_deleted += 1
                continue

            with tempfile.NamedTemporaryFile(delete=False, suffix=".fit") as tmp:
                tmp.write(fit_data)
                tmp_path = tmp.name

            try:
                data = parse_fit(tmp_path, max_hr=us.max_hr,
                                 max_credible_pace=us.max_credible_pace,
                                 max_gps_jump_m=us.max_gps_jump_m,
                                 min_hr_for_fast_pace=us.min_hr_for_fast_pace)
            except Exception:
                os.unlink(tmp_path)
                continue
            os.unlink(tmp_path)

            if not data:
                continue

            session = TrainingSession(**data)
            session.user_id = cred.user_id
            tz = data.get('timezone')
            if tz and not us.timezone:
                us.timezone = tz
            db.add(session)
            synced += 1

        if synced:
            cred.last_activity_sync_at = datetime.now(timezone.utc)
            db.commit()
            logger.info("Activity sync: brand=%s user=%s — синхронизировано %d новых тренировок (skipped_existing=%d, skipped_deleted=%d)",
                         brand, cred.user_id, synced, skipped_existing, skipped_deleted)
            # Уведомление в Telegram (Notify user in Telegram about new training)
            telegram_notify(
                user_id=cred.user_id,
                text=f"🏃 Новая тренировка синхронизирована!\n"
                     f"📅 {datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M')} UTC\n"
                     f"Всего добавлено: {synced}\n"
                     f"Зайди в веб-интерфейс для деталей."
            )
        else:
            logger.info("Activity sync: brand=%s user=%s — новых тренировок нет (всего=%d, already_exist=%d, deleted=%d)",
                         brand, cred.user_id, len(activities), skipped_existing, skipped_deleted)

        return synced
    except Exception as e:
        logger.exception("Activity sync error for brand=%s user=%s", brand, cred.user_id)
        return 0
    finally:
        db.close()
        try:
            await client.close()
        except Exception:
            pass


# Автосинхронизация здоровья всех пользователей (Auto health sync for all users)
def auto_sync_health():
    import asyncio
    with _auto_sync_status_lock:
        _auto_sync_status['health']['status'] = 'syncing'
        _auto_sync_status['health']['message'] = 'Синхронизация...'
    try:
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
                s['last_run'] = datetime.now(timezone.utc)
                s['message'] = 'Нет учётных данных'
                s['next_run'] = s['last_run'] + timedelta(seconds=health_sync_interval)
            return

        total_synced = 0
        total_empty = 0
        total_failed = 0
        for cred in credentials:
            try:
                result = asyncio.run(sync_health_for_user(cred, cred.brand))
                if result > 0:
                    total_synced += result
                    logger.info("Health sync: brand=%s user=%s synced=%d", cred.brand, cred.user_id, result)
                elif result == 0:
                    total_empty += 1
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
            s['last_run'] = datetime.now(timezone.utc)
            if total_synced > 0:
                s['message'] = f'✓ Синхронизировано: {total_synced}'
            elif total_empty > 0 and total_failed == 0:
                s['message'] = '🟡 Синхронизация прошла, но данных о сне нет'
            elif total_failed > 0:
                s['message'] = f'⚠ Ошибок: {total_failed}, пусто: {total_empty}'
            else:
                s['message'] = 'Нет учётных данных'
            s['next_run'] = s['last_run'] + timedelta(seconds=health_sync_interval)
        logger.info("Health sync: итого — synced=%d, empty=%d, failed=%d", total_synced, total_empty, total_failed)
    except Exception as e:
        logger.exception("Health sync: глобальная ошибка")
        with _auto_sync_status_lock:
            s = _auto_sync_status['health']
            s['status'] = 'error'
            s['last_run'] = datetime.now(timezone.utc)
            s['message'] = str(e)[:80]
            s['next_run'] = s['last_run'] + timedelta(seconds=health_sync_interval)


# Автосинхронизация активностей всех пользователей (Auto activity sync for all users)
def auto_sync_activities():
    import asyncio
    with _auto_sync_status_lock:
        _auto_sync_status['activity']['status'] = 'syncing'
        _auto_sync_status['activity']['message'] = 'Синхронизация...'
    try:
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
                s['last_run'] = datetime.now(timezone.utc)
                s['message'] = 'Нет учётных данных'
                s['next_run'] = s['last_run'] + timedelta(seconds=activity_sync_interval)
            return

        total_synced = 0
        total_empty = 0
        total_failed = 0
        for cred in credentials:
            try:
                result = asyncio.run(sync_activities_for_user(cred, cred.brand))
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
            s['last_run'] = datetime.now(timezone.utc)
            if total_synced > 0:
                s['message'] = f'✓ Синхронизировано: {total_synced}'
            elif total_empty > 0 and total_failed == 0:
                s['message'] = '🟡 Синхронизация прошла, но новых тренировок нет'
            elif total_failed > 0:
                s['message'] = f'⚠ Ошибок: {total_failed}, пусто: {total_empty}'
            else:
                s['message'] = 'Нет учётных данных'
            s['next_run'] = s['last_run'] + timedelta(seconds=activity_sync_interval)
        logger.info("Activity sync: итого — synced=%d, empty=%d, failed=%d", total_synced, total_empty, total_failed)
    except Exception as e:
        logger.exception("Activity sync: глобальная ошибка")
        with _auto_sync_status_lock:
            s = _auto_sync_status['activity']
            s['status'] = 'error'
            s['last_run'] = datetime.now(timezone.utc)
            s['message'] = str(e)[:80]
            s['next_run'] = s['last_run'] + timedelta(seconds=activity_sync_interval)