# Синхронизация тренировок (Activity sync)

import os
import tempfile
from datetime import timedelta, datetime, timezone

from src.utils.logger import get_logger
from src.models import SessionLocal, User, TrainingSession, DeletedTraining
from src.services.audit import AuditService
from src.services.sync.utils import _make_client
from src.services.telegram_notify import telegram_notify

logger = get_logger("app")


# Синхронизация тренировок для пользователя (Sync activities for a user)
async def sync_activities_for_user(cred, brand: str,
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
