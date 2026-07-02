# Импорт FastAPI и компонентов (FastAPI and component imports)
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from src.models import SessionLocal, User, TrainingSession, WeightMeasurement, DeletedTraining, DailyMetrics, get_settings, get_db
from src.parsers.tcx_parser import parse_tcx
from src.parsers.fit_parser import parse_fit
from src.parsers.common import weather_icon, format_pace, format_duration
from src.logger import get_logger
from src.crypto import encrypt, decrypt
from src.api.middleware import register_middleware
from src.api.routes.health import router as health_router
from src.api.routes.auth import router as auth_router
from src.api.deps import get_current_user
from src.config import CONFIG
from src.services.auth import verify_telegram_login_token, check_telegram_login_token
from src.services.audit import AuditService
logger = get_logger("app")
import httpx
import json
import shutil
import os
import tempfile
import uuid
import threading
import time
from pathlib import Path

from src.services.telegram_notify import telegram_notify
from src.services.stats import fmt_duration, calc_stats, zone_ranges, render_zone_bars, render_type_row, build_nav_html, MONTHS_RU, MONTHS_RU_SHORT, ZONE_COLORS
from src.services.recovery_view import hrv_status, tired_label, readiness_label, load_label
from src.services.coros_sync_auto import (_auto_sync_status, _auto_sync_status_lock, health_sync_interval,
    activity_sync_interval, update_last_health_sync, save_dashboard_data,
    auto_sync_health, auto_sync_health_inner, auto_sync_activities, auto_sync_activities_inner)

# Создание экземпляра FastAPI (Create FastAPI app instance)
app = FastAPI(title="AI Running Coach")
register_middleware(app)
app.include_router(health_router)
app.include_router(auth_router)
os.makedirs("uploads", exist_ok=True)
templates = Jinja2Templates(directory="src/web/templates")

# Хранилище для загруженных TCX, ожидающих подтверждения (Pending uploads awaiting user confirmation)
PENDING_DIR = Path(os.getenv("PENDING_DIR", "/tmp/running_coach_uploads"))
PENDING_DIR.mkdir(parents=True, exist_ok=True)
_pending = {}  # temp_id -> dict with 'path', 'filename', 'data'
_sync_tasks = {}  # task_id -> dict with progress info
_sync_tasks_lock = threading.Lock()

# Словарь типов тренировок на русском (Training type labels in Russian)
TRAINING_TYPES_RU = {
    'interval': 'Интервальная',
    'long': 'Длинная',
    'recovery': 'Восстановительная',
    'tempo': 'Темповая',
}

