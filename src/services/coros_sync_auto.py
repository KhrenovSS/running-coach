# Фоновая автосинхронизация Coros (Background Coros auto-sync)

import json
import os
import threading
from datetime import timedelta, date, datetime, timezone
from src.logger import get_logger
from src.services.audit import AuditService
from src.crypto import encrypt, decrypt
from src.models import SessionLocal, User, DailyMetrics
from src.coros_client import CorosClient, CorosAuthError, CorosAPIError

logger = get_logger("app")


# Статус автосинхронизации (Auto-sync status tracking)
_auto_sync_status = {
    'health': {'last_run': None, 'status': 'idle', 'message': '', 'next_run': None},
    'activity': {'last_run': None, 'status': 'idle', 'message': '', 'next_run': None},
}
_auto_sync_status_lock = threading.Lock()

# Интервалы синхронизации из переменных окружения (с квотер-джиттером)
health_sync_interval = int(os.getenv("COROS_HEALTH_SYNC_INTERVAL", "21600"))  # 6 часов
activity_sync_interval = int(os.getenv("COROS_ACTIVITY_SYNC_INTERVAL", "3600"))  # 1 час


# Сохраняет время последней синхронизации здоровья в БД (Save last health sync attempt time to DB)
def update_last_health_sync(user_id: int):
    try:
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                user.last_health_sync_at = datetime.now(timezone.utc)
                db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.warning("Не удалось обновить last_health_sync_at: %s", e)


# Сохраняет dashboard данные Coros в today's запись DailyMetrics (Save Coros dashboard data to today's DailyMetrics)
def save_dashboard_data(client, db, user_id: int):
    try:
        dashboard = client.get_dashboard()
        if not dashboard:
            logger.warning("Dashboard: пустой ответ (endpoint вернул пустые данные)")
            return
        logger.info("Dashboard данные: %s", dashboard)
        info = dashboard.get('summaryInfo')
        if not info:
            logger.debug("Dashboard: нет summaryInfo")
            return
        today = date.today()
        dm = db.query(DailyMetrics).filter(
            DailyMetrics.user_id == user_id,
            DailyMetrics.date == today
        ).first()
        if not dm:
            dm = DailyMetrics(user_id=user_id, date=today)
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
        db.commit()
    except Exception as e:
        logger.warning("Ошибка сохранения dashboard: %s", e)


# Синхронизация метрик здоровья (авто, без прогресса) (Auto health metrics sync)
def auto_sync_health():
    from datetime import timedelta, datetime
    with _auto_sync_status_lock:
        _auto_sync_status['health']['status'] = 'syncing'
        _auto_sync_status['health']['message'] = 'Синхронизация...'
    try:
        db = SessionLocal()
        try:
            users = db.query(User).filter(
                User.coros_email.isnot(None),
                User.coros_password.isnot(None),
                (User.is_active == True) | (User.is_active.is_(None)),
            ).all()
        finally:
            db.close()

        total_synced = 0
        total_empty = 0
        for user in users:
            result = auto_sync_health_inner(user.id)
            update_last_health_sync(user.id)
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
                s['message'] = '🟡 Синхронизация прошла, но данных о сне нет — возможно часы не синхронизированы с приложением'
            else:
                s['message'] = 'Нет учётных данных Coros'
            s['next_run'] = s['last_run'] + timedelta(seconds=health_sync_interval)
    except Exception as e:
        with _auto_sync_status_lock:
            s = _auto_sync_status['health']
            s['status'] = 'error'
            s['last_run'] = datetime.now(timezone.utc)
            s['message'] = str(e)[:80]
            s['next_run'] = s['last_run'] + timedelta(seconds=health_sync_interval)


def auto_sync_health_inner(user_id: int) -> int:
    """Возвращает количество новых синхронизированных записей (Return count of new synced records)"""
    db = SessionLocal()
    try:
        us = db.query(User).filter(User.id == user_id).first()
        if not us or not us.coros_email or not us.coros_password:
            logger.debug("Автосинхронизация здоровья: нет учётных данных Coros")
            return -1
        try:
            plain_password = decrypt(us.coros_password)
        except Exception:
            plain_password = us.coros_password
        client = CorosClient(us.coros_email, plain_password, timeout=15)
        client.authenticate()

        existing_dates = {r[0] for r in db.query(DailyMetrics.date).filter(DailyMetrics.user_id == user_id).all()}
        today = date.today()
        start_day = (today - timedelta(days=120)).strftime("%Y%m%d")
        end_day = today.strftime("%Y%m%d")

        metrics_list = client.get_daily_metrics(start_day, end_day)
        logger.info("Автосинхронизация здоровья: получено %d записей из Coros", len(metrics_list))
        if not metrics_list:
            save_dashboard_data(client, db, user_id)
            return 0

        analytics_by_date = {}
        try:
            analytics_list = client.get_analytics()
            for a in analytics_list:
                ad = a.get('happenDay')
                if ad:
                    try:
                        d = datetime.strptime(str(ad), "%Y%m%d").date()
                        analytics_by_date[d] = a
                    except (ValueError, TypeError):
                        pass
        except Exception as e:
            logger.warning("Автосинхронизация: не удалось получить аналитику Coros: %s", e)

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
                user_id=user_id,
                date=entry_date,
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
            logger.info("Автосинхронизация здоровья: synced=%d", synced)
        else:
            logger.info("Автосинхронизация здоровья: новых записей нет")

        if analytics_by_date:
            updated = 0
            for entry_date, ana in analytics_by_date.items():
                existing = db.query(DailyMetrics).filter(DailyMetrics.user_id == user_id, DailyMetrics.date == entry_date).first()
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
                logger.info("Автосинхронизация: обновлено аналитикой %d записей", updated)
        save_dashboard_data(client, db, user_id)
        return synced
    except CorosAuthError as e:
        logger.warning("Автосинхронизация здоровья: ошибка аутентификации: %s", e)
        return 0
    except CorosAPIError as e:
        logger.warning("Автосинхронизация здоровья: ошибка Coros API: %s", e)
        return 0
    except Exception:
        logger.exception("Автосинхронизация здоровья: неожиданная ошибка")
        return 0
    finally:
        db.close()


