# Роуты для синхронизации Coros (Coros sync routes: activities, health, status)

import os
import json
import tempfile
import uuid
import threading
from datetime import timedelta, date, datetime
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from src.models import SessionLocal, get_db, User, TrainingSession, DailyMetrics, DeletedTraining
from src.parsers.fit_parser import parse_fit
from src.parsers.common import format_pace, format_duration
from src.logger import get_logger
from src.crypto import decrypt
from src.api.deps import get_current_user
from src.services.audit import AuditService
from src.web.state import _pending, _sync_tasks, _sync_tasks_lock
from src.services.coros_sync_auto import update_last_health_sync

logger = get_logger("app")
router = APIRouter()


@router.post('/coros/sync')
async def coros_sync(db: Session = Depends(get_db),
                     current_user: User = Depends(get_current_user)):
    from src.coros_client import CorosClient, CorosAuthError, CorosAPIError
    from src.models import User

    us = db.query(User).filter(User.id == current_user.id).first()
    if not us or not us.coros_email or not us.coros_password:
        return JSONResponse({'status': 'error', 'message': 'Coros credentials not configured.'})

    task_id = str(uuid.uuid4())
    progress = {
        'task_id': task_id, 'step': 'queued', 'message': 'В очереди...',
        'total': 0, 'current': 0, 'synced': 0, 'errors': [], 'total_found': 0, 'done': False,
    }
    with _sync_tasks_lock:
        _sync_tasks[task_id] = progress

    def _run():
        db = SessionLocal()
        audit = AuditService(db)
        try:
            us = db.query(User).filter(User.id == current_user.id).first()
            progress['step'] = 'auth'
            progress['message'] = 'Подключение к Coros...'
            logger.info("Запуск синхронизации Coros (Coros sync started)")
            audit.log_coros_sync_started(
                user_id=us.id,
                email=us.coros_email,
                source="web_coros_sync",
            )
            try:
                plain_password = decrypt(us.coros_password)
            except Exception:
                logger.warning("Не удалось расшифровать пароль Coros, используется как есть (plaintext fallback)")
                plain_password = us.coros_password
            client = CorosClient(us.coros_email, plain_password, timeout=15)
            client.authenticate()
            logger.info("Аутентификация Coros пройдена (Coros auth successful)")

            progress['step'] = 'fetch'
            progress['message'] = 'Получение списка активностей...'
            activities = client.list_activities(limit=50, since=None)
            progress['total_found'] = len(activities)
            logger.info("Получено активностей из Coros: %d", len(activities))

            if not activities:
                progress['step'] = 'done'
                progress['message'] = 'Нет новых беговых активностей'
                progress['done'] = True
                logger.info("Синхронизация Coros: нет беговых активностей")
                return

            existing_times = {r[0] for r in db.query(TrainingSession.begin_ts).filter(TrainingSession.user_id == current_user.id).all()}

            def already_imported(ts):
                for et in existing_times:
                    if et is not None and abs((et - ts).total_seconds()) < 120:
                        return True
                return False

            new_acts = [a for a in activities if not already_imported(a['start_time'])]
            if not new_acts:
                for a in activities:
                    if us.last_coros_sync is None or a['start_time'] > us.last_coros_sync:
                        us.last_coros_sync = a['start_time']
                if us.last_coros_sync:
                    db.commit()
                    logger.info("Синхронизация Coros: last_coros_sync обновлён: %s", us.last_coros_sync)
                progress['step'] = 'done'
                progress['message'] = 'Все активности уже импортированы'
                progress['total'] = 0
                progress['done'] = True
                logger.info("Синхронизация Coros: все активности уже в БД")
                return

            progress['total'] = len(new_acts)
            synced = 0
            max_act_ts = us.last_coros_sync
            latest_ts = us.last_coros_sync

            for i, act in enumerate(new_acts):
                progress['step'] = 'download'
                progress['current'] = i + 1
                progress['message'] = f'Скачивание {i+1}/{len(new_acts)}: {act["name"]}'
                logger.info("Загрузка новой активности: %s (%s)", act['name'], act['start_time'])

                tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.fit')
                tmp.close()
                try:
                    ok = client.download_fit(act['id'], act['sport_type'], tmp.name)
                    if not ok:
                        logger.warning("Не удалось скачать FIT для %s", act['name'])
                        progress['errors'].append(f"{act['name']}: download failed")
                        os.unlink(tmp.name)
                        continue

                    progress['step'] = 'parse'
                    progress['message'] = f'Обработка {i+1}/{len(new_acts)}: {act["name"]}'
                    data = parse_fit(tmp.name, max_hr=us.max_hr,
                                     max_credible_pace=us.max_credible_pace,
                                     max_gps_jump_m=us.max_gps_jump_m,
                                     min_hr_for_fast_pace=us.min_hr_for_fast_pace)
                    if data is None:
                        logger.warning("Не удалось распарсить FIT для %s", act['name'])
                        progress['errors'].append(f"{act['name']}: parse failed")
                        os.unlink(tmp.name)
                        continue

                    bt_sync = data.get('begin_ts')
                    deleted_match_sync = None
                    if bt_sync:
                        all_del = db.query(DeletedTraining).filter(DeletedTraining.user_id == current_user.id).all()
                        for d in all_del:
                            if d.begin_ts and abs((d.begin_ts - bt_sync).total_seconds()) < 120:
                                deleted_match_sync = d
                                break
                    if deleted_match_sync:
                        tid = str(uuid.uuid4())
                        _pending[tid] = {'path': tmp.name, 'filename': act['name'], 'data': data}
                        pace_str_s = format_pace(deleted_match_sync.avg_pace) if deleted_match_sync.avg_pace else '—'
                        dur_s = format_duration(deleted_match_sync.duration_minutes) if deleted_match_sync.duration_minutes else '—'
                        pending_info = {
                            'temp_id': tid,
                            'date': deleted_match_sync.begin_ts.strftime('%d.%m.%Y %H:%M'),
                            'distance': round(deleted_match_sync.total_distance_km, 1) if deleted_match_sync.total_distance_km else '—',
                            'distance_display': f'{deleted_match_sync.total_distance_km:.1f} км' if deleted_match_sync.total_distance_km else '—',
                            'pace': pace_str_s,
                            'duration': dur_s,
                            'type': deleted_match_sync.training_type or '—',
                            'hr': f'{deleted_match_sync.avg_heart_rate}' if deleted_match_sync.avg_heart_rate else '—',
                            'calories': f'{deleted_match_sync.calories}' if deleted_match_sync.calories else '—',
                        }
                        if 'pending_deleted' not in progress:
                            progress['pending_deleted'] = []
                            progress['has_pending_deleted'] = True
                        progress['pending_deleted'].append(pending_info)
                        logger.info("Найдена ранее удалённая тренировка %s (%s) — ожидает подтверждения (Deleted training found, awaiting confirmation)", act['name'], bt_sync)
                        continue

                    cleaning_log = data.pop('cleaning_log', None)
                    flags_val = data.pop('suspect_flags', None)
                    if data.get('training_type') in ('invalid', None):
                        logger.warning("Некорректные данные для %s", act['name'])
                        progress['errors'].append(f"{act['name']}: invalid data")
                        os.unlink(tmp.name)
                        continue

                    session = TrainingSession(**data)
                    if cleaning_log:
                        session.cleaning_log = cleaning_log
                    if flags_val:
                        session.suspect_flags = flags_val
                    tz = data.get('timezone')
                    if tz and not us.timezone:
                        us.timezone = tz
                    db.add(session)
                    db.commit()
                    db.refresh(session)
                    synced += 1
                    progress['synced'] = synced
                    logger.info("Активность сохранена: %s (%s)", act['name'], act['start_time'])
                    audit.log_training_uploaded(
                        user_id=us.id,
                        training_id=session.id,
                        filename=act['name'],
                        distance_km=session.total_distance_km,
                        training_type=session.training_type,
                        source="coros_sync",
                    )
                    if latest_ts is None or act['start_time'] > latest_ts:
                        latest_ts = act['start_time']
                except Exception as e:
                    logger.exception("Ошибка при обработке %s", act['name'])
                    progress['errors'].append(f"{act['name']}: {str(e)}")
                finally:
                    if os.path.exists(tmp.name):
                        os.unlink(tmp.name)
                if max_act_ts is None or act['start_time'] > max_act_ts:
                    max_act_ts = act['start_time']

            if max_act_ts is not None and (us.last_coros_sync is None or max_act_ts > us.last_coros_sync):
                us.last_coros_sync = max_act_ts
                db.commit()
                logger.info("last_coros_sync обновлён: %s", max_act_ts)

            logger.info("Синхронизация Coros завершена: synced=%d, errors=%d", synced, len(progress['errors']))
            progress['step'] = 'done'
            progress['message'] = f'Синхронизировано: {synced}'
            progress['done'] = True
            audit.log_coros_sync_completed(
                user_id=us.id,
                email=us.coros_email,
                trainings_synced=synced,
                health_synced=0,
                source="web_coros_sync",
            )
        except CorosAuthError as e:
            progress['step'] = 'error'
            progress['message'] = f'Ошибка аутентификации Coros: {e}'
            progress['done'] = True
            logger.error("Coros auth error: %s", e)
            audit.log_coros_sync_failed(user_id=us.id, email=us.coros_email, error=str(e), source="web_coros_sync")
        except CorosAPIError as e:
            progress['step'] = 'error'
            progress['message'] = f'Ошибка Coros API: {e}'
            progress['done'] = True
            logger.error("Coros API error: %s", e)
            audit.log_coros_sync_failed(user_id=us.id, email=us.coros_email, error=str(e), source="web_coros_sync")
        except Exception as e:
            if 'Timeout' in type(e).__name__:
                progress['message'] = 'Таймаут подключения к Coros'
            elif 'ConnectionError' in type(e).__name__:
                progress['message'] = 'Не удалось подключиться к Coros'
            else:
                progress['message'] = f'Ошибка: {type(e).__name__}: {e}'
            progress['step'] = 'error'
            progress['done'] = True
            logger.error("Coros sync error", exc_info=True)
            audit.log_coros_sync_failed(user_id=us.id, email=us.coros_email, error=str(e), source="web_coros_sync")
        finally:
            db.close()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return JSONResponse({'task_id': task_id, 'status': 'started'})