# Основная функция рендеринга главной страницы (Main page render function)
def render_page(db, user_id: int, user_name: str = "Бегун", year=None, month=None):
    all_sessions = db.query(TrainingSession).filter(TrainingSession.user_id == user_id).order_by(TrainingSession.begin_ts.desc()).all()
    settings = get_settings()
    weight_measurements = db.query(WeightMeasurement).filter(WeightMeasurement.user_id == user_id).order_by(WeightMeasurement.measured_at).all()
    # Последние метрики восстановления (Latest recovery metrics)
    recovery_metrics = db.query(DailyMetrics).filter(DailyMetrics.user_id == user_id).order_by(DailyMetrics.date.desc()).limit(30).all()

    weight_json = json.dumps([{
        'date': wm.measured_at.strftime('%Y-%m-%d'),
        'weight': wm.weight_kg,
    } for wm in weight_measurements])

    # Для графика: от старых к новым (слева направо), для карточки: последняя сверху
    recovery_json = json.dumps([{
        'date': rm.date.strftime('%Y-%m-%d'),
        'rhr': rm.rhr,
    } for rm in reversed(recovery_metrics)])

    latest = all_sessions[0].begin_ts if all_sessions else None
    week_stats = month_stats = None
    if latest:
        from datetime import timedelta
        week_cut = latest - timedelta(days=7)
        month_cut = latest - timedelta(days=30)
        week_sessions = [s for s in all_sessions if s.begin_ts >= week_cut]
        month_sessions = [s for s in all_sessions if s.begin_ts >= month_cut]
        week_stats = calc_stats(week_sessions)
        month_stats = calc_stats(month_sessions)

    # Навигация (Navigation)
    nav_html = ""
    sel_year, sel_month = year, month
    if all_sessions:
        nav_result = build_nav_html(all_sessions, sel_year, sel_month)
        if nav_result:
            nav_html, sel_year, sel_month = nav_result

    # Фильтруем или показываем последние 20 (Filter or show latest 20)
    if sel_year and sel_month:
        filtered = [s for s in all_sessions
                    if s.begin_ts and s.begin_ts.year == sel_year and s.begin_ts.month == sel_month]
    else:
        filtered = all_sessions[:20]

    rows = ""
    for s in filtered:
        t = s.begin_ts.strftime("%d.%m.%Y %H:%M") if s.begin_ts else ""
        dur = fmt_duration(s.duration_minutes)
        eg = s.elevation_gain
        el = s.elevation_loss
        if eg is not None and el is not None:
            elev_str = f"↑{eg} / ↓{el}"
        elif eg is not None:
            elev_str = f"↑{eg}"
        elif el is not None:
            elev_str = f"↓{el}"
        else:
            elev_str = ""
        warn = ""
        if s.cleaning_log:
            warn = "✂️"
        elif s.suspect_flags:
            warn = "⚠️"
        cad_str = str(s.avg_cadence) if s.avg_cadence is not None else "—"
        cal_str = f"{s.calories}" if s.calories is not None else ""
        extra_str = cal_str
        rows += f"<tr onclick=\"window.location='/session/{s.id}'\" style='cursor:pointer'>"
        rows += f"<td>{warn} {t}</td><td>{dur}</td><td>{s.total_distance_km:.2f}</td><td>{s.avg_heart_rate}</td>"
        rows += f"<td>{TRAINING_TYPES_RU.get(s.training_type, s.training_type)}</td><td>{cad_str}</td><td>{elev_str}</td><td>{extra_str}</td></tr>"

    if not rows:
        rows = "<tr><td colspan='8' style='color:#888;padding:30px;'>Нет тренировок за выбранный период</td></tr>"

    week_bars = render_zone_bars(week_stats['zone_min'], week_stats['total_min'], settings.max_hr) if week_stats else ""
    month_bars = render_zone_bars(month_stats['zone_min'], month_stats['total_min'], settings.max_hr) if month_stats else ""
    week_types = render_type_row(week_stats['type_count']) if week_stats else ""
    month_types = render_type_row(month_stats['type_count']) if month_stats else ""

    # Последние метрики для отображения (Latest metrics for display)
    latest_rm = recovery_metrics[0] if recovery_metrics else None
    if latest_rm:
        _, latest_hrv = hrv_status(latest_rm.avg_sleep_hrv, latest_rm.sleep_hrv_baseline, latest_rm.sleep_hrv_sd,
            json.loads(latest_rm.sleep_hrv_interval_list) if latest_rm.sleep_hrv_interval_list else None)
        latest_rhr = str(latest_rm.rhr) if latest_rm.rhr is not None else ''
        latest_tired = tired_label(latest_rm.tired_rate)
        latest_perf = readiness_label(latest_rm.performance, latest_rm.recovery_pct, latest_rm.training_load_ratio)
        latest_recovery_pct = f'{latest_rm.recovery_pct}%' if latest_rm.recovery_pct is not None else ''
    else:
        latest_hrv = latest_rhr = latest_tired = latest_perf = ''
        latest_recovery_pct = ''

    # Статус автосинхронизации (Auto-sync status)
    from datetime import datetime
    now = datetime.now()
    with _auto_sync_status_lock:
        as_health = dict(_auto_sync_status['health'])
        as_activity = dict(_auto_sync_status['activity'])
    def fmt_sync_time(t):
        if not t:
            return '—'
        diff = (now - t).total_seconds()
        if diff < 60:
            return 'только что'
        elif diff < 3600:
            return f'{int(diff/60)} мин назад'
        elif diff < 86400:
            return f'{int(diff/3600)} ч назад'
        else:
            return t.strftime('%d.%m %H:%M')
    def fmt_next_sync(t):
        if not t:
            return '—'
        left = (t - now).total_seconds()
        if left < 0:
            return 'скоро'
        return f'через {int(left/60)} мин'

    user_header = f"👤 {user_name} | <a href='/auth/logout'>Выйти</a>"
    return {
        "rows": rows,
        "nav_html": nav_html,
        "user_header": user_header,
        "max_hr": settings.max_hr,
        "weight": settings.weight,
        "week_km": week_stats['total_km'] if week_stats else 0,
        "week_dur": week_stats['total_dur'] if week_stats else "",
        "week_bars": week_bars,
        "week_types": week_types,
        "month_km": month_stats['total_km'] if month_stats else 0,
        "month_dur": month_stats['total_dur'] if month_stats else "",
        "month_bars": month_bars,
        "month_types": month_types,
        "weight_json": weight_json,
        "recovery_json": recovery_json,
        "latest_hrv": latest_hrv,
        "latest_rhr": latest_rhr,
        "latest_tired": latest_tired,
        "latest_perf": latest_perf,
        "latest_recovery_pct": latest_recovery_pct,
        "auto_health_last": fmt_sync_time(as_health['last_run']),
        "auto_health_next": fmt_next_sync(as_health['next_run']),
        "auto_health_status": as_health['status'],
        "auto_health_msg": as_health['message'],
        "auto_activity_last": fmt_sync_time(as_activity['last_run']),
        "auto_activity_next": fmt_next_sync(as_activity['next_run']),
        "auto_activity_status": as_activity['status'],
        "auto_activity_msg": as_activity['message'],
    }

