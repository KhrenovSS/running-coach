# Brand-agnostic роуты синхронизации (Brand-agnostic sync routes: activities, health, status)

import os
import json
import tempfile
import uuid
import threading
from datetime import timedelta, date, datetime, timezone
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from src.models import SessionLocal, get_db, User, TrainingSession, DailyMetrics, DeletedTraining, WatchCredential
from src.parsers.fit_parser import parse_fit
from src.parsers.utils import format_pace, format_duration
from src.utils.logger import get_logger
from src.crypto import decrypt
from src.api.deps import get_current_user
from src.services.audit import AuditService
from src.web.state import _pending, _sync_tasks, _sync_tasks_lock
from src.watch import get_watch_client, list_brands

logger = get_logger("app")
router = APIRouter()


@router.post('/sync/{brand}/run')
async def sync_run(brand: str, db: Session = Depends(get_db),
                   current_user: User = Depends(get_current_user)):
    brand = brand.lower()
    # Check credential exists
    cred = db.query(WatchCredential).filter(
        WatchCredential.user_id == current_user.id,
        WatchCredential.brand == brand,
        WatchCredential.is_active == True,
    ).first()
    if not cred or not cred.encrypted_password:
        return JSONResponse({'status': 'error', 'message': f'{brand.capitalize()} credentials not configured.'})

    task_id = str(uuid.uuid4())
    progress = {
        'task_id': task_id, 'step': 'queued', 'message': 'В очереди...',
        'total': 0, 'current': 0, 'synced': 0, 'errors': [], 'total_found': 0, 'done': False,
    }
    with _sync_tasks_lock:
        _sync_tasks[task_id] = progress

    def _run():
        import asyncio
        db = SessionLocal()
        audit = AuditService(db)
        try:
            cred = db.query(WatchCredential).filter(
                WatchCredential.user_id == current_user.id,
                WatchCredential.brand == brand,
            ).first()
            us = db.query(User).filter(User.id == current_user.id).first()
            progress['step'] = 'auth'
            progress['message'] = f'Подключение к {brand.capitalize()}...'
            logger.info("Sync started for brand=%s user=%s", brand, current_user.id)
            audit.log_sync_started(brand=brand, user_id=us.id, source=f"web_{brand}_sync")

            plain_password = decrypt(cred.encrypted_password) if cred.encrypted_password else ''
            if not plain_password:
                progress['step'] = 'error'
                progress['message'] = 'Пароль не расшифрован'
                progress['done'] = True
                return

            client = get_watch_client(brand, email=cred.encrypted_user, password=plain_password, timeout=15)
            if not client:
                progress['step'] = 'error'
                progress['message'] = f'Бренд {brand} не поддерживается'
                progress['done'] = True
                return

            try:
                # For async client, run in a new event loop
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(client.authenticate())
            except Exception as e:
                progress['step'] = 'error'
                progress['message'] = f'Ошибка аутентификации {brand.capitalize()}: {e}'
                progress['done'] = True
                logger.error("Auth error for brand=%s: %s", brand, e)
                audit.log_sync_failed(brand=brand, user_id=us.id, error=str(e), source=f"web_{brand}_sync")
                return

            progress['step'] = 'fetch'
            progress['message'] = f'Получение списка активностей из {brand.capitalize()}...'
            try:
                activities = loop.run_until_complete(client.list_activities(since=None))
            except Exception as e:
                progress['step'] = 'error'
                progress['message'] = f'Ошибка получения активностей: {e}'
                progress['done'] = True
                audit.log_sync_failed(brand=brand, user_id=us.id, error=str(e), source=f"web_{brand}_sync")
                loop.close()
                return

            progress['total_found'] = len(activities)
            logger.info("Получено активностей из %s: %d", brand, len(activities))

            if not activities:
                progress['step'] = 'done'
                progress['message'] = 'Нет новых беговых активностей'
                progress['done'] = True
                audit.log_sync_completed(brand=brand, user_id=us.id, found=0, processed=0, source=f"web_{brand}_sync")
                loop.close()
                return

            existing_times = {r[0] for r in db.query(TrainingSession.begin_ts).filter(TrainingSession.user_id == current_user.id).all()}

            def already_imported(ts):
                for et in existing_times:
                    if et is not None and abs((et - ts).total_seconds()) < 120:
                        return True
                return False

            new_acts = [a for a in activities if not already_imported(a['start_time'])]
            if not new_acts:
                progress['step'] = 'done'
                progress['message'] = 'Все активности уже импортированы'
                progress['total'] = 0
                progress['done'] = True
                audit.log_sync_completed(brand=brand, user_id=us.id, found=len(activities), processed=0, source=f"web_{brand}_sync")
                loop.close()
                return

            progress['total'] = len(new_acts)
            synced = 0

            for i, act in enumerate(new_acts):
                progress['step'] = 'download'
                progress['current'] = i + 1
                progress['message'] = f'Скачивание {i+1}/{len(new_acts)}: {act.get("name", "activity")}'

                try:
                    fit_data = loop.run_until_complete(client.download_activity(act['id'], act['sport_type']))
                except Exception as e:
                    logger.warning("Download error for %s: %s", act.get('name'), e)
                    progress['errors'].append(f"{act.get('name', '?')}: download failed")
                    continue

                if not fit_data:
                    progress['errors'].append(f"{act.get('name', '?')}: download failed (empty)")
                    continue

                tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.fit')
                tmp.write(fit_data)
                tmp.close()

                try:
                    progress['step'] = 'parse'
                    progress['message'] = f'Обработка {i+1}/{len(new_acts)}: {act.get("name", "activity")}'
                    data = parse_fit(tmp.name, max_hr=us.max_hr,
                                     max_credible_pace=us.max_credible_pace,
                                     max_gps_jump_m=us.max_gps_jump_m,
                                     min_hr_for_fast_pace=us.min_hr_for_fast_pace)
                    if data is None:
                        progress['errors'].append(f"{act.get('name', '?')}: parse failed")
                        os.unlink(tmp.name)
                        continue

                    # Check deleted
                    bt_sync = data.get('begin_ts')
                    deleted_match = None
                    if bt_sync:
                        all_del = db.query(DeletedTraining).filter(DeletedTraining.user_id == current_user.id).all()
                        for d in all_del:
                            if d.begin_ts and abs((d.begin_ts - bt_sync).total_seconds()) < 120:
                                deleted_match = d
                                break
                    if deleted_match:
                        tid = str(uuid.uuid4())
                        _pending[tid] = {'path': tmp.name, 'filename': act.get('name', 'activity'), 'data': data}
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

                    if data.get('training_type') in ('invalid', None):
                        progress['errors'].append(f"{act.get('name', '?')}: invalid data")
                        os.unlink(tmp.name)
                        continue

                    session = TrainingSession(**data)
                    session.user_id = current_user.id
                    tz = data.get('timezone')
                    if tz and not us.timezone:
                        us.timezone = tz
                    db.add(session)
                    db.commit()
                    db.refresh(session)
                    synced += 1
                    progress['synced'] = synced
                    audit.log_training_uploaded(user_id=us.id, training_id=session.id, filename=act.get('name', ''),
                                                distance_km=session.total_distance_km, training_type=session.training_type,
                                                source=f"{brand}_sync")
                except Exception as e:
                    logger.exception("Error processing %s", act.get('name'))
                    progress['errors'].append(f"{act.get('name', '?')}: {str(e)}")
                finally:
                    if os.path.exists(tmp.name):
                        os.unlink(tmp.name)

            # Update last activity sync
            cred.last_activity_sync_at = datetime.now(timezone.utc)
            db.commit()

            logger.info("Sync completed for brand=%s user=%s: synced=%d, errors=%d", brand, current_user.id, synced, len(progress['errors']))
            progress['step'] = 'done'
            progress['message'] = f'Синхронизировано: {synced}'
            progress['done'] = True
            audit.log_sync_completed(brand=brand, user_id=us.id, found=len(activities), processed=synced, source=f"web_{brand}_sync")
            loop.close()
        except Exception as e:
            progress['step'] = 'error'
            progress['message'] = f'Ошибка: {type(e).__name__}: {e}'
            progress['done'] = True
            logger.error("Sync error for brand=%s", brand, exc_info=True)
            audit.log_sync_failed(brand=brand, user_id=current_user.id, error=str(e), source=f"web_{brand}_sync")
        finally:
            db.close()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return JSONResponse({'task_id': task_id, 'status': 'started'})