@router.get('/coros/sync/status/{task_id}')
async def coros_sync_status(task_id: str):
    with _sync_tasks_lock:
        p = _sync_tasks.get(task_id)
    if not p:
        return JSONResponse({'status': 'error', 'message': 'Task not found'})
    return JSONResponse(p)


@router.post('/coros/sync/health')
async def coros_sync_health(db: Session = Depends(get_db),
                            current_user: User = Depends(get_current_user)):
    from src.coros_client import CorosClient, CorosAuthError, CorosAPIError
    from src.models import User

    us = db.query(User).filter(User.id == current_user.id).first()
    if not us or not us.coros_email or not us.coros_password:
        return JSONResponse({'status': 'error', 'message': 'Coros credentials not configured.'})

    task_id = str(uuid.uuid4())
    progress = {
        'task_id': task_id, 'step': 'queued', 'message': 'В очереди...',
        'total': 0, 'current': 0, 'synced': 0, 'errors': [], 'done': False,
    }
    with _sync_tasks_lock:
        _sync_tasks[task_id] = progress

    def _run():
        db = SessionLocal()
        audit = AuditService(db)
        try:
            us = db.query(User).filter(User.id == current_user.id).first()
            progress['step'] = 'auth'
            progress['message'] = 'Подключение к Coros...'
            logger.info("Запуск синхронизации метрик здоровья Coros (Coros health sync started)")
            audit.log_coros_sync_started(
                user_id=us.id,
                email=us.coros_email,
                source="web_coros_sync_health",
            )
            try:
                plain_password = decrypt(us.coros_password)
            except Exception:
                plain_password = us.coros_password
            client = CorosClient(us.coros_email, plain_password, timeout=15)
            client.authenticate()
            logger.info("Аутентификация Coros пройдена")

            progress['step'] = 'fetch'
            progress['message'] = 'Получение дневных метрик...'

            existing_dates = {r[0] for r in db.query(DailyMetrics.date).filter(DailyMetrics.user_id == current_user.id).all()}
            today = date.today()
            start_day = (today - timedelta(days=120)).strftime("%Y%m%d")
            end_day = today.strftime("%Y%m%d")

            metrics_list = client.get_daily_metrics(start_day, end_day)
            progress['total_found'] = len(metrics_list)
            logger.info("Получено дневных метрик из Coros: %d", len(metrics_list))

            if not metrics_list:
                progress['step'] = 'done'
                progress['message'] = 'Нет данных о восстановлении'
                progress['done'] = True
                return

            analytics_by_date = {}
            try:
                analytics_list = client.get_analytics()
                logger.info("Получено записей аналитики из Coros: %d", len(analytics_list))
                for a in analytics_list:
                    ad = a.get('happenDay')
                    if ad:
                        try:
                            d = datetime.strptime(str(ad), "%Y%m%d").date()
                            analytics_by_date[d] = a
                        except (ValueError, TypeError):
                            pass
            except Exception as e:
                logger.warning("Не удалось получить аналитику Coros: %s", e)

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
                    logger.debug("Пропуск: дата %s уже есть в БД", entry_date)
                    continue

                ana = analytics_by_date.get(entry_date, {})
                dm = DailyMetrics(
                    user_id=current_user.id,
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
                progress['synced'] = synced
                progress['message'] = f'Синхронизировано: {synced}/{len(metrics_list)}'
                logger.info("Сохранены метрики за %s (HRV=%s, RHR=%s)", happen_day,
                            entry.get('avgSleepHrv'), entry.get('rhr'))

            db.commit()
            logger.info("Синхронизация метрик Coros завершена: synced=%d", synced)

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
                    logger.info("Обновлено аналитикой записей: %d", updated)

            progress['step'] = 'done'
            progress['message'] = f'Синхронизировано: {synced}'
            progress['done'] = True
            audit.log_coros_sync_completed(
                user_id=us.id,
                email=us.coros_email,
                trainings_synced=0,
                health_synced=synced,
                source="web_coros_sync_health",
            )

        except CorosAuthError as e:
            progress['step'] = 'error'
            progress['message'] = f'Ошибка аутентификации Coros: {e}'
            progress['done'] = True
            logger.error("Coros auth error: %s", e)
            audit.log_coros_sync_failed(user_id=us.id, email=us.coros_email, error=str(e), source="web_coros_sync_health")
        except CorosAPIError as e:
            progress['step'] = 'error'
            progress['message'] = f'Ошибка Coros API: {e}'
            progress['done'] = True
            logger.error("Coros API error: %s", e)
            audit.log_coros_sync_failed(user_id=us.id, email=us.coros_email, error=str(e), source="web_coros_sync_health")
        except Exception as e:
            progress['step'] = 'error'
            progress['message'] = f'Ошибка: {type(e).__name__}: {e}'
            progress['done'] = True
            logger.error("Coros health sync error", exc_info=True)
            audit.log_coros_sync_failed(user_id=us.id, email=us.coros_email, error=str(e), source="web_coros_sync_health")
        finally:
            db.close()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return JSONResponse({'task_id': task_id, 'status': 'started'})