# Событие при запуске сервера: инициализация БД и миграции (Startup event: DB init and migrations)
@app.on_event("startup")
def startup():
    from src.models import init_db, engine, User
    from datetime import datetime
    init_db()
    # Применяем Alembic миграции (Apply Alembic migrations for schema changes)
    try:
        from alembic.config import Config as AlembicConfig
        from alembic import command
        alembic_cfg = AlembicConfig("alembic.ini")
        command.upgrade(alembic_cfg, "head")
    except Exception as e:
        logger.error("Ошибка Alembic миграции: %s", e)

    # Очистка старых pending-файлов (Cleanup old pending uploads)
    for f in PENDING_DIR.glob("*.tcx"):
        f.unlink(missing_ok=True)
    _pending.clear()
    settings = get_settings()
    db = SessionLocal()
    try:
        # Гарантируем существование пользователя-админа (Ensure admin user exists)
        from src.models import User
        admin_user = db.query(User).filter(User.id == 1).first()
        if not admin_user:
            admin_user = User(id=1, is_active=True, max_hr=177)
            db.add(admin_user)
            db.commit()
            db.refresh(admin_user)
        
        # Первое измерение веса (First weight measurement)
        existing = db.query(WeightMeasurement).filter(WeightMeasurement.user_id == admin_user.id).first()
        if not existing and settings.weight:
            wm = WeightMeasurement(weight_kg=settings.weight, measured_at=datetime.utcnow(), user_id=admin_user.id)
            db.add(wm)
            db.commit()
        
        # Логируем запуск приложения (Log application startup)
        audit = AuditService(db)
        audit.log_event(
            event_type="app.startup",
            message="Application started",
            severity="info",
            user_id=admin_user.id,
        )
    except Exception as e:
        logger.warning("Не удалось инициализировать пользователя и аудит: %s", e)
    finally:
        db.close()

    # Восстановление логгера после uvicorn dictConfig (Restore logger after uvicorn dictConfig)
    from src.utils.logger import fix_logger_after_uvicorn
    fix_logger_after_uvicorn()

    # Запуск фоновой автосинхронизации Coros (Start background auto-sync)
    _start_auto_sync()


# === Страницы аутентификации (Auth pages) ===

# Сообщения об ошибках для форм (Error messages for auth forms)
_AUTH_ERRORS = {
    "invalid_token": "Ссылка устарела или недействительна. Запросите новую через /start в Telegram.",
    "invalid_credentials": "Неверный email или пароль.",
    "short_password": "Пароль слишком короткий (минимум 6 символов).",
    "password_mismatch": "Пароли не совпадают.",
    "email_taken": "Этот email уже используется.",
}


@app.get('/login', response_class=HTMLResponse)
async def login_page(request: Request, error: Optional[str] = None):
    """Страница входа по email и паролю (Login page — email + password)"""
    # Если уже авторизован — редирект на главную (If already logged in — redirect to home)
    if request.session.get("user_id"):
        return RedirectResponse(url="/", status_code=303)
    err_msg = _AUTH_ERRORS.get(error, "")
    err_html = f'<div class="auth-error">{err_msg}</div>' if err_msg else ''
    return templates.TemplateResponse(request, "login.html", {"err_html": err_html})


@app.get('/register', response_class=HTMLResponse)
async def register_page(token: str = "", error: Optional[str] = None, db: Session = Depends(get_db)):
    """Страница регистрации — установка email и пароля (Registration page — set email and password)"""
    if not token:
        return RedirectResponse(url="/login?error=invalid_token", status_code=303)
    # Проверяем, валиден ли токен без потребления (Check token validity without consuming)
    user = check_telegram_login_token(db, token)
    if not user:
        return RedirectResponse(url="/login?error=invalid_token", status_code=303)
    # Если у пользователя уже есть пароль — редирект на логин (If user already has password — redirect to login)
    if user.password_hash:
        return RedirectResponse(url="/login?error=invalid_token", status_code=303)
    err_msg = _AUTH_ERRORS.get(error, "")
    err_html = f'<div class="auth-error">{err_msg}</div>' if err_msg else ''
    return templates.TemplateResponse(request, "register.html", {
        "err_html": err_html, "token": token,
        "password_min_length": CONFIG.AUTH.PASSWORD_MIN_LENGTH,
    })


