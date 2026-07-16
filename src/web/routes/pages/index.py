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
from src.services.stats import fmt_duration, calc_stats, get_zone_bars_data, MONTHS_RU
from src.config import settings
from src.services.recovery_view import hrv_status, tired_label, readiness_label
from src.services.sync import get_auto_sync_status_snapshot
from src.web.state import TRAINING_TYPES_RU

router = APIRouter()


def _format_type_row(type_count):
    """Форматировать строку с типами тренировок (Format training type row)"""
    labels = {'interval': 'Интервальная', 'tempo': 'Темповая', 'long': 'Длинная', 'recovery': 'Восстановительная'}
    parts = []
    for key, label in labels.items():
        c = type_count.get(key, 0)
        if c:
            parts.append(f"{label}: {c}")
    return ", ".join(parts) if parts else "—"


def _build_nav(nav_items, sel_year, sel_month):
    """Построить навигацию по годам/месяцам из списка begin_ts (Build year/month nav from begin_ts list)"""
    years: dict[int, set[int]] = {}
    for (begin_ts,) in nav_items:
        y, m = begin_ts.year, begin_ts.month
        if y not in years:
            years[y] = set()
        years[y].add(m)

    if not years:
        return {}, None, None, ""

    sorted_years = sorted(years.keys(), reverse=True)
    if sel_year is None or sel_year not in years:
        sel_year = sorted_years[0]
    if sel_month is None or sel_month not in years[sel_year]:
        sel_month = max(years[sel_year])

    if sel_year and sel_month:
        title = f'Тренировки за {MONTHS_RU[sel_month]} {sel_year}'
    elif sel_year:
        title = f'Тренировки за {sel_year} год'
    else:
        title = 'Все тренировки'

    years_data: dict[int, list[int]] = {y: sorted(years[y]) for y in sorted_years}
    return years_data, sel_year, sel_month, title


def render_page(db, user_id: int, user_name: str = "Бегун", year=None, month=None, tz_str=None):
    recent_sessions = db.query(TrainingSession).filter(
        TrainingSession.user_id == user_id
    ).order_by(TrainingSession.begin_ts.desc()).limit(200).all()
    settings = get_settings()
    weight_measurements = db.query(WeightMeasurement).filter(
        WeightMeasurement.user_id == user_id
    ).order_by(WeightMeasurement.measured_at).limit(365).all()
    recovery_metrics = db.query(DailyMetrics).filter(DailyMetrics.user_id == user_id).order_by(DailyMetrics.date.desc()).limit(30).all()

    weight_json = json.dumps([{'date': wm.measured_at.strftime('%Y-%m-%d'), 'weight': wm.weight_kg} for wm in weight_measurements])
    recovery_json = json.dumps([{'date': rm.date.strftime('%Y-%m-%d'), 'rhr': rm.rhr} for rm in reversed(recovery_metrics)])

    latest = recent_sessions[0].begin_ts if recent_sessions else None
    week_stats = month_stats = None
    if latest:
        week_cut = latest - timedelta(days=7)
        month_cut = latest - timedelta(days=30)
        week_sessions = [s for s in recent_sessions if s.begin_ts >= week_cut]
        month_sessions = [s for s in recent_sessions if s.begin_ts >= month_cut]
        week_stats = calc_stats(week_sessions)
        month_stats = calc_stats(month_sessions)

    nav_items = db.query(TrainingSession.begin_ts).filter(
        TrainingSession.user_id == user_id,
        TrainingSession.begin_ts.isnot(None),
    ).all()
    nav_years, sel_year, sel_month, nav_title = _build_nav(nav_items, year, month)

    if sel_year and sel_month:
        month_start = datetime(sel_year, sel_month, 1, tzinfo=timezone.utc)
        if sel_month == 12:
            month_end = datetime(sel_year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            month_end = datetime(sel_year, sel_month + 1, 1, tzinfo=timezone.utc)
        filtered = db.query(TrainingSession).filter(
            TrainingSession.user_id == user_id,
            TrainingSession.begin_ts >= month_start,
            TrainingSession.begin_ts < month_end,
        ).order_by(TrainingSession.begin_ts.desc()).all()
    else:
        filtered = recent_sessions[:20]

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
            tz_name = tz_str or s.timezone or settings.timezone
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

    week_zones = get_zone_bars_data(week_stats['zone_min'], week_stats['total_min'], settings.max_hr) if week_stats else []
    month_zones = get_zone_bars_data(month_stats['zone_min'], month_stats['total_min'], settings.max_hr) if month_stats else []
    week_types = _format_type_row(week_stats['type_count']) if week_stats else ""
    month_types = _format_type_row(month_stats['type_count']) if month_stats else ""

    latest_rm = recovery_metrics[0] if recovery_metrics else None
    if latest_rm:
        _, latest_hrv = hrv_status(latest_rm.avg_sleep_hrv, latest_rm.sleep_hrv_baseline, latest_rm.sleep_hrv_sd,
            latest_rm.sleep_hrv_interval_list)
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
        "nav_years": nav_years,
        "nav_sel_year": sel_year,
        "nav_sel_month": sel_month,
        "nav_title": nav_title,
        "user_header": user_header,
        "max_hr": settings.max_hr,
        "weight": settings.weight,
        "week_km": week_stats['total_km'] if week_stats else 0,
        "week_dur": week_stats['total_dur'] if week_stats else "",
        "week_zones": week_zones,
        "week_types": week_types,
        "month_km": month_stats['total_km'] if month_stats else 0,
        "month_dur": month_stats['total_dur'] if month_stats else "",
        "month_zones": month_zones,
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