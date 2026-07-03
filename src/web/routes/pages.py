# Роуты для страниц (Pages: login, register, index, session, settings)

from typing import Optional
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from src.models import get_db, User, TrainingSession, DailyMetrics, WeightMeasurement, DeletedTraining, WatchCredential, TrainingFeedback, get_settings
from src.utils.logger import get_logger
from src.deps import templates, local_dt
from src.api.deps import get_current_user
from src.config import settings
from src.services.auth import check_telegram_login_token
from src.services.audit import AuditService
from src.parsers.weather import weather_icon
from src.parsers.utils import format_pace, format_duration
from src.services.stats import fmt_duration, calc_stats, render_zone_bars, render_type_row, build_nav_html, MONTHS_RU, MONTHS_RU_SHORT
from src.services.recovery_view import hrv_status, tired_label, readiness_label, load_label
from src.services.sync_service import _auto_sync_status, _auto_sync_status_lock
from src.web.state import _pending, TRAINING_TYPES_RU
from src.crypto import encrypt
import json
from pathlib import Path
from datetime import timezone
from zoneinfo import ZoneInfo

logger = get_logger("app")
router = APIRouter()

_AUTH_ERRORS = {
    "invalid_token": "Ссылка устарела или недействительна. Запросите новую через /start в Telegram.",
    "invalid_credentials": "Неверный email или пароль.",
    "short_password": "Пароль слишком короткий (минимум 6 символов).",
    "password_mismatch": "Пароли не совпадают.",
    "email_taken": "Этот email уже используется.",
}


def render_page(db, user_id: int, user_name: str = "Бегун", year=None, month=None, tz_str=None):
    all_sessions = db.query(TrainingSession).filter(TrainingSession.user_id == user_id).order_by(TrainingSession.begin_ts.desc()).all()
    settings = get_settings()
    weight_measurements = db.query(WeightMeasurement).filter(WeightMeasurement.user_id == user_id).order_by(WeightMeasurement.measured_at).all()
    recovery_metrics = db.query(DailyMetrics).filter(DailyMetrics.user_id == user_id).order_by(DailyMetrics.date.desc()).limit(30).all()

    weight_json = json.dumps([{'date': wm.measured_at.strftime('%Y-%m-%d'), 'weight': wm.weight_kg} for wm in weight_measurements])
    recovery_json = json.dumps([{'date': rm.date.strftime('%Y-%m-%d'), 'rhr': rm.rhr} for rm in reversed(recovery_metrics)])

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

    nav_html = ""
    sel_year, sel_month = year, month
    if all_sessions:
        nav_result = build_nav_html(all_sessions, sel_year, sel_month)
        if nav_result:
            nav_html, sel_year, sel_month = nav_result

    if sel_year and sel_month:
        filtered = [s for s in all_sessions if s.begin_ts and s.begin_ts.year == sel_year and s.begin_ts.month == sel_month]
    else:
        filtered = all_sessions[:20]

    # Загружаем оценки тренировок (Load training feedback ratings)
    session_ids = [s.id for s in filtered]
    feedbacks = db.query(TrainingFeedback).filter(
        TrainingFeedback.session_id.in_(session_ids),
        TrainingFeedback.user_id == user_id,
    ).all()
    feedback_map = {fb.session_id: fb.rating for fb in feedbacks}

    # Баннер для нового пользователя (New user banner — has credentials but no training sessions)
    has_creds = db.query(WatchCredential).filter(
        WatchCredential.user_id == user_id,
        WatchCredential.is_active == True,
    ).first()
    has_trainings = db.query(TrainingSession).filter(TrainingSession.user_id == user_id).first()
    new_user_banner = bool(has_creds and not has_trainings)

    rows = ""
    for s in filtered:
        if s.begin_ts:
            tz_name = tz_str or s.timezone or "Europe/Moscow"
            local_begin = s.begin_ts.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz_name))
            t = local_begin.strftime("%d.%m.%Y %H:%M")
        else:
            t = ""
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
        rating = feedback_map.get(s.id)
        rating_str = f"⭐ {rating}/10" if rating is not None else ""
        rows += f"<tr onclick=\"window.location='/session/{s.id}'\" style='cursor:pointer'>"
        rows += f"<td>{warn} {t}</td><td>{dur}</td><td>{s.total_distance_km:.2f}</td><td>{s.avg_heart_rate}</td>"
        rows += f"<td>{TRAINING_TYPES_RU.get(s.training_type, s.training_type)}</td><td>{cad_str}</td><td>{elev_str}</td><td>{extra_str}</td><td>{rating_str}</td></tr>"

    if not rows:
        rows = "<tr><td colspan='9' style='color:#888;padding:30px;'>Нет тренировок за выбранный период</td></tr>"

    week_bars = render_zone_bars(week_stats['zone_min'], week_stats['total_min'], settings.max_hr) if week_stats else ""
    month_bars = render_zone_bars(month_stats['zone_min'], month_stats['total_min'], settings.max_hr) if month_stats else ""
    week_types = render_type_row(week_stats['type_count']) if week_stats else ""
    month_types = render_type_row(month_stats['type_count']) if month_stats else ""

    latest_rm = recovery_metrics[0] if recovery_metrics else None
    if latest_rm:
        _, latest_hrv = hrv_status(latest_rm.avg_sleep_hrv, latest_rm.sleep_hrv_baseline, latest_rm.sleep_hrv_sd,
            json.loads(latest_rm.sleep_hrv_interval_list) if latest_rm.sleep_hrv_interval_list else None)
        latest_rhr = str(latest_rm.rhr) if latest_rm.rhr is not None else ''
        latest_tired = tired_label(latest_rm.tired_rate)
        latest_perf = readiness_label(latest_rm.performance, latest_rm.recovery_pct, latest_rm.training_load_ratio)
        latest_recovery_pct = f'{latest_rm.recovery_pct}%' if latest_rm.recovery_pct is not None else ''
    else:
        latest_hrv = latest_rhr = latest_tired = latest_perf = latest_recovery_pct = ''

    from datetime import datetime
    now = datetime.now(timezone.utc)
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
        "new_user_banner": new_user_banner,
    }