# Главная страница: список тренировок и статистика (Main page: session list and stats)
@app.get('/', response_class=HTMLResponse)
async def index(request: Request, year: Optional[int] = None, month: Optional[int] = None, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    user_name = current_user.name or current_user.telegram_username or "Бегун"
    ctx = render_page(db, user_id=current_user.id, user_name=user_name, year=year, month=month)
    return templates.TemplateResponse(request, "index.html", ctx)


# Загрузка TCX/FIT-файлов (TCX/FIT file upload endpoint)
@app.post('/upload')
async def upload_files(files: list[UploadFile] = File(...), db: Session = Depends(get_db),
                       current_user: User = Depends(get_current_user)):
    settings = get_settings()
    saved = 0
    deleted_hit = None
    temp_id = None
    audit = AuditService(db)
    uploaded_filenames = []
    parse_errors = []
    
    for file in files:
        ext = os.path.splitext(file.filename or '')[1].lower()
        suffix = ".fit" if ext == ".fit" else ".tcx"
        uploaded_filenames.append(file.filename or "unknown")
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name
        if ext == ".fit":
            data = parse_fit(tmp_path, max_hr=settings.max_hr,
                             max_credible_pace=settings.max_credible_pace,
                             max_gps_jump_m=settings.max_gps_jump_m,
                             min_hr_for_fast_pace=settings.min_hr_for_fast_pace)
        else:
            data = parse_tcx(tmp_path, max_hr=settings.max_hr,
                             max_credible_pace=settings.max_credible_pace,
                             max_gps_jump_m=settings.max_gps_jump_m,
                             min_hr_for_fast_pace=settings.min_hr_for_fast_pace)
        if data is None:
            logger.warning("Загрузка: не удалось распарсить %s (Upload: parse failed)", file.filename)
            parse_errors.append(file.filename or "unknown")
            os.unlink(tmp_path)
            continue
        # Проверка, не было ли эта тренировка удалена ранее (Check if this training was previously deleted)
        deleted_match = None
        bt = data['begin_ts']
        if bt:
            all_deleted = db.query(DeletedTraining).filter(DeletedTraining.user_id == current_user.id).all()
            for d in all_deleted:
                if d.begin_ts and abs((d.begin_ts - bt).total_seconds()) < 120:
                    deleted_match = d
                    break
        if deleted_match:
            # Сохраняем распарсенные данные в _pending для отложенного сохранения (Store parsed data for deferred save)
            tid = str(uuid.uuid4())
            _pending[tid] = {'path': tmp_path, 'filename': file.filename, 'data': data}
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
            os.unlink(tmp_path)  # не удалять tmp — перенесём в _pending
            break
        # Проверка, существует ли уже такая тренировка (Check if training already exists)
        exists = db.query(TrainingSession).filter(
            TrainingSession.begin_ts == data['begin_ts'],
            TrainingSession.user_id == current_user.id
        ).first()
        if not exists:
            cleaning_log_val = data.pop('cleaning_log', None)
            flags_val = data.pop('suspect_flags', None)
            session = TrainingSession(**data)
            session.user_id = current_user.id
            if cleaning_log_val:
                session.cleaning_log = cleaning_log_val
            if flags_val:
                session.suspect_flags = flags_val
            db.add(session)
            db.commit()
            db.refresh(session)
            saved += 1
            audit.log_training_uploaded(
                user_id=current_user.id,
                training_id=session.id,
                filename=file.filename or "unknown",
                distance_km=session.total_distance_km,
                training_type=session.training_type,
            )
        os.unlink(tmp_path)
    
    # Аудит: сводка по загрузке (Audit: upload summary)
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


# Подтверждение сомнительных тренировок (Confirm problematic uploads)
@app.post('/upload/confirm')
async def confirm_upload(temp_ids: list[str] = Form(...), db: Session = Depends(get_db),
                          current_user: User = Depends(get_current_user)):
    confirmed = 0
    audit = AuditService(db)
    for temp_id in temp_ids:
        pending = _pending.pop(temp_id, None)
        if not pending:
            continue
        data = pending['data']
        exists = db.query(TrainingSession).filter(
            TrainingSession.begin_ts == data['begin_ts'],
            TrainingSession.user_id == current_user.id
        ).first()
        if not exists:
            cleaning_log_val = data.pop('cleaning_log', None)
            flags_val = data.pop('suspect_flags', None)
            session = TrainingSession(**data)
            session.user_id = current_user.id
            if cleaning_log_val:
                session.cleaning_log = cleaning_log_val
            if flags_val:
                session.suspect_flags = flags_val
            db.add(session)
            db.commit()
            db.refresh(session)
            confirmed += 1
            audit.log_training_uploaded(
                user_id=current_user.id,
                training_id=session.id,
                filename=pending.get('filename', 'unknown'),
                distance_km=session.total_distance_km,
                training_type=session.training_type,
                source="confirm_upload",
            )
        Path(pending['path']).unlink(missing_ok=True)
    audit.log_event(
        event_type="training.confirm_upload",
        message=f"Confirmed problematic uploads: {confirmed} saved",
        severity="info",
        user_id=current_user.id,
        metadata={"confirmed": confirmed, "temp_ids": temp_ids},
    )
    return RedirectResponse(url='/', status_code=303)


# Принудительное сохранение ранее удалённой тренировки (Force-save a previously deleted training)
@app.post('/upload/confirm_deleted')
async def confirm_deleted(temp_id: str = Form(...), db: Session = Depends(get_db),
                           current_user: User = Depends(get_current_user)):
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
    # Удаляем запись DeletedTraining (Remove DeletedTraining entry)
    if bt:
        all_deleted = db.query(DeletedTraining).filter(DeletedTraining.user_id == current_user.id).all()
        for d in all_deleted:
            if d.begin_ts and abs((d.begin_ts - bt).total_seconds()) < 120:
                db.delete(d)
                break
    # Сохраняем тренировку (Save training)
    exists = db.query(TrainingSession).filter(
        TrainingSession.begin_ts == bt,
        TrainingSession.user_id == current_user.id
    ).first()
    if not exists:
        cleaning_log_val = data.pop('cleaning_log', None)
        flags_val = data.pop('suspect_flags', None)
        session = TrainingSession(**data)
        session.user_id = current_user.id
        if cleaning_log_val:
            session.cleaning_log = cleaning_log_val
        if flags_val:
            session.suspect_flags = flags_val
        db.add(session)
        db.commit()
        db.refresh(session)
        logger.info("Удалённая тренировка от %s повторно импортирована (Deleted training re-imported)", bt)
        audit.log_training_uploaded(
            user_id=current_user.id,
            training_id=session.id,
            filename=pending.get('filename', 'unknown'),
            distance_km=session.total_distance_km,
            training_type=session.training_type,
            source="confirm_deleted",
        )
    Path(pending.get('path', '')).unlink(missing_ok=True)
    audit.log_event(
        event_type="training.confirm_deleted",
        message="Previously deleted training re-imported",
        severity="info",
        user_id=current_user.id,
        metadata={"begin_ts": str(bt) if bt else None},
    )
    return JSONResponse({'ok': True})


# Детальный просмотр тренировки (Training session detail page)
@app.get('/session/{session_id}', response_class=HTMLResponse)
async def session_detail(request: Request, session_id: int, db: Session = Depends(get_db),
                         current_user: User = Depends(get_current_user)):
    s = db.query(TrainingSession).filter(TrainingSession.id == session_id, TrainingSession.user_id == current_user.id).first()
    if not s:
        return HTMLResponse("<h2>Тренировка не найдена</h2><a href='/'>Назад</a>", status_code=404)

    # Получаем метрики восстановления на день тренировки (Get recovery metrics for training day)
    recovery_info = None
    if s.begin_ts:
        from datetime import date
        training_date = s.begin_ts.date()
        rm = db.query(DailyMetrics).filter(DailyMetrics.user_id == current_user.id, DailyMetrics.date == training_date).first()
        if rm:
            _, hrv_label = hrv_status(rm.avg_sleep_hrv, rm.sleep_hrv_baseline, rm.sleep_hrv_sd,
                json.loads(rm.sleep_hrv_interval_list) if rm.sleep_hrv_interval_list else None)
            rhr_str = f"{rm.rhr}" if rm.rhr is not None else "—"
            tired_str = tired_label(rm.tired_rate) or "—"
            perf_str = readiness_label(rm.performance, rm.recovery_pct, rm.training_load_ratio) or "—"
            load_str = load_label(rm.training_load) or "—"
            recovery_pct_str = f"{rm.recovery_pct}%" if rm.recovery_pct is not None else "—"
            form_str = f"{rm.cti:.0f}" if rm.cti is not None else "—"
            recovery_info = {
                'hrv': hrv_label or "—",
                'rhr': rhr_str,
                'tired_rate': tired_str,
                'performance': perf_str,
                'training_load': load_str,
                'recovery_pct': recovery_pct_str,
                'form_score': form_str,
            }

    seg_rows = ""
    segs = s.segments_json or []
    for i, seg in enumerate(segs, 1):
        zone = seg.get('zone', '')
        cls = f"zone-z{zone}" if zone else ""
        pace = seg.get('pace') or "—"
        dur = seg.get('duration') or f"{seg['duration_min']:.0f}"
        eg = seg.get('elevation_gain')
        el = seg.get('elevation_loss')
        seg_eg = str(eg) if eg is not None else "—"
        seg_el = str(el) if el is not None else "—"
        cad_seg = seg.get('avg_cadence')
        cad_seg_str = str(cad_seg) if cad_seg is not None else "—"
        seg_rows += f"<tr class='{cls}'><td>{i}</td><td>Z{zone}</td><td>{dur}</td><td>{seg['distance_km']}</td><td>{seg['avg_hr']}</td><td>{cad_seg_str}</td><td>{pace}</td><td>{seg_eg}</td><td>{seg_el}</td></tr>"

    eg_total = s.elevation_gain or 0
    el_total = s.elevation_loss or 0
    if s.weather_code is not None and s.avg_temperature is not None:
        temp_display = f"{weather_icon(s.weather_code)} {s.avg_temperature}°"
    elif s.avg_temperature is not None:
        temp_display = f"{s.avg_temperature}°"
    else:
        temp_display = None
    background_info = temp_display if temp_display else ""

    chart_json = json.dumps(s.hr_pace_series or [])

    suspect_badge = ""
    suspect_detail = ""
    reason_labels = {
        'pace_impossible': 'Нереальный темп (Impossible pace)',
        'hr_pace_mismatch': 'Пульс не соответствует темпу (HR/pace mismatch)',
        'gps_spike': 'Скачки GPS (GPS jumps)',
        'too_short': 'Слишком короткая тренировка (Too short)',
        'anomaly': 'Аномалия (Anomaly)',
    }
    if s.cleaning_log:
        items = ""
        total_removed_dur = 0
        total_removed_dist = 0
        for entry in s.cleaning_log:
            reasons = ", ".join(reason_labels.get(r, r) for r in (entry.get('reason') or ['unknown']))
            removed_dur = entry.get('removed_dur_s', 0)
            removed_dist = entry.get('removed_dist_m', 0)
            total_removed_dur += removed_dur
            total_removed_dist += removed_dist
            dur_str = f"{removed_dur // 60}:{removed_dur % 60:02d}" if removed_dur else "—"
            items += f"<li>Удалён участок: {entry.get('removed_count', '?')} точек, {removed_dist}м, {dur_str} — {reasons}</li>"
        if items:
            suspect_badge = '<span style="background:#ff9800;color:white;padding:2px 10px;border-radius:4px;font-size:14px">✂️ Очищено</span>'
            suspect_detail = f'<div style="background:#fff3e0;border:1px solid #ffccbc;border-radius:8px;padding:10px;margin-bottom:15px"><b>✂️ Удалены ошибочные участки тренировки:</b><ul style="margin:5px 0 0 0;padding-left:20px">{items}</ul></div>'
    elif s.suspect_flags:
        items = "".join(f"<li>{reason_labels.get(f, f)}</li>" for f in s.suspect_flags)
        suspect_badge = '<span style="background:#ff5722;color:white;padding:2px 10px;border-radius:4px;font-size:14px">⚠️ Ошибочные данные</span>'
        suspect_detail = f'<div style="background:#fff3e0;border:1px solid #ffccbc;border-radius:8px;padding:10px;margin-bottom:15px"><b>⚠️ Обнаружены проблемы:</b><ul style="margin:5px 0 0 0;padding-left:20px">{items}</ul></div>'

    cadence_display = str(s.avg_cadence) if s.avg_cadence is not None else "—"
    cal = str(s.calories) if s.calories is not None else "—"

    # Рендер recovery-блока (Render recovery info block)
    recovery_html = ""
    if recovery_info:
        recovery_html = f'''
        <div class='card' style='background:#f3e5f5;border-color:#ce93d8'>
            <h4 style='margin:0 0 10px 0;color:#7B1FA2'>❤️ Восстановление перед тренировкой</h4>
            <div class='info'>
                <div class='info-item'><span class='info-label'>Восстановление</span><b>{recovery_info["recovery_pct"]}</b></div>
                <div class='info-item'><span class='info-label'>Нервная система</span><b>{recovery_info["hrv"]}</b></div>
                <div class='info-item'><span class='info-label'>Пульс покоя</span><b>{recovery_info["rhr"]}</b><span class='info-unit'>уд/мин</span></div>
                <div class='info-item'><span class='info-label'>Усталость</span><b>{recovery_info["tired_rate"]}</b></div>
                <div class='info-item'><span class='info-label'>Базовая форма</span><b>{recovery_info["form_score"]}</b></div>
                <div class='info-item'><span class='info-label'>Состояние</span><b>{recovery_info["performance"]}</b></div>
                <div class='info-item'><span class='info-label'>Нагрузка</span><b>{recovery_info["training_load"]}</b></div>
            </div>
        </div>'''

    user_name = current_user.name or current_user.telegram_username or "Бегун"
    user_header = f"👤 {user_name} | <a href='/auth/logout'>Выйти</a>"
    return templates.TemplateResponse(request, "session.html", {
        "user_header": user_header,
        "session_id": s.id,
        "suspect_badge": suspect_badge,
        "suspect_detail": suspect_detail,
        "type_ru": TRAINING_TYPES_RU.get(s.training_type, s.training_type),
        "date": s.begin_ts.strftime("%d.%m.%Y %H:%M") if s.begin_ts else "",
        "dist": f"{s.total_distance_km:.2f}",
        "dur": fmt_duration(s.duration_minutes),
        "hr": s.avg_heart_rate,
        "cadence": cadence_display,
        "cal": cal,
        "background_info": background_info,
        "elev_gain": eg_total,
        "elev_loss": el_total,
        "segments_rows": seg_rows,
        "chart_json": chart_json,
        "recovery_html": recovery_html,
    })


# Страница настроек (Settings page)
@app.get('/settings', response_class=HTMLResponse)
async def settings_page(request: Request, current_user: User = Depends(get_current_user)):
    settings = get_settings()
    m = settings.max_hr
    z1 = f"{round(m * 0.5)}-{round(m * 0.6)}"
    z2 = f"{round(m * 0.6)}-{round(m * 0.7)}"
    z3 = f"{round(m * 0.7)}-{round(m * 0.8)}"
    z4 = f"{round(m * 0.8)}-{round(m * 0.9)}"
    z5 = f"{round(m * 0.9)}-{round(m)}"
    pw_placeholder = '********' if settings.coros_password else ''
    user_name = current_user.name or current_user.telegram_username or "Бегун"
    user_header = f"👤 {user_name} | <a href='/auth/logout'>Выйти</a>"
    return templates.TemplateResponse(request, "settings.html", {
        "user_header": user_header,
        "max_hr": m, "weight": settings.weight, "z1": z1, "z2": z2, "z3": z3, "z4": z4, "z5": z5,
        "max_credible_pace": settings.max_credible_pace,
        "max_gps_jump_m": settings.max_gps_jump_m,
        "min_hr_for_fast_pace": settings.min_hr_for_fast_pace,
        "coros_email": settings.coros_email or '',
        "coros_password": pw_placeholder,
    })


# Удаление тренировки с сохранением метаданных (Delete training, save metadata for re-upload confirmation)
@app.post('/session/{session_id}/delete')
async def session_delete(session_id: int, db: Session = Depends(get_db),
                         current_user: User = Depends(get_current_user)):
    s = db.query(TrainingSession).filter(TrainingSession.id == session_id, TrainingSession.user_id == current_user.id).first()
    audit = AuditService(db)
    if s:
        segs = s.segments_json or []
        # Средний темп из сегментов (Compute average pace from segments)
        pace = None
        if segs:
            paces = [seg.get('pace_min_km') for seg in segs if seg.get('pace_min_km')]
            if paces:
                pace = round(sum(paces) / len(paces), 2)
        # Сохраняем метаданные тренировки перед удалением (Save training metadata before delete)
        deleted = DeletedTraining(
            user_id=current_user.id,
            begin_ts=s.begin_ts,
            total_distance_km=s.total_distance_km,
            avg_heart_rate=s.avg_heart_rate,
            max_heart_rate=s.max_heart_rate,
            training_type=s.training_type,
            duration_minutes=s.duration_minutes,
            avg_temperature=s.avg_temperature,
            elevation_gain=s.elevation_gain,
            avg_cadence=s.avg_cadence,
            training_effect=s.training_effect,
            vo2max=s.vo2max,
            calories=s.calories,
            avg_pace=pace,
        )
        db.add(deleted)
        db.delete(s)
        db.commit()
        logger.info("Тренировка #%s удалена, метаданные сохранены (Session #%s deleted, metadata saved)", session_id, session_id)
        audit.log_training_deleted(
            user_id=current_user.id,
            training_id=session_id,
            begin_ts=str(s.begin_ts) if s.begin_ts else None,
            distance_km=s.total_distance_km,
            training_type=s.training_type,
        )
    else:
        audit.log_event(
            event_type="training.delete_failed",
            message=f"Delete training failed: id={session_id} not found",
            severity="warning",
            user_id=current_user.id,
            metadata={"training_id": session_id},
        )
    return RedirectResponse(url='/', status_code=303)


# Сохранение настроек (Save settings)
@app.post('/settings')
async def settings_save(max_hr: int = Form(...), weight: float = Form(...),
                        max_credible_pace: float = Form(3.0),
                        max_gps_jump_m: float = Form(100.0),
                        min_hr_for_fast_pace: int = Form(130),
                        coros_email: str = Form(''),
                        coros_password: str = Form(''),
                        db: Session = Depends(get_db),
                        current_user: User = Depends(get_current_user)):
    from src.models import User, WeightMeasurement
    from datetime import datetime
    user = db.query(User).filter(User.id == current_user.id).first()
    audit = AuditService(db)
    if not user:
        user = User(id=current_user.id)
        db.add(user)
    old_weight = user.weight_kg
    old_max_hr = user.max_hr
    old_coros_email = user.coros_email
    user.max_hr = max_hr
    user.weight_kg = weight
    user.max_credible_pace = max_credible_pace
    user.max_gps_jump_m = max_gps_jump_m
    user.min_hr_for_fast_pace = min_hr_for_fast_pace
    user.coros_email = coros_email or None
    if coros_password and coros_password != '********':
        user.coros_password = encrypt(coros_password)
    elif not coros_email:
        user.coros_password = None
    if old_weight != weight:
        wm = WeightMeasurement(weight_kg=weight, measured_at=datetime.utcnow(), user_id=current_user.id)
        db.add(wm)
    db.commit()
    
    # Логируем изменения настроек (Log settings changes)
    changes = {}
    if old_max_hr != max_hr:
        changes['max_hr'] = {'old': old_max_hr, 'new': max_hr}
    if old_weight != weight:
        changes['weight_kg'] = {'old': old_weight, 'new': weight}
    if old_coros_email != (coros_email or None):
        changes['coros_email'] = {'old': old_coros_email, 'new': coros_email or None}
    if changes:
        audit.log_settings_changed(
            user_id=current_user.id,
            changes=changes,
        )
    
    return RedirectResponse(url='/', status_code=303)


# Просмотр лога операций (View operation log)
@app.get('/logs')
async def view_logs(lines: int = 100):
    from datetime import date
    from src.config import CONFIG
    log_filename = f"app_{date.today().isoformat()}.log"
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), CONFIG.LOG_FILE)
    # Fallback на сегодняшний ротированный файл (Fallback to today's rotated file)
    rotated_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", log_filename)
    
    # Ищем самый свежий лог-файл (Find most recent log file)
    chosen_path = None
    for path in [rotated_path, log_path]:
        if os.path.exists(path):
            chosen_path = path
            break
    
    if not chosen_path:
        return HTMLResponse("<html><body><h2>Лог пуст</h2></body></html>")
    
    with open(chosen_path, "r", encoding="utf-8") as f:
        all_lines = f.readlines()
    tail = all_lines[-lines:]
    html = "<html><head><meta charset='utf-8'><title>Лог операций</title>"
    html += "<style>body{font-family:monospace;font-size:13px;background:#1e1e1e;color:#d4d4d4;padding:20px}"
    html += ".INFO{color:#4ec9b0}.WARNING{color:#ce9178}.ERROR{color:#f44747}.DEBUG{color:#808080}"
    html += "a{color:#569cd6;text-decoration:none;margin-right:10px}</style></head><body>"
    html += f"<h2>📋 Лог операций ({os.path.basename(chosen_path)})</h2>"
    html += f"<p>Последние {len(tail)} строк (<a href='/logs?lines=50'>50</a> "
    html += f"<a href='/logs?lines=200'>200</a> <a href='/logs?lines=1000'>все</a>)</p>"
    html += "<pre>"
    for line in tail:
        level = "INFO" if "INFO" in line else ("WARNING" if "WARNING" in line else
                ("ERROR" if "ERROR" in line else "DEBUG"))
        html += f"<span class='{level}'>{line.strip()}</span>\n"
    html += "</pre></body></html>"
    return HTMLResponse(html)


