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
def save_dashboard_data(client: BaseWatchClient, db, user_id: int, brand: str):
    try:
        dashboard = client.get_dashboard()
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
        return -1

    db = SessionLocal()
    try:
        existing_dates = {r[0] for r in db.query(DailyMetrics.date).filter(DailyMetrics.user_id == cred.user_id).all()}
        today = date.today()
        start_day = (today - timedelta(days=120)).strftime("%Y%m%d")
        end_day = today.strftime("%Y%m%d")

        metrics_list = await client.get_daily_metrics(start_day, end_day)
        logger.info("Health sync for brand=%s user=%s: got %d records", brand, cred.user_id, len(metrics_list))
        if not metrics_list:
            save_dashboard_data(client, db, cred.user_id, brand)
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

        save_dashboard_data(client, db, cred.user_id, brand)
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
        return -1

    db = SessionLocal()
    try:
        us = db.query(User).filter(User.id == cred.user_id).first()
        if not us:
            return -1

        # Буфер 2ч чтобы не пропустить активности, которые Coros обработал с задержкой (2h lookback buffer to catch delayed Coros activities)
        since = cred.last_activity_sync_at - timedelta(hours=2) if cred.last_activity_sync_at else None
        activities = await client.list_activities(since=since)
        if not activities:
            return 0

        existing_begin = {r[0] for r in db.query(TrainingSession.begin_ts).filter(TrainingSession.user_id == cred.user_id).all()}
        all_deleted = db.query(DeletedTraining).filter(DeletedTraining.user_id == cred.user_id).all()

        synced = 0
        for act in activities:
            bt = act.get('start_time')
            if not bt:
                continue
            if bt in existing_begin:
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
            # Update last_activity_sync_at
            cred.last_activity_sync_at = datetime.now(timezone.utc)
            db.commit()

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

        total_synced = 0
        total_empty = 0
        for cred in credentials:
            result = asyncio.run(sync_health_for_user(cred, cred.brand))
            if result > 0:
                total_synced += result
            elif result == 0:
                total_empty += 1

        with _auto_sync_status_lock:
            s = _auto_sync_status['health']
            s['status'] = 'ok'
            s['last_run'] = datetime.now(timezone.utc)
            if total_synced > 0:
                s['message'] = f'✓ Синхронизировано: {total_synced}'
            elif total_empty > 0:
                s['message'] = '🟡 Синхронизация прошла, но данных о сне нет'
            else:
                s['message'] = 'Нет учётных данных'
            s['next_run'] = s['last_run'] + timedelta(seconds=health_sync_interval)
    except Exception as e:
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

        total_synced = 0
        total_empty = 0
        for cred in credentials:
            result = asyncio.run(sync_activities_for_user(cred, cred.brand))
            if result > 0:
                total_synced += result
            elif result == 0:
                total_empty += 1

        with _auto_sync_status_lock:
            s = _auto_sync_status['activity']
            s['status'] = 'ok'
            s['last_run'] = datetime.now(timezone.utc)
            if total_synced > 0:
                s['message'] = f'✓ Синхронизировано: {total_synced}'
            elif total_empty > 0:
                s['message'] = '🟡 Синхронизация прошла, но новых тренировок нет'
            else:
                s['message'] = 'Нет учётных данных'
            s['next_run'] = s['last_run'] + timedelta(seconds=activity_sync_interval)
    except Exception as e:
        with _auto_sync_status_lock:
            s = _auto_sync_status['activity']
            s['status'] = 'error'
            s['last_run'] = datetime.now(timezone.utc)
            s['message'] = str(e)[:80]
            s['next_run'] = s['last_run'] + timedelta(seconds=activity_sync_interval)