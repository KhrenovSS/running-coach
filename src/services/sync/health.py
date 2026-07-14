# Синхронизация метрик здоровья (Health metrics sync)

import json
from datetime import timedelta, date, datetime, timezone

from src.utils.logger import get_logger
from src.models import SessionLocal, DailyMetrics
from src.services.sync.utils import _make_client
from src.watch import BaseWatchClient

logger = get_logger("app")


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
async def sync_health_for_user(cred, brand: str,
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

        # Fill analytics gaps / Заполнение пробелов аналитики
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