# Синхронизация тренировок с Coros — запуск в фоне (Coros sync — background task)
@app.post('/coros/sync')
async def coros_sync(db: Session = Depends(get_db),
                     current_user: User = Depends(get_current_user)):
    from src.coros_client import CorosClient, CorosAuthError, CorosAPIError
    from src.parsers.fit_parser import parse_fit
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

    # Фоновая синхронизация Coros (Background Coros sync)
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

            # Фильтруем новые (не в БД)
            existing_times = {r[0] for r in db.query(TrainingSession.begin_ts).filter(TrainingSession.user_id == current_user.id).all()}
            # Проверка, импортирована ли тренировка (с окном ±120 с) (Check if training already imported with ±120s window)
            def already_imported(ts):
                for et in existing_times:
                    if et is not None and abs((et - ts).total_seconds()) < 120:
                        return True
                return False

            new_acts = [a for a in activities if not already_imported(a['start_time'])]
            if not new_acts:
                # Даже если ничего не импортировано, обновляем last_coros_sync
                # на последнюю активность из ответа API (Even if nothing imported,
                # advance last_coros_sync to latest activity from API response)
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

                    # Проверка, не удалялась ли эта тренировка ранее (Check if previously deleted)
                    bt_sync = data.get('begin_ts')
                    deleted_match_sync = None
                    if bt_sync:
                        all_del = db.query(DeletedTraining).filter(DeletedTraining.user_id == current_user.id).all()
                        for d in all_del:
                            if d.begin_ts and abs((d.begin_ts - bt_sync).total_seconds()) < 120:
                                deleted_match_sync = d
                                break
                    if deleted_match_sync:
                        # Сохраняем данные в _pending для показа модала (Store in _pending for confirmation modal)
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
            audit.log_coros_sync_failed(
                user_id=us.id,
                email=us.coros_email,
                error=str(e),
                source="web_coros_sync",
            )
        except CorosAPIError as e:
            progress['step'] = 'error'
            progress['message'] = f'Ошибка Coros API: {e}'
            progress['done'] = True
            logger.error("Coros API error: %s", e)
            audit.log_coros_sync_failed(
                user_id=us.id,
                email=us.coros_email,
                error=str(e),
                source="web_coros_sync",
            )
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
            audit.log_coros_sync_failed(
                user_id=us.id,
                email=us.coros_email,
                error=str(e),
                source="web_coros_sync",
            )
        finally:
            db.close()
    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return JSONResponse({'task_id': task_id, 'status': 'started'})