@router.get('/sync/status/{task_id}')
async def sync_status(task_id: str):
    with _sync_tasks_lock:
        p = _sync_tasks.get(task_id)
    if not p:
        return JSONResponse({'status': 'error', 'message': 'Task not found'})
    return JSONResponse(p)


@router.post('/sync/{brand}/health')
async def sync_health(brand: str, db: Session = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    brand = brand.lower()
    cred = db.query(WatchCredential).filter(
        WatchCredential.user_id == current_user.id,
        WatchCredential.brand == brand,
        WatchCredential.is_active == True,
    ).first()
    if not cred or not cred.encrypted_password:
        return JSONResponse({'status': 'error', 'message': f'{brand.capitalize()} credentials not configured.'})

    task_id = str(uuid.uuid4())
    progress = {
        'task_id': task_id, 'step': 'queued', 'message': 'В очереди...',
        'total': 0, 'current': 0, 'synced': 0, 'errors': [], 'done': False,
    }
    with _sync_tasks_lock:
        _sync_tasks[task_id] = progress

    def _run():
        import asyncio
        db = SessionLocal()
        audit = AuditService(db)
        try:
            cred = db.query(WatchCredential).filter(
                WatchCredential.user_id == current_user.id,
                WatchCredential.brand == brand,
            ).first()
            us = db.query(User).filter(User.id == current_user.id).first()
            progress['step'] = 'auth'
            progress['message'] = f'Подключение к {brand.capitalize()}...'
            logger.info("Health sync started for brand=%s user=%s", brand, current_user.id)
            audit.log_sync_started(brand=brand, user_id=us.id, source=f"web_{brand}_sync_health")

            plain_password = decrypt(cred.encrypted_password) if cred.encrypted_password else ''
            if not plain_password:
                progress['step'] = 'error'
                progress['message'] = 'Пароль не расшифрован'
                progress['done'] = True
                return

            client = get_watch_client(brand, email=cred.encrypted_user, password=plain_password, timeout=15)
            if not client:
                progress['step'] = 'error'
                progress['message'] = f'Бренд {brand} не поддерживается'
                progress['done'] = True
                return

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(client.authenticate())

            progress['step'] = 'fetch'
            progress['message'] = 'Получение дневных метрик...'

            existing_dates = {r[0] for r in db.query(DailyMetrics.date).filter(DailyMetrics.user_id == current_user.id).all()}
            today = date.today()
            start_day = (today - timedelta(days=120)).strftime("%Y%m%d")
            end_day = today.strftime("%Y%m%d")

            metrics_list = loop.run_until_complete(client.get_daily_metrics(start_day, end_day))
            progress['total_found'] = len(metrics_list)
            logger.info("Health sync: got %d metric days from %s", len(metrics_list), brand)

            if not metrics_list:
                progress['step'] = 'done'
                progress['message'] = 'Нет данных о восстановлении'
                progress['done'] = True
                loop.close()
                return

            analytics_by_date = {}
            try:
                analytics_list = loop.run_until_complete(client.get_analytics())
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
            progress['total'] = len(metrics_list)

            for i, entry in enumerate(metrics_list):
                progress['current'] = i + 1
                happen_day = entry.get('happenDay')
                if not happen_day:
                    continue
                happen_day = str(happen_day)
                try:
                    entry_date = datetime.strptime(happen_day, "%Y%m%d").date()
                except (ValueError, TypeError):
                    try:
                        entry_date = datetime.strptime(happen_day, "%Y-%m-%d").date()
                    except (ValueError, TypeError):
                        continue

                if entry_date in existing_dates:
                    continue

                ana = analytics_by_date.get(entry_date, {})
                dm = DailyMetrics(
                    user_id=current_user.id,
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
                progress['synced'] = synced
                progress['message'] = f'Синхронизировано: {synced}/{len(metrics_list)}'

            db.commit()

            # Fill analytics gaps
            if analytics_by_date:
                updated = 0
                for entry_date, ana in analytics_by_date.items():
                    existing = db.query(DailyMetrics).filter(DailyMetrics.user_id == current_user.id, DailyMetrics.date == entry_date).first()
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

            # Update last health sync
            cred.last_health_sync_at = datetime.now(timezone.utc)
            db.commit()

            progress['step'] = 'done'
            progress['message'] = f'Синхронизировано: {synced}'
            progress['done'] = True
            audit.log_sync_completed(brand=brand, user_id=us.id, found=len(metrics_list), processed=synced, source=f"web_{brand}_sync_health")
            loop.close()
        except Exception as e:
            progress['step'] = 'error'
            progress['message'] = f'Ошибка: {type(e).__name__}: {e}'
            progress['done'] = True
            logger.error("Health sync error for brand=%s", brand, exc_info=True)
            audit.log_sync_failed(brand=brand, user_id=current_user.id, error=str(e), source=f"web_{brand}_sync_health")
        finally:
            db.close()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return JSONResponse({'task_id': task_id, 'status': 'started'})


# Обратная совместимость: старые /coros/sync роуты (Backward compat: old /coros/sync routes)
@router.post('/coros/sync')
async def coros_sync_redirect(db: Session = Depends(get_db),
                              current_user: User = Depends(get_current_user)):
    return await sync_run('coros', db=db, current_user=current_user)


@router.post('/coros/sync/health')
async def coros_sync_health_redirect(db: Session = Depends(get_db),
                                     current_user: User = Depends(get_current_user)):
    return await sync_health('coros', db=db, current_user=current_user)


@router.get('/coros/sync/status/{task_id}')
async def coros_sync_status_redirect(task_id: str):
    return await sync_status(task_id)