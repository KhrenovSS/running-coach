# Роуты для загрузки TCX/FIT-файлов (Upload TCX/FIT file routes)

import hashlib
import os
import tempfile
import time
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, Form, Request, UploadFile, File
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from src.models import get_db, User, TrainingSession, DeletedTraining, get_settings
from src.parsers.tcx_parser import parse_tcx
from src.parsers.fit_parser import parse_fit
from src.analysis.utils import format_pace, format_duration
from src.utils.logger import get_logger
from src.api.deps import get_current_user
from src.services.audit import AuditService
from src.services.raw_files import save_raw_file
from src.services.telegram_notify import telegram_notify
from src.services.hr_max import evaluate_max_hr_raise
from src.web.state import _pending, _pending_lock, _cleanup_stale_pending
from src.utils.rate_limit import rate_limit

logger = get_logger("app")
router = APIRouter()


def _build_rating_keyboard(session_id: int) -> dict:
    """Inline-клавиатура для оценки тренировки (Inline keyboard for training rating)"""
    row1 = [{"text": str(i), "callback_data": f"feedback:{session_id}:{i}"} for i in range(0, 6)]
    row2 = [{"text": str(i), "callback_data": f"feedback:{session_id}:{i}"} for i in range(6, 11)]
    return {"inline_keyboard": [row1, row2]}


def _save_session_from_data(data: dict, db: Session, current_user: User,
                             pending: dict | None = None,
                             file_sha256: str | None = None,
                             raw_file_path: str | None = None) -> TrainingSession:
    """
    Создать и сохранить TrainingSession из данных трекпоинтов.
    Create and save a TrainingSession from trackpoint data.
    """
    cleaning_log_val = data.pop('cleaning_log', None)
    flags_val = data.pop('suspect_flags', None)
    trackpoints_json_val = data.pop('trackpoints_json', None)
    session = TrainingSession(**data)
    session.user_id = current_user.id
    if cleaning_log_val:
        session.cleaning_log = cleaning_log_val
    if flags_val:
        session.suspect_flags = flags_val
    if trackpoints_json_val:
        session.trackpoints_json = trackpoints_json_val
    # Дедуп (BACKLOG #228): ручная загрузка — по SHA256 контента; sync-restore — по внешнему ID
    if file_sha256:
        # Graceful-skip: sha уже в БД (например, файл импортирован раньше вручную) →
        # вернуть существующую сессию вместо IntegrityError на частичном UNIQUE
        # (return the existing session instead of tripping the partial UNIQUE index)
        existing = db.query(TrainingSession).filter(
            TrainingSession.user_id == current_user.id,
            TrainingSession.file_sha256 == file_sha256,
        ).first()
        if existing:
            return existing
        session.file_sha256 = file_sha256
        session.source_brand = 'manual'
    if pending and pending.get('external_activity_id'):
        session.external_activity_id = pending['external_activity_id']
        session.source_brand = pending.get('source_brand')
    if raw_file_path:
        session.raw_file_path = raw_file_path
    elif pending and pending.get('raw_path'):
        session.raw_file_path = pending['raw_path']
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _notify_new_session(session: TrainingSession, current_user: User,
                         source: str = "upload", filename: str = "unknown"):
    """Отправить уведомление о новой тренировке в Telegram (Notify Telegram about new training)"""
    type_labels = {'easy': 'Лёгкая пробежка', 'interval': 'Интервальная', 'tempo': 'Темповая', 'long': 'Длинная', 'recovery': 'Восстановительная'}
    t_type = type_labels.get(session.training_type, session.training_type or '—')
    telegram_notify(
        user_id=current_user.id,
        text=f"🏃 *Тренировка {'восстановлена!' if source == 'confirm_deleted' else 'загружена!'}*\n"
             f"📅 {session.begin_ts.strftime('%d.%m.%Y %H:%M')}\n"
             f"▫️ {session.total_distance_km:.1f} км\n"
             f"▫️ {t_type}\n"
             f"📂 {filename}\n\n"
             f"Насколько тяжёлой была тренировка?\n"
             f"`0` — легко\n"
             f"`10` — очень тяжело",
        reply_markup=_build_rating_keyboard(session.id),
    )