@router.get('/login', response_class=HTMLResponse)
async def login_page(request: Request, error: Optional[str] = None):
    if request.session.get("user_id"):
        return RedirectResponse(url="/", status_code=303)
    err_msg = _AUTH_ERRORS.get(error, "")
    err_html = f'<div class="auth-error">{err_msg}</div>' if err_msg else ''
    return templates.TemplateResponse(request, "login.html", {"err_html": err_html})


@router.get('/register', response_class=HTMLResponse)
async def register_page(request: Request, token: str = "", error: Optional[str] = None, db: Session = Depends(get_db)):
    if not token:
        return RedirectResponse(url="/login?error=invalid_token", status_code=303)
    user = check_telegram_login_token(db, token)
    if not user:
        return RedirectResponse(url="/login?error=invalid_token", status_code=303)
    if user.password_hash:
        return RedirectResponse(url="/login?error=invalid_token", status_code=303)
    err_msg = _AUTH_ERRORS.get(error, "")
    err_html = f'<div class="auth-error">{err_msg}</div>' if err_msg else ''
    return templates.TemplateResponse(request, "register.html", {
        "err_html": err_html, "token": token,
        "password_min_length": settings.password_min_length,
    })


@router.get('/', response_class=HTMLResponse)
async def index(request: Request, year: Optional[int] = None, month: Optional[int] = None, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    user_name = current_user.name or current_user.telegram_username or "Бегун"
    ctx = render_page(db, user_id=current_user.id, user_name=user_name, year=year, month=month, tz_str=current_user.timezone)
    return templates.TemplateResponse(request, "index.html", ctx)


@router.get('/session/{session_id}', response_class=HTMLResponse)
async def session_detail(request: Request, session_id: int, db: Session = Depends(get_db),
                         current_user: User = Depends(get_current_user)):
    s = db.query(TrainingSession).filter(TrainingSession.id == session_id, TrainingSession.user_id == current_user.id).first()
    if not s:
        return HTMLResponse("<h2>Тренировка не найдена</h2><a href='/'>Назад</a>", status_code=404)

    recovery_info = None
    if s.begin_ts:
        tz_name = current_user.timezone or s.timezone or "Europe/Moscow"
        local_begin = s.begin_ts.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz_name))
        training_date = local_begin.date()
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

    # Загружаем оценку тренировки (Load training feedback rating)
    fb = db.query(TrainingFeedback).filter(
        TrainingFeedback.session_id == session_id,
        TrainingFeedback.user_id == current_user.id,
    ).first()
    rating = fb.rating if fb else None
    rating_display = f"⭐ {rating}/10" if fb else "—"

    user_name = current_user.name or current_user.telegram_username or "Бегун"
    user_header = f"👤 {user_name} | <a href='/auth/logout'>Выйти</a>"
    return templates.TemplateResponse(request, "session.html", {
        "user_header": user_header,
        "session_id": s.id,
        "rating": rating,
        "suspect_badge": suspect_badge,
        "suspect_detail": suspect_detail,
        "type_ru": TRAINING_TYPES_RU.get(s.training_type, s.training_type),
        "date": local_begin.strftime("%d.%m.%Y %H:%M") if s.begin_ts else "",
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
        "rating_display": rating_display,
    })