# Синхронизация активностей (авто, без прогресса) (Auto activity sync)
def auto_sync_activities():
    from datetime import timedelta, datetime
    with _auto_sync_status_lock:
        _auto_sync_status['activity']['status'] = 'syncing'
        _auto_sync_status['activity']['message'] = 'Синхронизация...'
    try:
        db = SessionLocal()
        try:
            users = db.query(User).filter(
                User.coros_email.isnot(None),
                User.coros_password.isnot(None),
                (User.is_active == True) | (User.is_active.is_(None)),
            ).all()
        finally:
            db.close()

        total_synced = 0
        total_empty = 0
        for user in users:
            result = auto_sync_activities_inner(user.id)
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
                s['message'] = 'Нет учётных данных Coros'
            s['next_run'] = s['last_run'] + timedelta(seconds=activity_sync_interval)
    except Exception as e:
        with _auto_sync_status_lock:
            s = _auto_sync_status['activity']
            s['status'] = 'error'
            s['last_run'] = datetime.now(timezone.utc)
            s['message'] = str(e)[:80]
            s['next_run'] = s['last_run'] + timedelta(seconds=activity_sync_interval)


def auto_sync_activities_inner(user_id: int) -> int:
    """Возвращает количество новых синхронизированных тренировок (Return count of synced activities)"""
    from src.parsers.fit_parser import parse_fit
    from src.models import TrainingSession, DeletedTraining, get_settings

    db = SessionLocal()
    try:
        us = db.query(User).filter(User.id == user_id).first()
        if not us or not us.coros_email or not us.coros_password:
            logger.debug("Автосинхронизация активностей: нет учётных данных Coros")
            return -1
        try:
            plain_password = decrypt(us.coros_password)
        except Exception:
            plain_password = us.coros_password
        client = CorosClient(us.coros_email, plain_password, timeout=30)
        client.authenticate()

        activities = client.list_activities()
        if not activities:
            logger.debug("Автосинхронизация активностей: нет активностей")
            return 0

        settings = get_settings()
        existing_begin = {r[0] for r in db.query(TrainingSession.begin_ts).filter(TrainingSession.user_id == user_id).all()}
        all_deleted = db.query(DeletedTraining).filter(DeletedTraining.user_id == user_id).all()

        synced = 0
        for act in activities:
            begin_ts = act.get('beginTs')
            if not begin_ts:
                continue
            try:
                from datetime import datetime as dt_cls
                bt = dt_cls.strptime(str(begin_ts)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc) if 'T' in str(begin_ts) else dt_cls.strptime(str(begin_ts)[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                try:
                    from datetime import datetime as dt_cls
                    bt = dt_cls.strptime(str(begin_ts)[:16], "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    continue

            if bt in existing_begin:
                continue

            file_url = act.get('fileUrl')
            if not file_url:
                continue

            try:
                fit_data = client.download_activity(file_url)
            except Exception as e:
                logger.warning("Автосинхронизация: ошибка скачивания активности: %s", e)
                continue

            if not fit_data:
                continue

            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix=".fit") as tmp:
                tmp.write(fit_data)
                tmp_path = tmp.name

            try:
                data = parse_fit(tmp_path, max_hr=settings.max_hr,
                                 max_credible_pace=settings.max_credible_pace,
                                 max_gps_jump_m=settings.max_gps_jump_m,
                                 min_hr_for_fast_pace=settings.min_hr_for_fast_pace)
            except Exception:
                os.unlink(tmp_path)
                continue
            os.unlink(tmp_path)

            if not data:
                continue

            # Проверка на ранее удалённые тренировки
            deleted_match = None
            for d in all_deleted:
                if d.begin_ts and abs((d.begin_ts - bt).total_seconds()) < 120:
                    deleted_match = d
                    break
            if deleted_match:
                logger.info("Автосинхронизация: пропуск ранее удалённой тренировки %s", bt)
                continue

            session = TrainingSession(**data)
            session.user_id = user_id
            tz = data.get('timezone')
            if tz and not us.timezone:
                us.timezone = tz
            db.add(session)
            synced += 1

        if synced:
            db.commit()
            logger.info("Автосинхронизация активностей: synced=%d", synced)
        else:
            logger.info("Автосинхронизация активностей: новых тренировок нет")
        return synced
    except CorosAuthError as e:
        logger.warning("Автосинхронизация активностей: ошибка аутентификации: %s", e)
        return 0
    except CorosAPIError as e:
        logger.warning("Автосинхронизация активностей: ошибка Coros API: %s", e)
        return 0
    except Exception:
        logger.exception("Автосинхронизация активностей: неожиданная ошибка")
        return 0
    finally:
        db.close()
