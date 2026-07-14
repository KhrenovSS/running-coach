# Главная страница: render_page + GET / (Index page)

import json
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from src.models import get_db, User, TrainingSession, DailyMetrics, WeightMeasurement, WatchCredential, TrainingFeedback, get_settings
from src.deps import templates
from src.api.deps import get_current_user
from src.services.stats import fmt_duration, calc_stats, render_zone_bars, render_type_row, build_nav_html
from src.services.recovery_view import hrv_status, tired_label, readiness_label
from src.services.sync import get_auto_sync_status_snapshot
from src.web.state import TRAINING_TYPES_RU

router = APIRouter()


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

    session_ids = [s.id for s in filtered]
    feedbacks = db.query(TrainingFeedback).filter(
        TrainingFeedback.session_id.in_(session_ids),
        TrainingFeedback.user_id == user_id,
    ).all()
    feedback_map = {fb.session_id: fb.rating for fb in feedbacks}

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

    now = datetime.now(timezone.utc)
    status_snapshot = get_auto_sync_status_snapshot()
    as_health = status_snapshot['health']
    as_activity = status_snapshot['activity']

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


@router.get('/', response_class=HTMLResponse)
async def index(request: Request, year: Optional[int] = None, month: Optional[int] = None, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    user_name = current_user.name or current_user.telegram_username or "Бегун"
    ctx = render_page(db, user_id=current_user.id, user_name=user_name, year=year, month=month, tz_str=current_user.timezone)
    return templates.TemplateResponse(request, "index.html", ctx)