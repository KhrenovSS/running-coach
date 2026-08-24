# Синхронизация тренировок (Activity sync)

import os
import tempfile
import threading
from datetime import timedelta, datetime, timezone

from src.utils.logger import get_logger
from src.models import SessionLocal, User, TrainingSession, DeletedTraining
from src.services.audit import AuditService
from src.services.sync.utils import _make_client
from src.services.sync.dedup import load_dedup_state, is_duplicate, find_deleted_match
from src.services.raw_files import save_raw_file, sha256_hex
from src.services.telegram_notify import telegram_notify
from src.services.hr_max import evaluate_max_hr_raise
from src.exceptions import CoachError

logger = get_logger("app")


def _coach_reviews(user_id: int, trainings: list[dict]) -> None:
    """Разборы коуча после синка (post-sync coach reviews) — DEV_PLAN §9 C8.

    Живёт в daemon-треде: своя сессия (композиционный корень, гвард
    test_session_ownership). Гейт initiative: off → тишина; low →
    детерминированные карточки; normal/high → LLM-разбор, но только для
    самой свежей тренировки батча (батч ≈ бэкфилл: LLM по старым тратит
    бюджет и путает относительные даты).
    """
    def _ts(nt: dict) -> float:
        return nt["begin_ts"].timestamp() if nt.get("begin_ts") else float("-inf")

    db = SessionLocal()
    try:
        from src.coach import orchestrator as coach
        initiative = coach.get_initiative(user_id, db=db)
        if initiative == "off":
            return
        llm_allowed = initiative in ("normal", "high")
        latest_sid = max(trainings, key=_ts)["session_id"]
        for nt in sorted(trainings, key=_ts):
            review = coach.on_workout_completed(
                user_id, nt["session_id"], db=db,
                use_llm=llm_allowed and nt["session_id"] == latest_sid)
            telegram_notify(user_id=user_id, text=review)
    except CoachError as e:
        logger.error("Coach review failed (sync unaffected): %s", e)
    finally:
        db.close()


# Синхронизация тренировок для пользователя (Sync activities for a user)
async def sync_activities_for_user(cred, brand: str, db,
                                  progress: dict | None = None,
                                  pending: dict | None = None) -> int:
    """Возвращает количество новых синхронизированных тренировок (Return count of synced activities).

    db       — сессия ВЫЗЫВАЮЩЕГО кода (Этап 6, BACKLOG #231): не открываем и не закрываем.
    progress — dict для отслеживания прогресса (web UI); None для автосинхронизации.
    pending  — dict для кэширования pending-deleted тренировок (web UI); None для автосинхронизации.
    """
    from src.parsers.fit_parser import parse_fit
    from src.analysis.utils import format_pace, format_duration

    async def _download_parse(act):
        """Скачать FIT и распарсить; вернуть (data, fit_bytes) или (None, None)
        (Download+parse FIT; return (data, fit_bytes) or (None, None))."""
        fit_data = await client.download_activity(act['id'], act['sport_type'])
        if not fit_data:
            return None, None
        with tempfile.NamedTemporaryFile(delete=False, suffix=".fit") as tmp:
            tmp.write(fit_data)
            tmp_path = tmp.name
        try:
            data = parse_fit(tmp_path, max_hr=us.max_hr,
                             max_credible_pace=us.max_credible_pace,
                             max_gps_jump_m=us.max_gps_jump_m,
                             min_hr_for_fast_pace=us.min_hr_for_fast_pace,
                             coros_cadence_workaround=True)
            return data, fit_data
        except Exception:
            logger.warning("Parse error for %s", act.get('name'), exc_info=True)
            return None, None
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

        db_since = since - timedelta(days=1) if since else (datetime.now(timezone.utc) - timedelta(days=90))

        # Дедуп (BACKLOG #228): primary — внешний ID активности; окно по времени —
        # только fallback для legacy-строк без ID (Dedup: external id first, time window is legacy fallback)
        dedup_state = load_dedup_state(db, cred.user_id, brand, db_since)

        new_acts = [a for a in activities
                    if not is_duplicate(dedup_state, a.get('id'), a.get('start_time'))]

        # Фильтруем already-deleted, кэшируем в pending если предоставлен (Filter already-deleted, cache in pending if provided)
        acts_to_sync = []
        skipped_deleted = 0
        for act in new_acts:
            deleted_match = find_deleted_match(dedup_state, act.get('id'), act.get('start_time'))
            if deleted_match:
                skipped_deleted += 1
                if pending is not None:
                    # Скачиваем и парсим FIT, чтобы confirm_deleted мог восстановить (Download+parse FIT so confirm_deleted can restore)
                    data, fit_bytes = await _download_parse(act)
                    if data and data.get('training_type') not in ('invalid', None):
                        import uuid as _uuid
                        tid = str(_uuid.uuid4())
                        raw_path = save_raw_file(cred.user_id, fit_bytes, 'fit') if fit_bytes else None
                        pending[tid] = {
                            'path': '', 'filename': act.get('name', 'activity'),
                            'data': data,
                            # для точного дедупа при подтверждении восстановления (for exact dedup on confirm)
                            'external_activity_id': act.get('id'),
                            'source_brand': brand,
                            'sha256': sha256_hex(fit_bytes) if fit_bytes else None,
                            'raw_path': raw_path,
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

            data, fit_bytes = await _download_parse(act)
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
            # Стабильный ключ дедупа (BACKLOG #228): защищён частичным UNIQUE-индексом в БД
            session.external_activity_id = act.get('id')
            session.source_brand = brand
            dedup_state.ext_ids.add(act.get('id'))  # защита от дублей внутри одного батча (intra-batch guard)
            # Сырьё (BACKLOG #229): исходный FIT сохраняем — ошибка записи не роняет импорт
            if fit_bytes:
                session.file_sha256 = sha256_hex(fit_bytes)
                session.raw_file_path = save_raw_file(cred.user_id, fit_bytes, 'fit')
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
                'hr_peak': session.hr_peak_smoothed or session.max_heart_rate or 0,
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
            # Адаптивный max_hr: один вызов на батч по максимальному пику
            # (Adaptive max HR: one call per batch with the batch peak)
            evaluate_max_hr_raise(db, cred.user_id,
                                  max(nt['hr_peak'] for nt in new_trainings),
                                  source=f"{brand}_sync")
            # Разбор тренировки коучем — в daemon-треде: LLM-мост отвечает до
            # 150 с и не должен держать sync/progress (DEV_PLAN §9 C8).
            # (Coach review in a daemon thread; must never block or break the sync.)
            threading.Thread(
                target=_coach_reviews,
                args=(cred.user_id, [dict(nt) for nt in new_trainings]),
                daemon=True,
            ).start()
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
        db.rollback()  # чужая сессия не должна остаться в failed-состоянии (don't poison the caller's session)
        if progress is not None:
            progress['step'] = 'error'
            progress['message'] = f'Ошибка: {type(e).__name__}: {e}'
            progress['done'] = True
        # -1 = ошибка: таймстемп НЕ двигать. Раньше тут был 0 (=успех) →
        # окно since уезжало вперёд (буфер всего 2ч) и тренировки терялись навсегда.
        # (-1 = error: do NOT advance the timestamp; 0 here used to lose activities forever.)
        return -1
    finally:
        # db НЕ закрываем — сессией владеет вызывающий код (caller owns the session)
        try:
            await client.close()
        except Exception:
            logger.warning("Activity sync: client.close() failed for brand=%s user=%s", brand, cred.user_id, exc_info=True)