@router.get('/settings', response_class=HTMLResponse)
async def settings_page(request: Request, current_user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    settings = get_settings()
    m = settings.max_hr
    z1 = f"{round(m * 0.5)}-{round(m * 0.6)}"
    z2 = f"{round(m * 0.6)}-{round(m * 0.7)}"
    z3 = f"{round(m * 0.7)}-{round(m * 0.8)}"
    z4 = f"{round(m * 0.8)}-{round(m * 0.9)}"
    z5 = f"{round(m * 0.9)}-{round(m)}"
    # Читаем email из WatchCredential (Read email from WatchCredential)
    cred = db.query(WatchCredential).filter(
        WatchCredential.user_id == current_user.id,
        WatchCredential.brand == 'coros',
    ).first()
    coros_email = cred.encrypted_user if cred else ''
    pw_placeholder = '********' if cred and cred.encrypted_password else ''
    # Значения интервалов синхронизации (Sync interval values)
    coros_activity_interval = cred.activity_sync_interval if cred and cred.activity_sync_interval else ''
    coros_health_interval = cred.health_sync_interval if cred and cred.health_sync_interval else ''
    user_name = current_user.name or current_user.telegram_username or "Бегун"
    user_header = f"👤 {user_name} | <a href='/auth/logout'>Выйти</a>"
    return templates.TemplateResponse(request, "settings.html", {
        "user_header": user_header,
        "max_hr": m, "weight": settings.weight, "z1": z1, "z2": z2, "z3": z3, "z4": z4, "z5": z5,
        "max_credible_pace": settings.max_credible_pace,
        "max_gps_jump_m": settings.max_gps_jump_m,
        "min_hr_for_fast_pace": settings.min_hr_for_fast_pace,
        "coros_email": coros_email,
        "coros_password": pw_placeholder,
        "coros_activity_sync_interval": coros_activity_interval,
        "coros_health_sync_interval": coros_health_interval,
    })


@router.post('/session/{session_id}/delete')
async def session_delete(session_id: int, db: Session = Depends(get_db),
                         current_user: User = Depends(get_current_user)):
    s = db.query(TrainingSession).filter(TrainingSession.id == session_id, TrainingSession.user_id == current_user.id).first()
    audit = AuditService(db)
    if s:
        segs = s.segments_json or []
        pace = None
        if segs:
            paces = [seg.get('pace_min_km') for seg in segs if seg.get('pace_min_km')]
            if paces:
                pace = round(sum(paces) / len(paces), 2)
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


# Сохранить оценку тренировки (Save training rating) — POST /session/{session_id}/feedback
@router.post('/session/{session_id}/feedback')
async def session_feedback(session_id: int, rating: int = Form(...),
                           db: Session = Depends(get_db),
                           current_user: User = Depends(get_current_user)):
    # Проверяем, что тренировка принадлежит пользователю (Verify session belongs to user)
    s = db.query(TrainingSession).filter(
        TrainingSession.id == session_id,
        TrainingSession.user_id == current_user.id,
    ).first()
    if not s:
        return HTMLResponse("<h2>Тренировка не найдена</h2><a href='/'>Назад</a>", status_code=404)

    # Клипим rating в 0–10 (Clamp rating to 0–10)
    rating = max(0, min(10, rating))

    # Upsert оценки (Upsert training feedback)
    fb = db.query(TrainingFeedback).filter(
        TrainingFeedback.session_id == session_id,
        TrainingFeedback.user_id == current_user.id,
    ).first()
    audit = AuditService(db)
    if fb:
        old_rating = fb.rating
        fb.rating = rating
        db.commit()
        logger.info("Оценка тренировки #%s обновлена: %s → %s (Rating updated)", session_id, old_rating, rating)
        audit.log_event(
            event_type="feedback.updated",
            message=f"Session #{session_id} rating updated: {old_rating} → {rating}",
            severity="info",
            user_id=current_user.id,
            metadata={"session_id": session_id, "old_rating": old_rating, "new_rating": rating},
        )
    else:
        fb = TrainingFeedback(
            session_id=session_id,
            user_id=current_user.id,
            rating=rating,
        )
        db.add(fb)
        db.commit()
        logger.info("Оценка тренировки #%s сохранена: %s (Rating created)", session_id, rating)
        audit.log_event(
            event_type="feedback.created",
            message=f"Session #{session_id} rating created: {rating}/10",
            severity="info",
            user_id=current_user.id,
            metadata={"session_id": session_id, "rating": rating},
        )

    return RedirectResponse(url=f'/session/{session_id}', status_code=303)


@router.post('/settings')
async def settings_save(max_hr: int = Form(...), weight: float = Form(...),
                        max_credible_pace: float = Form(3.0),
                        max_gps_jump_m: float = Form(100.0),
                        min_hr_for_fast_pace: int = Form(130),
                        coros_email: str = Form(''),
                        coros_password: str = Form(''),
                        coros_activity_sync_interval: int = Form(None),
                        coros_health_sync_interval: int = Form(None),
                        db: Session = Depends(get_db),
                        current_user: User = Depends(get_current_user)):
    from src.models import User, WeightMeasurement, WatchCredential
    from datetime import datetime, timezone
    user = db.query(User).filter(User.id == current_user.id).first()
    audit = AuditService(db)
    if not user:
        user = User(id=current_user.id)
        db.add(user)
    old_weight = user.weight_kg
    old_max_hr = user.max_hr

    # Читаем старый email из WatchCredential (Read old email from WatchCredential)
    old_cred = db.query(WatchCredential).filter(
        WatchCredential.user_id == current_user.id,
        WatchCredential.brand == 'coros',
    ).first()
    old_coros_email = old_cred.encrypted_user if old_cred else ''

    user.max_hr = max_hr
    user.weight_kg = weight
    user.max_credible_pace = max_credible_pace
    user.max_gps_jump_m = max_gps_jump_m
    user.min_hr_for_fast_pace = min_hr_for_fast_pace

    # Сохраняем credentials в WatchCredential (Save credentials to WatchCredential)
    if coros_email:
        cred = db.query(WatchCredential).filter(
            WatchCredential.user_id == current_user.id,
            WatchCredential.brand == 'coros',
        ).first()
        if not cred:
            cred = WatchCredential(
                user_id=current_user.id,
                brand='coros',
                encrypted_user=coros_email,
            )
            db.add(cred)
        cred.encrypted_user = coros_email
        if coros_password and coros_password != '********':
            cred.encrypted_password = encrypt(coros_password)
        # Сохраняем интервалы синхронизации (Save sync intervals)
        from src.config.constants import MIN_ACTIVITY_SYNC_INTERVAL_MIN, MIN_HEALTH_SYNC_INTERVAL_MIN, MAX_SYNC_INTERVAL_MIN
        if coros_activity_sync_interval is not None and coros_activity_sync_interval > 0:
            cred.activity_sync_interval = max(MIN_ACTIVITY_SYNC_INTERVAL_MIN, min(coros_activity_sync_interval, MAX_SYNC_INTERVAL_MIN))
        if coros_health_sync_interval is not None and coros_health_sync_interval > 0:
            cred.health_sync_interval = max(MIN_HEALTH_SYNC_INTERVAL_MIN, min(coros_health_sync_interval, MAX_SYNC_INTERVAL_MIN))
    else:
        cred = db.query(WatchCredential).filter(
            WatchCredential.user_id == current_user.id,
            WatchCredential.brand == 'coros',
        ).first()
        if cred:
            db.delete(cred)
    if old_weight != weight:
        wm = WeightMeasurement(weight_kg=weight, measured_at=datetime.now(timezone.utc), user_id=current_user.id)
        db.add(wm)
    db.commit()

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