@router.post('/upload')
async def upload_files(files: list[UploadFile] = File(...), db: Session = Depends(get_db),
                       current_user: User = Depends(get_current_user),
                       _: None = Depends(rate_limit(max_requests=30, window_seconds=60))):
    settings = get_settings(db, current_user.id)
    from src.services.repositories import latest_lthr
    user_lthr = latest_lthr(current_user.id, db=db)  # зоны от порога (F4/M3.1)
    saved = 0
    hr_peak = 0  # пик батча для адаптивного max_hr (batch peak for adaptive max HR)
    deleted_hit = None
    temp_id = None
    audit = AuditService(db)
    uploaded_filenames = []
    parse_errors = []

    for file in files:
        ext = os.path.splitext(file.filename or '')[1].lower()
        suffix = ".fit" if ext == ".fit" else ".tcx"
        uploaded_filenames.append(file.filename or "unknown")

        contents = await file.read()
        if len(contents) > 50 * 1024 * 1024:
            logger.warning("Upload: file too large — %s (%d bytes)", file.filename, len(contents))
            parse_errors.append(file.filename or "unknown")
            continue

        # Дедуп по контенту (BACKLOG #228): тот же файл — не парсим повторно
        # (Content dedup: identical file — skip without re-parsing)
        file_sha = hashlib.sha256(contents).hexdigest()
        sha_exists = db.query(TrainingSession).filter(
            TrainingSession.user_id == current_user.id,
            TrainingSession.file_sha256 == file_sha,
        ).first()
        if sha_exists:
            logger.info("Upload: %s уже импортирован (sha256 match, session=%d)", file.filename, sha_exists.id)
            continue

        # Сырьё (BACKLOG #229): сохраняем исходник до парсинга — ошибка записи не роняет импорт
        raw_path = save_raw_file(current_user.id, contents, ext)

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(contents)
            tmp_path = tmp.name
        try:
            if ext == ".fit":
                data = parse_fit(tmp_path, max_hr=settings.max_hr,
                                 max_credible_pace=settings.max_credible_pace,
                                 max_gps_jump_m=settings.max_gps_jump_m,
                                 min_hr_for_fast_pace=settings.min_hr_for_fast_pace,
                                 lthr=user_lthr)
            else:
                data = parse_tcx(tmp_path, max_hr=settings.max_hr,
                                 max_credible_pace=settings.max_credible_pace,
                                 max_gps_jump_m=settings.max_gps_jump_m,
                                 min_hr_for_fast_pace=settings.min_hr_for_fast_pace,
                                 lthr=user_lthr)
        except Exception as e:
            logger.warning("Upload: parse error for %s — %s", file.filename, e, exc_info=True)
            parse_errors.append(file.filename or "unknown")
            os.unlink(tmp_path)
            continue
        if data is None:
            logger.warning("Загрузка: не удалось распарсить %s (Upload: parse failed)", file.filename)
            parse_errors.append(file.filename or "unknown")
            os.unlink(tmp_path)
            continue
        deleted_match = None
        bt = data['begin_ts']
        if bt:
            all_deleted = db.query(DeletedTraining).filter(DeletedTraining.user_id == current_user.id).all()
            for d in all_deleted:
                if d.begin_ts and abs((d.begin_ts - bt).total_seconds()) < 120:
                    deleted_match = d
                    break
        if deleted_match:
            tid = str(uuid.uuid4())
            with _pending_lock:
                _pending[tid] = {'path': tmp_path, 'filename': file.filename, 'data': data,
                                 'sha256': file_sha, 'raw_path': raw_path, '_created': time.time()}
                _cleanup_stale_pending()
            pace_str = format_pace(deleted_match.avg_pace) if deleted_match.avg_pace else '—'
            deleted_hit = {
                'id': deleted_match.id,
                'date': deleted_match.begin_ts.strftime('%d.%m.%Y %H:%M'),
                'distance': round(deleted_match.total_distance_km, 1) if deleted_match.total_distance_km else '—',
                'distance_display': f'{deleted_match.total_distance_km:.1f} км' if deleted_match.total_distance_km else '—',
                'pace': pace_str,
                'pace_val': round(deleted_match.avg_pace, 2) if deleted_match.avg_pace else None,
                'duration': format_duration(deleted_match.duration_minutes) if deleted_match.duration_minutes else '—',
                'type': deleted_match.training_type or '—',
                'hr': f'{deleted_match.avg_heart_rate}' if deleted_match.avg_heart_rate else '—',
                'calories': f'{deleted_match.calories}' if deleted_match.calories else '—',
            }
            temp_id = tid
            os.unlink(tmp_path)
            break
        exists = db.query(TrainingSession).filter(
            TrainingSession.begin_ts == data['begin_ts'],
            TrainingSession.user_id == current_user.id
        ).first()
        if not exists:
            tz = data.get('timezone')
            if tz:
                db_user = db.query(User).filter(User.id == current_user.id).first()
                if db_user and not db_user.timezone:
                    db_user.timezone = tz
            session = _save_session_from_data(data, db, current_user,
                                              file_sha256=file_sha, raw_file_path=raw_path)
            saved += 1
            hr_peak = max(hr_peak, session.hr_peak_smoothed or session.max_heart_rate or 0)
            _notify_new_session(session, current_user, filename=file.filename or "unknown")
            audit.log_training_uploaded(
                user_id=current_user.id,
                training_id=session.id,
                filename=file.filename or "unknown",
                distance_km=session.total_distance_km,
                training_type=session.training_type,
            )
        logger.info("Temp file удалён: %s", tmp_path)
        os.unlink(tmp_path)

    # Адаптивный max_hr: один вызов на мультифайловый батч; строго ПОСЛЕ коммитов —
    # сервис коммитит сессию (one call per batch, strictly after commits — service commits)
    evaluate_max_hr_raise(db, current_user.id, hr_peak, source="upload")

    if parse_errors:
        audit.log_event(
            event_type="training.upload_summary",
            message=f"Upload finished: {saved} saved, {len(parse_errors)} parse errors",
            severity="warning" if parse_errors else "info",
            user_id=current_user.id,
            metadata={"saved": saved, "files": uploaded_filenames, "parse_errors": parse_errors, "deleted_match": bool(deleted_hit)},
        )

    if deleted_hit:
        return JSONResponse({'saved': saved, 'deleted_match': deleted_hit, 'temp_id': temp_id})
    return JSONResponse({'saved': saved})