_AUTO_SYNC_LOCK = threading.Lock()
# Фоновый планировщик автосинхронизации (Background auto-sync scheduler)
def _start_auto_sync():
    import random

    with _AUTO_SYNC_LOCK:
        if hasattr(_start_auto_sync, '_started') and _start_auto_sync._started:
            return
        _start_auto_sync._started = True

    def _loop():
        logger.info("Автосинхронизация: запуск планировщика (health=%dс, activities=%dс)",
                     health_sync_interval, activity_sync_interval)
        time.sleep(30)

        last_health = 0.0
        last_activity = 0.0

        while True:
            now = time.time()
            try:
                if now - last_health >= health_sync_interval * random.uniform(0.8, 1.2):
                    logger.info("Автосинхронизация: health sync")
                    auto_sync_health()
                    last_health = time.time()
            except Exception:
                logger.exception("Автосинхронизация: ошибка health sync")

            try:
                if now - last_activity >= activity_sync_interval * random.uniform(0.8, 1.2):
                    logger.info("Автосинхронизация: activity sync")
                    auto_sync_activities()
                    last_activity = time.time()
            except Exception:
                logger.exception("Автосинхронизация: ошибка activity sync")

            time.sleep(300)

    thread = threading.Thread(target=_loop, daemon=True, name="coros-auto-sync")
    thread.start()
    logger.info("Автосинхронизация Coros: фоновый поток запущен")



# Статус фоновой синхронизации Coros (Background Coros sync status)
@app.get('/coros/sync/status/{task_id}')
async def coros_sync_status(task_id: str):
    with _sync_tasks_lock:
        p = _sync_tasks.get(task_id)
    if not p:
        return JSONResponse({'status': 'error', 'message': 'Task not found'})
    return JSONResponse(p)


# Синхронизация ежедневных метрик здоровья с Coros (Coros health metrics sync — sleep, HRV, recovery)
@app.post('/coros/sync/health')
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

    # Фоновая синхронизация метрик здоровья (Background health metrics sync)
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

            # Определяем диапазон дат для синхронизации (Determine date range for sync)
            existing_dates = {r[0] for r in db.query(DailyMetrics.date).filter(DailyMetrics.user_id == current_user.id).all()}
            from datetime import timedelta, date, datetime
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

            # Получение аналитики (12-week analytics for VO2max, LTHR, LTSP, stamina)
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

                # Мерж данных из dayDetail + аналитики (Merge dayDetail + analytics data)
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

            # Обновление существующих записей аналитикой (Update existing records with analytics)
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
            audit.log_coros_sync_failed(
                user_id=us.id,
                email=us.coros_email,
                error=str(e),
                source="web_coros_sync_health",
            )
        except CorosAPIError as e:
            progress['step'] = 'error'
            progress['message'] = f'Ошибка Coros API: {e}'
            progress['done'] = True
            logger.error("Coros API error: %s", e)
            audit.log_coros_sync_failed(
                user_id=us.id,
                email=us.coros_email,
                error=str(e),
                source="web_coros_sync_health",
            )
        except Exception as e:
            progress['step'] = 'error'
            progress['message'] = f'Ошибка: {type(e).__name__}: {e}'
            progress['done'] = True
            logger.error("Coros health sync error", exc_info=True)
            audit.log_coros_sync_failed(
                user_id=us.id,
                email=us.coros_email,
                error=str(e),
                source="web_coros_sync_health",
            )
        finally:
            db.close()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return JSONResponse({'task_id': task_id, 'status': 'started'})