@router.post('/upload/confirm')
async def confirm_upload(temp_ids: list[str] = Form(...), db: Session = Depends(get_db),
                          current_user: User = Depends(get_current_user)):
    confirmed = 0
    hr_peak = 0  # пик батча для адаптивного max_hr (batch peak for adaptive max HR)
    audit = AuditService(db)
    for temp_id in temp_ids:
        with _pending_lock:
            pending = _pending.pop(temp_id, None)
        if not pending:
            continue
        data = pending['data']
        exists = db.query(TrainingSession).filter(
            TrainingSession.begin_ts == data['begin_ts'],
            TrainingSession.user_id == current_user.id
        ).first()
        if not exists:
            session = _save_session_from_data(data, db, current_user, pending,
                                              file_sha256=pending.get('sha256'))
            confirmed += 1
            hr_peak = max(hr_peak, session.hr_peak_smoothed or session.max_heart_rate or 0)
            _notify_new_session(session, current_user, source="confirm_upload",
                                filename=pending.get('filename', 'unknown'))
            audit.log_training_uploaded(
                user_id=current_user.id,
                training_id=session.id,
                filename=pending.get('filename', 'unknown'),
                distance_km=session.total_distance_km,
                training_type=session.training_type,
                source="confirm_upload",
            )
        Path(pending['path']).unlink(missing_ok=True)
    # Адаптивный max_hr — строго после коммитов, сервис коммитит сессию (after commits only)
    evaluate_max_hr_raise(db, current_user.id, hr_peak, source="confirm_upload")
    audit.log_event(
        event_type="training.confirm_upload",
        message=f"Confirmed problematic uploads: {confirmed} saved",
        severity="info",
        user_id=current_user.id,
        metadata={"confirmed": confirmed, "temp_ids": temp_ids},
    )
    return RedirectResponse(url='/', status_code=303)


@router.post('/upload/confirm_deleted')
async def confirm_deleted(temp_id: str = Form(...), db: Session = Depends(get_db),
                           current_user: User = Depends(get_current_user)):
    with _pending_lock:
        pending = _pending.pop(temp_id, None)
    audit = AuditService(db)
    if not pending:
        audit.log_event(
            event_type="training.confirm_deleted",
            message="Confirm deleted failed: temp_id not found",
            severity="warning",
            user_id=current_user.id,
            metadata={"temp_id": temp_id},
        )
        return JSONResponse({'ok': False, 'error': 'temp_id not found'})
    data = pending['data']
    bt = data.get('begin_ts')
    if bt:
        all_deleted = db.query(DeletedTraining).filter(DeletedTraining.user_id == current_user.id).all()
        for d in all_deleted:
            if d.begin_ts and abs((d.begin_ts - bt).total_seconds()) < 120:
                db.delete(d)
                break
    exists = db.query(TrainingSession).filter(
        TrainingSession.begin_ts == bt,
        TrainingSession.user_id == current_user.id
    ).first()
    if not exists:
        session = _save_session_from_data(data, db, current_user, pending,
                                          file_sha256=pending.get('sha256'))
        _notify_new_session(session, current_user, source="confirm_deleted",
                            filename=pending.get('filename', 'unknown'))
        # Адаптивный max_hr — строго после коммита, сервис коммитит сессию (after commit only)
        evaluate_max_hr_raise(db, current_user.id,
                              session.hr_peak_smoothed or session.max_heart_rate or 0,
                              source="confirm_deleted")
        logger.info("Удалённая тренировка от %s повторно импортирована (Deleted training re-imported)", bt)
        audit.log_training_uploaded(
            user_id=current_user.id,
            training_id=session.id,
            filename=pending.get('filename', 'unknown'),
            distance_km=session.total_distance_km,
            training_type=session.training_type,
            source="confirm_deleted",
        )
    _path = pending.get('path')
    if _path:
        Path(_path).unlink(missing_ok=True)
    audit.log_event(
        event_type="training.confirm_deleted",
        message="Previously deleted training re-imported",
        severity="info",
        user_id=current_user.id,
        metadata={"begin_ts": str(bt) if bt else None},
    )
    return JSONResponse({'ok': True})
