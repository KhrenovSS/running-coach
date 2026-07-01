# Импорт FastAPI и компонентов (FastAPI and component imports)
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
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

# Создание экземпляра FastAPI (Create FastAPI app instance)
app = FastAPI(title="AI Running Coach")
register_middleware(app)
app.include_router(health_router)
app.include_router(auth_router)
os.makedirs("uploads", exist_ok=True)

# Хранилище для загруженных TCX, ожидающих подтверждения (Pending uploads awaiting user confirmation)
PENDING_DIR = Path("/tmp/opencode/uploads")
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

# Отправить уведомление пользователю в Telegram (Send notification to user via Telegram)
def _telegram_notify(user_id: int, text: str, reply_markup: dict = None):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        return
    db = SessionLocal()
    audit = AuditService(db)
    try:
        from src.models import User
        user = db.query(User).filter(User.id == user_id, User.telegram_chat_id.isnot(None)).first()
        if not user:
            return
        try:
            payload = {"chat_id": user.telegram_chat_id, "text": text, "parse_mode": "Markdown"}
            if reply_markup:
                payload["reply_markup"] = reply_markup
            with httpx.Client(timeout=5) as client:
                response = client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json=payload,
                )
                if response.status_code == 400:
                    logger.warning("Telegram notify retry without Markdown (400 error)")
                    payload.pop("parse_mode")
                    response = client.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        json=payload,
                    )
                response.raise_for_status()
            audit.log_telegram_sent(
                user_id=user.id,
                chat_id=user.telegram_chat_id,
                message_preview=text[:100],
                source="main_telegram_notify",
            )
        except Exception as e:
            logger.warning("Telegram notify error: %s", e)
            audit.log_telegram_failed(
                user_id=user.id,
                chat_id=user.telegram_chat_id,
                error=str(e),
                message_preview=text[:100],
                source="main_telegram_notify",
            )
    finally:
        db.close()

# Цвета для пульсовых зон (Heart rate zone colors)
ZONE_COLORS = ['', '#e8f5e9', '#c8e6c9', '#fff3e0', '#ffccbc', '#ffcdd2']

# Форматирование длительности в человекочитаемый вид (Format duration for display)
def fmt_duration(minutes):
    if not minutes:
        return ""
    m = int(minutes)
    if m >= 60:
        h = m // 60
        rest = m % 60
        return f"{h}ч {rest}мин" if rest else f"{h}ч"
    return f"{m}мин"

# Расчёт статистики по списку тренировок (Calculate statistics for a list of sessions)
def calc_stats(sessions):
    total_km = 0.0
    total_duration_min = 0.0
    zone_min = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0}
    type_count = {}
    for s in sessions:
        total_km += s.total_distance_km or 0
        total_duration_min += s.duration_minutes or 0
        t = s.training_type
        type_count[t] = type_count.get(t, 0) + 1
        for seg in (s.segments_json or []):
            z = seg.get('zone')
            d = seg.get('duration_min', 0)
            if z and d:
                zone_min[z] = zone_min.get(z, 0) + d
    return {
        'total_km': round(total_km, 1),
        'total_dur': fmt_duration(total_duration_min),
        'total_min': round(total_duration_min),
        'zone_min': zone_min,
        'type_count': type_count,
    }

# Расчёт диапазонов пульсовых зон (Calculate heart rate zone ranges)
def zone_ranges(max_hr):
    r = {}
    r[1] = f"≤{round(0.70 * max_hr)}"
    r[2] = f"{round(0.70 * max_hr) + 1}–{round(0.80 * max_hr)}"
    r[3] = f"{round(0.80 * max_hr) + 1}–{round(0.87 * max_hr)}"
    r[4] = f"{round(0.87 * max_hr) + 1}–{round(0.93 * max_hr)}"
    r[5] = f"{round(0.93 * max_hr) + 1}–{max_hr}"
    return r

# Рендер HTML-полосок пульсовых зон (Render zone bar HTML)
def render_zone_bars(zone_min, total_min, max_hr):
    if not total_min:
        return ""
    bars = ""
    colors = {1: '#e8f5e9', 2: '#c8e6c9', 3: '#fff3e0', 4: '#ffccbc', 5: '#ffcdd2'}
    zr = zone_ranges(max_hr)
    for z in range(1, 6):
        val = zone_min.get(z, 0)
        pct = round(val / total_min * 100) if total_min else 0
        bars += f"<div style='display:flex;align-items:center;gap:6px;margin:3px 0;white-space:nowrap'><div style='width:90px;font-size:12px'>{zr[z]} уд/мин</div><div style='height:20px;width:{pct}%;background:{colors[z]};border-radius:4px;min-width:4px'></div><div style='font-size:12px;color:#666;margin-left:4px'>{fmt_duration(val)}</div></div>"
    return bars

# Рендер строки с количеством тренировок по типам (Render training type count row)
def render_type_row(type_count):
    labels = {'interval': 'Интервальная', 'tempo': 'Темповая', 'long': 'Длинная', 'recovery': 'Восстановительная'}
    parts = []
    for key, label in labels.items():
        c = type_count.get(key, 0)
        if c:
            parts.append(f"{label}: {c}")
    return ", ".join(parts) if parts else "—"

# Названия месяцев (Month names in Russian)
MONTHS_RU = ['', 'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
             'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']
MONTHS_RU_SHORT = ['', 'Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн',
                   'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек']

# Построить навигацию по годам/месяцам (Build year/month navigation)
def build_nav_html(all_sessions, sel_year, sel_month):
    # Собираем уникальные (год, месяц) из всех тренировок
    years = {}
    for s in all_sessions:
        if s.begin_ts is None:
            continue
        y, m = s.begin_ts.year, s.begin_ts.month
        if y not in years:
            years[y] = set()
        years[y].add(m)

    if not years:
        return ""

    sorted_years = sorted(years.keys(), reverse=True)

    # Если год/месяц не указаны — выбираем последний месяц с данными
    if sel_year is None or sel_year not in years:
        sel_year = sorted_years[0]
    if sel_month is None or sel_month not in years[sel_year]:
        sel_month = max(years[sel_year])

    html = '<div class="ym-nav">'

    # Строка годов (Year row)
    html += '<div class="year-row">'
    for y in sorted_years:
        cls = 'ym-pill active-year' if y == sel_year else 'ym-pill'
        html += f'<a href="/?year={y}" class="{cls}">{y}</a>'
    html += '</div>'

    # Строка месяцев (Month row)
    html += '<div class="month-row">'
    for m in sorted(years[sel_year]):
        cls = 'ym-pill active-month' if m == sel_month else 'ym-pill'
        html += f'<a href="/?year={sel_year}&month={m}" class="{cls}">{MONTHS_RU_SHORT[m]}</a>'
    html += '</div>'

    # Заголовок (Title)
    if sel_year and sel_month:
        title = f'Тренировки за {MONTHS_RU[sel_month]} {sel_year}'
    elif sel_year:
        title = f'Тренировки за {sel_year} год'
    else:
        title = 'Все тренировки'
    html += f'<div class="ym-title">{title}</div>'
    html += '</div>'

    return html, sel_year, sel_month


# Классификация метрик здоровья для отображения (Health metrics display helpers)
def _hrv_status(hrv, baseline, sd, intervals=None):
    """Классификация HRV: Повышенная/Норма/Пониженная/Низкая (Classify HRV level)"""
    if hrv is None:
        return None, ''
    # Если есть Coros-интервалы [min, low, normal_start, normal_end] — используем их (Use Coros intervals when available)
    if intervals and len(intervals) >= 4:
        if hrv < intervals[0]:
            return 'very_low', f'🔴 Низкая ({hrv:.0f})'
        elif hrv < intervals[2]:
            return 'low', f'🟡 Пониженная ({hrv:.0f})'
        elif hrv <= intervals[3]:
            return 'normal', f'🟢 Норма ({hrv:.0f})'
        else:
            return 'elevated', f'🟣 Повышенная ({hrv:.0f})'
    # Fallback: SD-based классификация (SD-based classification)
    if baseline is None or baseline == 0:
        return None, f'{hrv:.0f}'
    if sd is None or sd == 0:
        sd = baseline * 0.2
    if hrv > baseline + sd:
        return 'elevated', f'🟣 Повышенная ({hrv:.0f})'
    elif hrv >= baseline - sd:
        return 'normal', f'🟢 Норма ({hrv:.0f})'
    elif hrv >= baseline - 2 * sd:
        return 'low', f'🟡 Пониженная ({hrv:.0f})'
    else:
        return 'very_low', f'🔴 Низкая ({hrv:.0f})'

def _tired_label(tired_rate):
    """Классификация уровня усталости (Classify tiredness level)"""
    if tired_rate is None:
        return ''
    if tired_rate <= -5:
        return '🟢 Низкая'
    elif tired_rate <= 0:
        return '🟡 Умеренная'
    else:
        return '🔴 Высокая'

def _readiness_label(performance, recovery_pct=None, training_load_ratio=None):
    """Классификация готовности к нагрузкам: приоритет recovery%, затем ATI/CTI ratio, затем performance (Classify readiness)"""
    if recovery_pct is not None:
        if recovery_pct >= 70:
            return '🟢 Готов к тренировкам'
        elif recovery_pct >= 30:
            return '🟡 Умеренная готовность'
        else:
            return '🔴 Требуется отдых'
    if training_load_ratio is not None:
        if training_load_ratio < 0.8:
            return '🟢 Низкая нагрузка'
        elif training_load_ratio <= 1.2:
            return '🟡 Оптимальная нагрузка'
        else:
            return '🔴 Перегрузка'
    if performance is None:
        return ''
    if performance > 0.5:
        return '🟢 Готов к тренировкам'
    elif performance > -0.5:
        return '🟡 Умеренная готовность'
    else:
        return '🔴 Требуется отдых'

def _load_label(training_load):
    """Классификация тренировочной нагрузки (Classify training load)"""
    if training_load is None:
        return ''
    if training_load < 50:
        return 'Лёгкая'
    elif training_load < 150:
        return 'Средняя'
    else:
        return 'Высокая'

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
        _, latest_hrv = _hrv_status(latest_rm.avg_sleep_hrv, latest_rm.sleep_hrv_baseline, latest_rm.sleep_hrv_sd,
            json.loads(latest_rm.sleep_hrv_interval_list) if latest_rm.sleep_hrv_interval_list else None)
        latest_rhr = str(latest_rm.rhr) if latest_rm.rhr is not None else ''
        latest_tired = _tired_label(latest_rm.tired_rate)
        latest_perf = _readiness_label(latest_rm.performance, latest_rm.recovery_pct, latest_rm.training_load_ratio)
        latest_recovery_pct = f'{latest_rm.recovery_pct}%' if latest_rm.recovery_pct is not None else ''
    else:
        latest_hrv = latest_rhr = latest_tired = latest_perf = ''
        latest_recovery_pct = ''

    # Статус автосинхронизации (Auto-sync status)
    from datetime import datetime
    now = datetime.now()
    with _AUTO_SYNC_STATUS_LOCK:
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
    return MAIN_HTML.format(
        rows=rows, nav_html=nav_html, user_header=user_header, max_hr=settings.max_hr, weight=settings.weight,
        week_km=week_stats['total_km'] if week_stats else 0,
        week_dur=week_stats['total_dur'] if week_stats else "",
        week_bars=week_bars,
        week_types=week_types,
        month_km=month_stats['total_km'] if month_stats else 0,
        month_dur=month_stats['total_dur'] if month_stats else "",
        month_bars=month_bars,
        month_types=month_types,
        weight_json=weight_json,
        recovery_json=recovery_json,
        latest_hrv=latest_hrv,
        latest_rhr=latest_rhr,
        latest_tired=latest_tired,
        latest_perf=latest_perf,
        latest_recovery_pct=latest_recovery_pct,
        auto_health_last=fmt_sync_time(as_health['last_run']),
        auto_health_next=fmt_next_sync(as_health['next_run']),
        auto_health_status=as_health['status'],
        auto_health_msg=as_health['message'],
        auto_activity_last=fmt_sync_time(as_activity['last_run']),
        auto_activity_next=fmt_next_sync(as_activity['next_run']),
        auto_activity_status=as_activity['status'],
        auto_activity_msg=as_activity['message'],
    )


MAIN_HTML = '''
<!DOCTYPE html>
<html lang='ru'>
<head>
    <meta charset='UTF-8'>
    <title>AI Running Coach</title>
    <script src='https://cdn.jsdelivr.net/npm/chart.js@4'></script>
    <style>
        body {{ font-family: sans-serif; max-width: 98%; margin: 20px 30px; line-height: 1.6; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
        th, td {{ padding: 10px; text-align: center; border-bottom: 1px solid #ddd; }}
        th {{ background: #4CAF50; color: white; }}
        tr:hover {{ background: #f1f1f1; }}
        h2, h3 {{ color: #333; }}
        .settings {{ background: #e8f5e9; padding: 15px; border-radius: 8px; margin-bottom: 20px; display: flex; gap: 20px; align-items: center; flex-wrap: wrap; }}
        .settings a {{ margin-left: auto; }}
        .btn {{ display: inline-block; padding: 6px 14px; background: #4CAF50; color: white; text-decoration: none; border-radius: 5px; font-size: 14px; border: none; cursor: pointer; }}
        .btn:hover {{ background: #45a049; }}
        input[type=number] {{ width: 70px; padding: 4px; }}
        .stats-grid {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 15px; margin: 15px 0; }}
        .stats-card {{ border: 1px solid #ddd; border-radius: 8px; padding: 15px; background: #fafafa; }}
        .stats-card h4 {{ margin: 0 0 8px 0; color: #4CAF50; }}
        .stats-summary {{ display: flex; gap: 15px; flex-wrap: wrap; font-size: 14px; margin-bottom: 10px; }}
        .stats-summary span {{ background: #e8f5e9; padding: 4px 10px; border-radius: 4px; }}
        .overlay {{ display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(255,255,255,0.9); z-index: 999; justify-content: center; align-items: center; flex-direction: column; }}
        .overlay.active {{ display: flex; }}
        .spinner {{ border: 4px solid #e0e0e0; border-top: 4px solid #4CAF50; border-radius: 50%; width: 40px; height: 40px; animation: spin 0.8s linear infinite; }}
        @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
        .sync-status {{ padding: 6px 10px; border-radius: 4px; margin-top: 6px; font-size: 13px; }}
        .sync-ok {{ background: #e8f5e9; color: #2e7d32; }}
        .sync-error {{ background: #ffebee; color: #c62828; }}
        .ym-nav {{ margin: 10px 0; }}
        .year-row, .month-row {{ display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 6px; }}
        .ym-pill {{ display: inline-block; padding: 4px 12px; border-radius: 14px; font-size: 13px;
                    text-decoration: none; color: #555; background: #f0f0f0; border: 1px solid #ddd; }}
        .ym-pill:hover {{ background: #e0e0e0; }}
        .active-year {{ background: #4CAF50; color: white; border-color: #4CAF50; }}
        .active-month {{ background: #2196F3; color: white; border-color: #2196F3; }}
        .ym-title {{ font-size: 14px; color: #666; margin-bottom: 8px; font-weight: bold; }}
        .modal {{ background: white; border-radius: 12px; padding: 20px; max-width: 500px; width: 90%; box-shadow: 0 4px 24px rgba(0,0,0,0.15); }}
        .modal h3 {{ margin-top: 0; }}
        .modal table {{ width: 100%; border-collapse: collapse; margin: 10px 0; }}
        .modal td {{ padding: 4px 8px; border-bottom: 1px solid #eee; }}
        .modal td:first-child {{ color: #666; width: 40%; }}
        .modal-buttons {{ display: flex; gap: 10px; justify-content: flex-end; margin-top: 16px; }}
        .btn-import {{ background: #4CAF50; color: white; padding: 8px 20px; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; }}
        .btn-skip {{ background: #f5f5f5; color: #333; padding: 8px 20px; border: 1px solid #ddd; border-radius: 6px; cursor: pointer; font-size: 14px; }}
        .btn-import:hover {{ background: #43a047; }}
        .btn-skip:hover {{ background: #e0e0e0; }}
    </style>
</head>
<body>
    <div class='overlay' id='uploadOverlay'>
        <div class='spinner'></div>
        <p style='margin-top:16px;font-size:18px;color:#333;'>Обработка файлов…</p>
        <p id='progressText' style='margin-top:8px;font-size:15px;color:#555;'></p>
        <div style='margin-top:12px;width:300px;background:#e0e0e0;border-radius:6px;height:10px;overflow:hidden;'>
            <div id='progressBar' style='width:0%;background:#4CAF50;border-radius:6px;height:10px;transition:width 0.3s;'></div>
        </div>
    </div>
    <div class='overlay' id='syncOverlay'>
        <div class='spinner'></div>
        <p style='margin-top:16px;font-size:18px;color:#333;' id='syncStatusText'>Синхронизация Coros…</p>
        <p id='syncProgressText' style='margin-top:8px;font-size:15px;color:#555;'></p>
        <div style='margin-top:12px;width:300px;background:#e0e0e0;border-radius:6px;height:10px;overflow:hidden;'>
            <div id='syncProgressBar' style='width:0%;background:#2196F3;border-radius:6px;height:10px;transition:width 0.3s;'></div>
        </div>
    </div>
    <div class='overlay' id='deletedConfirmOverlay'>
        <div class='modal'>
            <h3>⚠️ Тренировка была удалена</h3>
            <p style='color:#555;'>Эта тренировка ранее была удалена. Хотите импортировать её заново?</p>
            <div id='deletedDetails'></div>
            <div class='modal-buttons'>
                <button class='btn-skip' id='deletedSkipBtn'>Пропустить</button>
                <button class='btn-import' id='deletedImportBtn'>Импортировать</button>
            </div>
        </div>
    </div>

    <div style="display:flex;justify-content:space-between;align-items:center;margin:10px 0;">
        <h2 style="margin:0;">🏃 AI Running Coach</h2>
        <div>{user_header}</div>
    </div>

    <div class='settings'>
        <span><b>ЧССмакс:</b> {max_hr} уд/мин</span>
        <span id='weightToggle' style='cursor:pointer' onclick='toggleWeightChart()'><b>Вес:</b> {weight} кг ▾</span>
        <input type='file' name='files' accept='.tcx,.fit' multiple id='fileInput' style='display:none'>
        <button type='button' class='btn' onclick='document.getElementById("fileInput").click()'>&#128206; Загрузить TCX/FIT</button>
        <button type='button' class='btn' id='corosSyncBtn' style='background:#2196F3'>🔄 Coros Sync</button>
        <button type='button' class='btn' id='healthSyncBtn' style='background:#7B1FA2'>❤️ Health Sync</button>
        <a href='/settings' class='btn'>⚙️ Настройки</a>
        <div id='corosSyncStatus' style='width:100%;margin-top:6px;font-size:13px;'></div>
        <div id='healthSyncStatus' style='width:100%;margin-top:4px;font-size:13px;'></div>
    </div>
    <div id='weightChartContainer' style='display:none; margin-bottom:15px'>
        <div class='stats-card'>
            <h4>📉 Динамика веса</h4>
            <div style='max-height:300px; overflow-y:auto;'>
                <table style='margin-top:5px'>
                    <thead><tr><th>Дата</th><th>Вес, кг</th></tr></thead>
                    <tbody id='weightTableBody'></tbody>
                </table>
            </div>
            <canvas id='weightChart' height='100' style='margin-top:10px'></canvas>
        </div>
    </div>
    <script>
    // Функция для показа модала подтверждения удалённой тренировки (Show deleted training confirmation modal)
    function showDeletedModal(match, tempId) {{
        return new Promise((resolve) => {{
            const overlay = document.getElementById('deletedConfirmOverlay');
            const details = document.getElementById('deletedDetails');
            details.innerHTML = `
                <table>
                    <tr><td>Дата</td><td>${{match.date}}</td></tr>
                    <tr><td>Дистанция</td><td>${{match.distance_display || match.distance}}</td></tr>
                    <tr><td>Темп</td><td>${{match.pace}}</td></tr>
                    <tr><td>Длительность</td><td>${{match.duration}}</td></tr>
                    <tr><td>Тип</td><td>${{match.type}}</td></tr>
                    <tr><td>Пульс</td><td>${{match.hr}}</td></tr>
                    <tr><td>Калории</td><td>${{match.calories}}</td></tr>
                </table>`;
            overlay.classList.add('active');

            const skipBtn = document.getElementById('deletedSkipBtn');
            const importBtn = document.getElementById('deletedImportBtn');

            const cleanup = () => {{
                overlay.classList.remove('active');
                skipBtn.replaceWith(skipBtn.cloneNode(true));
                importBtn.replaceWith(importBtn.cloneNode(true));
            }};

            document.getElementById('deletedSkipBtn').onclick = () => {{ cleanup(); resolve(false); }};
            document.getElementById('deletedImportBtn').onclick = async () => {{
                cleanup();
                const fd = new FormData();
                fd.append('temp_id', tempId);
                try {{
                    const r = await fetch('/upload/confirm_deleted', {{ method: 'POST', body: fd }});
                    const j = await r.json();
                    resolve(j.ok);
                }} catch (e) {{
                    resolve(false);
                }}
            }};
        }});
    }}

    document.getElementById('fileInput').addEventListener('change', async function() {{
        if (!this.files.length) return;
        const files = Array.from(this.files);
        const total = files.length;
        let processed = 0;
        let allSaved = 0;

        const overlay = document.getElementById('uploadOverlay');
        const progressText = document.getElementById('progressText');
        const progressBar = document.getElementById('progressBar');

        overlay.classList.add('active');

        for (const file of files) {{
            const fd = new FormData();
            fd.append('files', file);
            try {{
                const resp = await fetch('/upload', {{ method: 'POST', body: fd }});
                const text = await resp.text();
                let j;
                try {{
                    j = JSON.parse(text);
                }} catch (e) {{
                    continue;
                }}
                // Если сервер обнаружил, что файл был ранее удалён (If server found this was previously deleted)
                if (j.deleted_match && j.temp_id) {{
                    const imported = await showDeletedModal(j.deleted_match, j.temp_id);
                    if (imported) {{
                        allSaved++;
                    }}
                }} else {{
                    allSaved += j.saved || 0;
                }}
            }} catch (e) {{
                // ignore network errors for individual files
            }}
            processed++;
            const pct = Math.round(processed / total * 100);
            progressText.textContent = `Обработано ${{processed}} из ${{total}} (${{pct}}%)`;
            progressBar.style.width = pct + '%';
        }}

        window.location.href = '/';
    }});
    </script>

    <div class='stats-grid'>
        <div class='stats-card'>
            <h4>Неделя (7 дней)</h4>
            <div class='stats-summary'>
                <span>📏 {week_km} км</span>
                <span>⏱ {week_dur}</span>
            </div>
            <div style='font-size:12px;color:#888;margin-bottom:4px'>Пульс</div>
            <div>{week_bars}</div>
            <div style='font-size:13px;color:#555;margin-top:6px'>{week_types}</div>
        </div>
        <div class='stats-card'>
            <h4>Месяц (30 дней)</h4>
            <div class='stats-summary'>
                <span>📏 {month_km} км</span>
                <span>⏱ {month_dur}</span>
            </div>
            <div style='font-size:12px;color:#888;margin-bottom:4px'>Пульс</div>
            <div>{month_bars}</div>
            <div style='font-size:13px;color:#555;margin-top:6px'>{month_types}</div>
        </div>
        <div class='stats-card' id='recoveryCard' onclick='toggleRecoveryChart()' style='cursor:pointer'>
            <h4>❤️ Восстановление</h4>
            <div class='stats-summary'>
                <span>Восстановление: <b>{latest_recovery_pct}</b></span>
                <span>Нервная система: <b>{latest_hrv}</b></span>
                <span>Пульс покоя: <b>{latest_rhr}</b> уд/мин</span>
                <span>Усталость: <b>{latest_tired}</b></span>
                <span>Состояние: <b>{latest_perf}</b></span>
            </div>
            <div style='font-size:13px;color:#888;margin-top:4px' id='recoveryToggle'>▾ График пульса покоя</div>
        </div>
    </div>
    <div id='recoveryChartContainer' style='display:none; margin-bottom:15px'>
        <div class='stats-card'>
            <h4>📈 Пульс покоя (RHR)</h4>
            <canvas id='recoveryChart' height='80'></canvas>
        </div>
    </div>

    <!-- Статус автосинхронизации Coros (Auto-sync status) -->
    <div class='sync-status' style='font-size:12px;color:#888;margin-bottom:15px;display:flex;gap:20px;flex-wrap:wrap;padding:8px 12px;background:#f9f9f9;border-radius:6px;'>
        <span>🔄 <b>Автосинхронизация:</b></span>
    <span>Health: <span id='autoHealthStatus' title='{auto_health_msg}'>{auto_health_status}</span>
          (последняя: {auto_health_last}, след.: {auto_health_next})</span>
    <span>Activities: <span id='autoActivityStatus' title='{auto_activity_msg}'>{auto_activity_status}</span>
          (последняя: {auto_activity_last}, след.: {auto_activity_next})</span>
    </div>

    <script>
    const recoveryData = {recovery_json};
    let recoveryChart = null;

    function toggleRecoveryChart() {{
        const container = document.getElementById('recoveryChartContainer');
        const toggle = document.getElementById('recoveryToggle');
        if (container.style.display === 'none') {{
            container.style.display = 'block';
            toggle.textContent = '▴ График пульса покоя';
            renderRecoveryChart();
        }} else {{
            container.style.display = 'none';
            toggle.textContent = '▾ График пульса покоя';
        }}
    }}

    function renderRecoveryChart() {{
        if (recoveryData.length < 2) return;
        if (recoveryChart) {{
            recoveryChart.destroy();
            recoveryChart = null;
        }}
        recoveryChart = new Chart(document.getElementById('recoveryChart'), {{
            type: 'line',
            data: {{
                labels: recoveryData.map(d => d.date),
                datasets: [{{
                    label: 'Пульс покоя (уд/мин)',
                    data: recoveryData.map(d => d.rhr),
                    borderColor: '#e53935',
                    backgroundColor: 'transparent',
                    tension: 0.4,
                    pointRadius: 4,
                    pointBackgroundColor: '#e53935',
                    pointBorderColor: '#fff',
                    pointBorderWidth: 2,
                    fill: true,
                    backgroundColor: 'rgba(229,57,53,0.08)',
                }}]
            }},
            options: {{
                responsive: true,
                scales: {{
                    x: {{ title: {{ display: true, text: 'Дата' }} }},
                    y: {{ title: {{ display: true, text: 'уд/мин' }}, beginAtZero: false }},
                }},
                plugins: {{ legend: {{ display: false }} }}
            }}
        }});
    }}

    const weightData = {weight_json};
    let weightChart = null;

    function toggleWeightChart() {{
        const container = document.getElementById('weightChartContainer');
        const toggle = document.getElementById('weightToggle');
        if (container.style.display === 'none') {{
            container.style.display = 'block';
            toggle.innerHTML = '<b>Вес:</b> {weight} кг ▴';
            renderWeightChart();
            renderWeightTable();
        }} else {{
            container.style.display = 'none';
            toggle.innerHTML = '<b>Вес:</b> {weight} кг ▾';
        }}
    }}

    function renderWeightTable() {{
        const tbody = document.getElementById('weightTableBody');
        tbody.innerHTML = weightData.map(d =>
            `<tr><td>${{d.date}}</td><td>${{d.weight}}</td></tr>`
        ).join('');
    }}

    function renderWeightChart() {{
        if (weightData.length < 2) return;
        if (weightChart) {{
            weightChart.destroy();
            weightChart = null;
        }}
        weightChart = new Chart(document.getElementById('weightChart'), {{
            type: 'line',
            data: {{
                labels: weightData.map(d => d.date),
                datasets: [{{
                    label: 'Вес (кг)',
                    data: weightData.map(d => d.weight),
                    borderColor: '#4CAF50',
                    backgroundColor: 'transparent',
                    tension: 0.4,
                    pointRadius: 5,
                    pointBackgroundColor: '#4CAF50',
                    pointBorderColor: '#fff',
                    pointBorderWidth: 2,
                }}]
            }},
            options: {{
                responsive: true,
                scales: {{
                    x: {{ title: {{ display: true, text: 'Дата' }} }},
                    y: {{ title: {{ display: true, text: 'кг' }}, beginAtZero: false }},
                }},
                plugins: {{ legend: {{ display: false }} }}
            }}
        }});
    }}
    </script>

    <script>
    async function syncCoros() {{
        const btn = document.getElementById('corosSyncBtn');
        const statusDiv = document.getElementById('corosSyncStatus');
        const overlay = document.getElementById('syncOverlay');
        const statusText = document.getElementById('syncStatusText');
        const progressText = document.getElementById('syncProgressText');
        const progressBar = document.getElementById('syncProgressBar');
        btn.disabled = true;
        btn.textContent = '🔄 Синхронизация…';
        statusDiv.className = 'sync-status';
        statusDiv.textContent = 'Запуск...';
        overlay.classList.add('active');
        statusText.textContent = 'Подключение к Coros...';
        progressText.textContent = '';
        progressBar.style.width = '0%';
        try {{
            const resp = await fetch('/coros/sync', {{ method: 'POST' }});
            const j = await resp.json();
            if (j.status !== 'started') {{
                overlay.classList.remove('active');
                statusDiv.className = 'sync-status sync-error';
                statusDiv.textContent = '❌ ' + (j.message || 'Ошибка запуска');
                btn.disabled = false;
                btn.textContent = '🔄 Coros Sync';
                return;
            }}
            const taskId = j.task_id;
            let done = false;
            while (!done) {{
                await new Promise(r => setTimeout(r, 800));
                const sr = await fetch('/coros/sync/status/' + taskId);
                const sp = await sr.json();
                statusText.textContent = sp.message || '';
                if (sp.total > 0) {{
                    const pct = Math.round(sp.current / sp.total * 100);
                    progressText.textContent = sp.current + ' из ' + sp.total;
                    progressBar.style.width = pct + '%';
                }}
                if (sp.step === 'done' || sp.step === 'error') {{
                    done = true;
                    overlay.classList.remove('active');
                    if (sp.step === 'error') {{
                        statusDiv.className = 'sync-status sync-error';
                        statusDiv.textContent = '❌ ' + (sp.message || 'Ошибка');
                    }} else if (sp.has_pending_deleted && sp.pending_deleted) {{
                        // Показываем модал для каждой удалённой тренировки (Show modal for each deleted training)
                        statusDiv.className = 'sync-status sync-ok';
                        statusDiv.textContent = '✅ Найдены ранее удалённые тренировки';
                        for (const pd of sp.pending_deleted) {{
                            const imported = await showDeletedModal(pd, pd.temp_id);
                            if (imported) {{
                                sp.synced = (sp.synced || 0) + 1;
                            }}
                        }}
                        statusDiv.textContent = '✅ Обработано: ' + (sp.synced || 0) + ' / ' + sp.pending_deleted.length;
                        window.location.href = '/';
                    }} else if (sp.synced > 0) {{
                        statusDiv.className = 'sync-status sync-ok';
                        statusDiv.textContent = '✅ Синхронизировано: ' + sp.synced;
                        if (sp.total_found) statusDiv.textContent += ' (найдено ' + sp.total_found + ')';
                        window.location.href = '/';
                    }} else {{
                        statusDiv.className = 'sync-status sync-ok';
                        statusDiv.textContent = '✅ ' + (sp.message || 'Новых тренировок нет');
                        setTimeout(() => {{ statusDiv.textContent = ''; }}, 5000);
                    }}
                }}
            }}
        }} catch (e) {{
            overlay.classList.remove('active');
            statusDiv.className = 'sync-status sync-error';
            statusDiv.textContent = '❌ ' + e.message;
        }} finally {{
            btn.disabled = false;
            btn.textContent = '🔄 Coros Sync';
        }}
    }}

    document.getElementById('corosSyncBtn').addEventListener('click', syncCoros);

    async function syncHealth() {{
        const btn = document.getElementById('healthSyncBtn');
        const statusDiv = document.getElementById('healthSyncStatus');
        const overlay = document.getElementById('syncOverlay');
        const statusText = document.getElementById('syncStatusText');
        const progressText = document.getElementById('syncProgressText');
        const progressBar = document.getElementById('syncProgressBar');
        btn.disabled = true;
        btn.textContent = '❤️ Синхронизация…';
        statusDiv.className = 'sync-status';
        statusDiv.textContent = 'Запуск...';
        overlay.classList.add('active');
        statusText.textContent = 'Подключение к Coros...';
        progressText.textContent = '';
        progressBar.style.width = '0%';
        try {{
            const resp = await fetch('/coros/sync/health', {{ method: 'POST' }});
            const j = await resp.json();
            if (j.status !== 'started') {{
                overlay.classList.remove('active');
                statusDiv.className = 'sync-status sync-error';
                statusDiv.textContent = '❌ ' + (j.message || 'Ошибка');
                btn.disabled = false;
                btn.textContent = '❤️ Health Sync';
                return;
            }}
            const taskId = j.task_id;
            let done = false;
            while (!done) {{
                await new Promise(r => setTimeout(r, 800));
                const sr = await fetch('/coros/sync/status/' + taskId);
                const sp = await sr.json();
                statusText.textContent = sp.message || '';
                if (sp.total > 0) {{
                    const pct = Math.round(sp.current / sp.total * 100);
                    progressText.textContent = sp.current + ' из ' + sp.total;
                    progressBar.style.width = pct + '%';
                }}
                if (sp.step === 'done' || sp.step === 'error') {{
                    done = true;
                    overlay.classList.remove('active');
                    if (sp.step === 'error') {{
                        statusDiv.className = 'sync-status sync-error';
                        statusDiv.textContent = '❌ ' + (sp.message || 'Ошибка');
                    }} else if (sp.synced > 0) {{
                        statusDiv.className = 'sync-status sync-ok';
                        statusDiv.textContent = '✅ Синхронизировано метрик: ' + sp.synced;
                        window.location.href = '/';
                    }} else {{
                        statusDiv.className = 'sync-status sync-ok';
                        statusDiv.textContent = '✅ ' + (sp.message || 'Новых данных нет');
                        setTimeout(() => {{ statusDiv.textContent = ''; }}, 5000);
                    }}
                }}
            }}
        }} catch (e) {{
            overlay.classList.remove('active');
            statusDiv.className = 'sync-status sync-error';
            statusDiv.textContent = '❌ ' + e.message;
        }} finally {{
            btn.disabled = false;
            btn.textContent = '❤️ Health Sync';
        }}
    }}

    document.getElementById('healthSyncBtn').addEventListener('click', syncHealth);
    </script>

    {nav_html}
    <table>
            <thead>
                <tr><th>Дата</th><th>Длительность</th><th>Дист., км</th><th>Пульс, уд/мин</th><th>Тип</th><th>Каденс</th><th>Набор</th><th>Энергозатраты, ккал</th></tr>
            </thead>
        <tbody>
            {rows}
        </tbody>
    </table>
</body>
</html>
'''

SESSION_HTML = '''
<!DOCTYPE html>
<html lang='ru'>
<head>
    <meta charset='UTF-8'>
    <title>Тренировка — AI Running Coach</title>
    <script src='https://cdn.jsdelivr.net/npm/chart.js@4'></script>
    <style>
        body {{ font-family: sans-serif; max-width: 98%; margin: 20px 30px; line-height: 1.6; }}
        .card {{ border: 1px solid #ccc; padding: 20px; border-radius: 10px; background: #f9f9f9; margin-bottom: 20px; }}
        .info {{ display: grid; grid-template-columns: 1fr 1fr 1fr 1fr 1fr 1fr 1fr; gap: 10px; margin: 15px 0; }}
        .info-item {{ background: white; padding: 8px; border-radius: 6px; text-align: center; display: flex; flex-direction: column; align-items: center; gap: 1px; }}
        .info-item b {{ font-size: 20px; color: #4CAF50; font-weight: bold; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
        th, td {{ padding: 8px; text-align: center; border-bottom: 1px solid #ddd; }}
        th {{ background: #4CAF50; color: white; }}
        .zone-z1 {{ background: #e8f5e9; }}
        .zone-z2 {{ background: #c8e6c9; }}
        .zone-z3 {{ background: #fff3e0; }}
        .zone-z4 {{ background: #ffccbc; }}
        .zone-z5 {{ background: #ffcdd2; }}
        .btn {{ display: inline-block; padding: 8px 20px; background: #4CAF50; color: white; text-decoration: none; border-radius: 5px; }}
        .btn:hover {{ background: #45a049; }}
        .btn-danger {{ background: #e53935; }}
        .btn-danger:hover {{ background: #c62828; }}
        .info-label {{ font-size: 13px; font-weight: bold; color: #444; }}
        .info-unit {{ font-size: 12px; font-weight: bold; color: #666; }}
    </style>
</head>
<body>
    <div style="text-align:right;margin-bottom:10px;">{user_header}</div>
    <h2>🏃 {type_ru} {suspect_badge}</h2>
    <p style='color:#666;'>{date}</p>
    {suspect_detail}
    <p style='color:#666;font-size:14px;margin:0 0 10px 0'>{background_info}</p>

    {recovery_html}

    <div class='card'>
        <div class='info'>
            <div class='info-item'><span class='info-label'>Дистанция</span><b>{dist}</b><span class='info-unit'>км</span></div>
            <div class='info-item'><span class='info-label'>Общее время</span><b>{dur}</b><span class='info-unit'></span></div>
            <div class='info-item'><span class='info-label'>Пульс</span><b>{hr}</b><span class='info-unit'>уд/мин</span></div>
            <div class='info-item'><span class='info-label'>Каденс</span><b>{cadence}</b><span class='info-unit'></span></div>
            <div class='info-item'><span class='info-label'>Подъем</span><b>{elev_gain}</b><span class='info-unit'>м</span></div>
            <div class='info-item'><span class='info-label'>Спуск</span><b>{elev_loss}</b><span class='info-unit'>м</span></div>
            <div class='info-item'><span class='info-label'>Калории</span><b>{cal}</b><span class='info-unit'>ккал</span></div>
        </div>

        <h3>Пульс и темп</h3>
        <canvas id='hrPaceChart' height='100'></canvas>
        <script>
        const raw = {chart_json};
        if (raw.length > 0) {{
            const step = Math.max(1, Math.floor(raw.length / 200));
            const data = raw.filter((_, i) => i % step === 0);
            if (data[data.length-1] !== raw[raw.length-1]) data.push(raw[raw.length-1]);
            new Chart(document.getElementById('hrPaceChart'), {{
                type: 'line',
                data: {{
                    datasets: [{{
                        label: 'Пульс (уд/мин)',
                        data: data.map(d => ({{x: d.dist_km, y: d.hr}})),
                        borderColor: '#e53935',
                        backgroundColor: 'transparent',
                        yAxisID: 'y',
                        cubicInterpolationMode: 'monotone',
                        tension: 0.4,
                        pointRadius: 0,
                    }}, {{
                        label: 'Темп (мин/км)',
                        data: data.map(d => ({{x: d.dist_km, y: d.pace}})),
                        borderColor: '#1e88e5',
                        backgroundColor: 'transparent',
                        yAxisID: 'y1',
                        cubicInterpolationMode: 'monotone',
                        tension: 0.4,
                        pointRadius: 0,
                    }}]
                }},
                options: {{
                    responsive: true,
                    interaction: {{ mode: 'index', intersect: false }},
                    scales: {{
                        x: {{ type: 'linear', title: {{ display: true, text: 'Дистанция, км' }}, ticks: {{ stepSize: 0.25, autoSkip: false }} }},
                        y: {{ title: {{ display: true, text: 'Пульс, уд/мин' }}, position: 'left' }},
                        y1: {{ title: {{ display: true, text: 'Темп, мин/км' }}, position: 'right', reverse: true }},
                    }}
                }}
            }});
        }}
        </script>

        <h3>Детали по отрезкам</h3>
        <table>
            <thead>
                <tr><th>#</th><th>Зона</th><th>Длительность</th><th>Дист., км</th><th>Пульс, уд/мин</th><th>Каденс</th><th>Темп</th><th>↑ м</th><th>↓ м</th></tr>
            </thead>
            <tbody>
                {segments_rows}
            </tbody>
        </table>
    </div>

    <div style='margin-top: 20px; display: flex; gap: 10px;'>
        <a href='/' class='btn'>&larr; Назад к списку</a>
        <form action='/session/{session_id}/delete' method='post' style='display:inline' onsubmit='return confirm("Удалить тренировку?")'>
            <button type='submit' class='btn btn-danger'>Удалить</button>
        </form>
    </div>
</body>
</html>
'''

SETTINGS_PAGE = '''
<!DOCTYPE html>
<html lang='ru'>
<head>
    <meta charset='UTF-8'>
    <title>Настройки — AI Running Coach</title>
    <style>
        body {{ font-family: sans-serif; max-width: 500px; margin: 50px auto; line-height: 1.6; padding: 0 20px; }}
        .card {{ border: 1px solid #ccc; padding: 20px; border-radius: 10px; background: #f9f9f9; }}
        label {{ display: block; margin: 15px 0 5px; }}
        input[type=number] {{ width: 120px; padding: 8px; font-size: 16px; }}
        .btn {{ display: inline-block; padding: 8px 20px; background: #4CAF50; color: white; text-decoration: none; border-radius: 5px; font-size: 16px; border: none; cursor: pointer; }}
        .btn:hover {{ background: #45a049; }}
    </style>
</head>
<body>
    <div style="text-align:right;margin-bottom:10px;">{user_header}</div>
    <h2>⚙️ Настройки</h2>
    <div class='card'>
        <form action='/settings' method='post'>
            <label><b>Максимальный пульс (ЧССмакс):</b></label>
            <input type='number' name='max_hr' value='{max_hr}' min='100' max='250'>
            <label><b>Вес (кг):</b></label>
            <input type='number' name='weight' value='{weight}' min='30' max='250' step='0.1'>
            <hr>
            <h4>Детекция ошибочных тренировок (Bogus session detection)</h4>
            <label><b>Мин. темп (мин/км):</b> темп быстрее этого считается ошибкой</label>
            <input type='number' name='max_credible_pace' value='{max_credible_pace}' min='2.0' max='6.0' step='0.1'>
            <label><b>Макс. GPS-скачок (м):</b> прыжок координат больше этого — ошибка</label>
            <input type='number' name='max_gps_jump_m' value='{max_gps_jump_m}' min='10' max='500' step='10'>
            <label><b>Мин. пульс для быстрого темпа:</b> если пульс ниже, а темп быстрее — ошибка</label>
            <input type='number' name='min_hr_for_fast_pace' value='{min_hr_for_fast_pace}' min='90' max='180'>
            <hr>
            <h4>Синхронизация Coros (Coros sync)</h4>
            <label><b>Email Coros Training Hub:</b></label>
            <input type='email' name='coros_email' value='{coros_email}' style='width:250px;padding:6px;font-size:14px'>
            <label><b>Пароль Coros:</b></label>
            <input type='password' name='coros_password' placeholder='{coros_password}' style='width:250px;padding:6px;font-size:14px'>
            <div style='font-size:12px;color:#888;margin-top:4px'>Пароль хранится в зашифрованном виде (Fernet). Оставьте пустым, чтобы не менять.</div>
            <br><br>
            <button type='submit' class='btn'>Сохранить</button>
            <a href='/' class='btn' style='background:#888;'>&larr; Назад</a>
        </form>
        <h4>Зоны пульса (при ЧССмакс = {max_hr})</h4>
        <table>
            <tr><th>Зона</th><th>% от ЧССмакс</th><th>Пульс</th></tr>
            <tr><td>Z1</td><td>50-60%</td><td>{z1}</td></tr>
            <tr><td>Z2</td><td>60-70%</td><td>{z2}</td></tr>
            <tr><td>Z3</td><td>70-80%</td><td>{z3}</td></tr>
            <tr><td>Z4</td><td>80-90%</td><td>{z4}</td></tr>
            <tr><td>Z5</td><td>90-100%</td><td>{z5}</td></tr>
        </table>
    </div>
</body>
</html>
'''


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

    # Запуск Telegram-бота (Start Telegram bot)
    _start_telegram_bot()


# Главная страница: список тренировок и статистика (Main page: session list and stats)
@app.get('/', response_class=HTMLResponse)
async def index(year: Optional[int] = None, month: Optional[int] = None, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    user_name = current_user.name or current_user.telegram_username or "Бегун"
    return render_page(db, user_id=current_user.id, user_name=user_name, year=year, month=month)


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
async def session_detail(session_id: int, db: Session = Depends(get_db),
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
            _, hrv_label = _hrv_status(rm.avg_sleep_hrv, rm.sleep_hrv_baseline, rm.sleep_hrv_sd,
                json.loads(rm.sleep_hrv_interval_list) if rm.sleep_hrv_interval_list else None)
            rhr_str = f"{rm.rhr}" if rm.rhr is not None else "—"
            tired_str = _tired_label(rm.tired_rate) or "—"
            perf_str = _readiness_label(rm.performance, rm.recovery_pct, rm.training_load_ratio) or "—"
            load_str = _load_label(rm.training_load) or "—"
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
    return SESSION_HTML.format(
        user_header=user_header,
        session_id=s.id,
        suspect_badge=suspect_badge,
        suspect_detail=suspect_detail,
        type_ru=TRAINING_TYPES_RU.get(s.training_type, s.training_type),
        date=s.begin_ts.strftime("%d.%m.%Y %H:%M") if s.begin_ts else "",
        dist=f"{s.total_distance_km:.2f}",
        dur=fmt_duration(s.duration_minutes),
        hr=s.avg_heart_rate,
        cadence=cadence_display,
        cal=cal,
        background_info=background_info,
        elev_gain=eg_total,
        elev_loss=el_total,
        segments_rows=seg_rows,
        chart_json=chart_json,
        recovery_html=recovery_html,
    )


# Страница настроек (Settings page)
@app.get('/settings', response_class=HTMLResponse)
async def settings_page(current_user: User = Depends(get_current_user)):
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
    return SETTINGS_PAGE.format(
        user_header=user_header,
        max_hr=m, weight=settings.weight, z1=z1, z2=z2, z3=z3, z4=z4, z5=z5,
        max_credible_pace=settings.max_credible_pace,
        max_gps_jump_m=settings.max_gps_jump_m,
        min_hr_for_fast_pace=settings.min_hr_for_fast_pace,
        coros_email=settings.coros_email or '',
        coros_password=pw_placeholder,
    )


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


# === Фоновая автоматическая синхронизация Coros (Auto background sync) ===

# Статус автосинхронизации (Auto-sync status tracking)
_auto_sync_status = {
    'health': {'last_run': None, 'status': 'idle', 'message': '', 'next_run': None},
    'activity': {'last_run': None, 'status': 'idle', 'message': '', 'next_run': None},
}
_AUTO_SYNC_STATUS_LOCK = threading.Lock()

# Интервалы синхронизации из переменных окружения (с квотер-джиттером)
_HEALTH_SYNC_INTERVAL = int(os.getenv("COROS_HEALTH_SYNC_INTERVAL", "21600"))  # 6 часов
_ACTIVITY_SYNC_INTERVAL = int(os.getenv("COROS_ACTIVITY_SYNC_INTERVAL", "3600"))  # 1 час
_AUTO_SYNC_LOCK = threading.Lock()

# Сохраняет время последней синхронизации здоровья в БД (Save last health sync attempt time to DB)
def _update_last_health_sync(user_id: int):
    from src.models import User
    from datetime import datetime
    try:
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                user.last_health_sync_at = datetime.now()
                db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.warning("Не удалось обновить last_health_sync_at: %s", e)

# Сохраняет dashboard данные Coros в today's запись DailyMetrics (Save Coros dashboard data to today's DailyMetrics)
def _save_dashboard_data(client, db, user_id: int):
    from src.models import DailyMetrics
    from datetime import date
    try:
        dashboard = client.get_dashboard()
        if not dashboard:
            logger.warning("Dashboard: пустой ответ (endpoint вернул пустые данные)")
            return
        logger.info("Dashboard данные: %s", dashboard)
        info = dashboard.get('summaryInfo')
        if not info:
            logger.debug("Dashboard: нет summaryInfo")
            return
        today = date.today()
        dm = db.query(DailyMetrics).filter(
            DailyMetrics.user_id == user_id,
            DailyMetrics.date == today
        ).first()
        if not dm:
            dm = DailyMetrics(user_id=user_id, date=today)
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
        db.commit()
    except Exception as e:
        logger.warning("Ошибка сохранения dashboard: %s", e)

# Синхронизация метрик здоровья (авто, без прогресса) (Auto health metrics sync)
def _auto_sync_health():
    from datetime import timedelta, datetime
    from src.models import User
    with _AUTO_SYNC_STATUS_LOCK:
        _auto_sync_status['health']['status'] = 'syncing'
        _auto_sync_status['health']['message'] = 'Синхронизация...'
    try:
        db = SessionLocal()
        try:
            users = db.query(User).filter(
                User.coros_email.isnot(None),
                User.coros_password.isnot(None),
                (User.is_active == True) | (User.is_active.is_(None)),
            ).all()
        finally:
            db.close()

        total_synced = 0
        total_empty = 0
        for user in users:
            result = _auto_sync_health_inner(user.id)
            _update_last_health_sync(user.id)
            if result > 0:
                total_synced += result
            elif result == 0:
                total_empty += 1

        with _AUTO_SYNC_STATUS_LOCK:
            s = _auto_sync_status['health']
            s['status'] = 'ok'
            s['last_run'] = datetime.now()
            if total_synced > 0:
                s['message'] = f'✓ Синхронизировано: {total_synced}'
            elif total_empty > 0:
                s['message'] = '🟡 Синхронизация прошла, но данных о сне нет — возможно часы не синхронизированы с приложением'
            else:
                s['message'] = 'Нет учётных данных Coros'
            s['next_run'] = s['last_run'] + timedelta(seconds=_HEALTH_SYNC_INTERVAL)
    except Exception as e:
        with _AUTO_SYNC_STATUS_LOCK:
            s = _auto_sync_status['health']
            s['status'] = 'error'
            s['last_run'] = datetime.now()
            s['message'] = str(e)[:80]
            s['next_run'] = s['last_run'] + timedelta(seconds=_HEALTH_SYNC_INTERVAL)

def _auto_sync_health_inner(user_id: int) -> int:
    """Возвращает количество новых синхронизированных записей (Return count of new synced records)"""
    from src.coros_client import CorosClient, CorosAuthError, CorosAPIError
    from src.models import User
    from datetime import timedelta, date, datetime

    db = SessionLocal()
    try:
        us = db.query(User).filter(User.id == user_id).first()
        if not us or not us.coros_email or not us.coros_password:
            logger.debug("Автосинхронизация здоровья: нет учётных данных Coros")
            return -1
        try:
            plain_password = decrypt(us.coros_password)
        except Exception:
            plain_password = us.coros_password
        client = CorosClient(us.coros_email, plain_password, timeout=15)
        client.authenticate()

        existing_dates = {r[0] for r in db.query(DailyMetrics.date).filter(DailyMetrics.user_id == user_id).all()}
        today = date.today()
        start_day = (today - timedelta(days=120)).strftime("%Y%m%d")
        end_day = today.strftime("%Y%m%d")

        metrics_list = client.get_daily_metrics(start_day, end_day)
        logger.info("Автосинхронизация здоровья: получено %d записей из Coros", len(metrics_list))
        if not metrics_list:
            # Всё равно сохраняем dashboard данные (Still save dashboard data even if metrics empty)
            _save_dashboard_data(client, db, user_id)
            return 0

        analytics_by_date = {}
        try:
            analytics_list = client.get_analytics()
            for a in analytics_list:
                ad = a.get('happenDay')
                if ad:
                    try:
                        d = datetime.strptime(str(ad), "%Y%m%d").date()
                        analytics_by_date[d] = a
                    except (ValueError, TypeError):
                        pass
        except Exception as e:
            logger.warning("Автосинхронизация: не удалось получить аналитику Coros: %s", e)

        synced = 0
        for entry in metrics_list:
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
                user_id=user_id,
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

        if synced:
            db.commit()
            logger.info("Автосинхронизация здоровья: synced=%d", synced)
        else:
            logger.info("Автосинхронизация здоровья: новых записей нет")

        if analytics_by_date:
            updated = 0
            for entry_date, ana in analytics_by_date.items():
                existing = db.query(DailyMetrics).filter(DailyMetrics.user_id == user_id, DailyMetrics.date == entry_date).first()
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
                logger.info("Автосинхронизация: обновлено аналитикой %d записей", updated)
        # Сохраняем dashboard данные после обработки метрик (Save dashboard data after metrics processing)
        _save_dashboard_data(client, db, user_id)
        return synced
    except CorosAuthError as e:
        logger.warning("Автосинхронизация здоровья: ошибка аутентификации: %s", e)
        return 0
    except CorosAPIError as e:
        logger.warning("Автосинхронизация здоровья: ошибка Coros API: %s", e)
        return 0
    except Exception:
        logger.exception("Автосинхронизация здоровья: неожиданная ошибка")
        return 0
    finally:
        db.close()

# Синхронизация активностей (авто, без прогресса) (Auto activity sync)
def _auto_sync_activities():
    from datetime import timedelta, datetime
    from src.models import User
    with _AUTO_SYNC_STATUS_LOCK:
        _auto_sync_status['activity']['status'] = 'syncing'
        _auto_sync_status['activity']['message'] = 'Синхронизация...'
    try:
        db = SessionLocal()
        try:
            users = db.query(User).filter(
                User.coros_email.isnot(None),
                User.coros_password.isnot(None),
                (User.is_active == True) | (User.is_active.is_(None)),
            ).all()
        finally:
            db.close()

        total_synced = 0
        for user in users:
            result = _auto_sync_activities_inner(user.id)
            if result > 0:
                total_synced += result

        with _AUTO_SYNC_STATUS_LOCK:
            s = _auto_sync_status['activity']
            s['status'] = 'ok'
            s['last_run'] = datetime.now()
            if total_synced == 0:
                s['message'] = '✓ Новых тренировок нет'
            else:
                s['message'] = f'✓ Синхронизировано: {total_synced}'
            s['next_run'] = s['last_run'] + timedelta(seconds=_ACTIVITY_SYNC_INTERVAL)
    except Exception as e:
        with _AUTO_SYNC_STATUS_LOCK:
            s = _auto_sync_status['activity']
            s['status'] = 'error'
            s['last_run'] = datetime.now()
            s['message'] = str(e)[:80]
            s['next_run'] = s['last_run'] + timedelta(seconds=_ACTIVITY_SYNC_INTERVAL)

def _auto_sync_activities_inner(user_id: int) -> int:
    from src.coros_client import CorosClient, CorosAuthError, CorosAPIError
    from src.models import DeletedTraining
    from src.parsers.fit_parser import parse_fit
    import tempfile

    db = SessionLocal()
    try:
        us = db.query(User).filter(User.id == user_id).first()
        if not us or not us.coros_email or not us.coros_password:
            logger.debug("Автосинхронизация активностей: нет учётных данных Coros")
            return -1
        try:
            plain_password = decrypt(us.coros_password)
        except Exception:
            plain_password = us.coros_password
        client = CorosClient(us.coros_email, plain_password, timeout=15)
        client.authenticate()

        activities = client.list_activities(limit=50, since=us.last_coros_sync)
        logger.info("Автосинхронизация активностей: получено %d активностей", len(activities))
        if not activities:
            return 0

        existing_times = {r[0] for r in db.query(TrainingSession.begin_ts).filter(TrainingSession.user_id == user_id).all()}
        deleted_times = set()
        all_deleted = db.query(DeletedTraining).filter(DeletedTraining.user_id == user_id).all()
        for d in all_deleted:
            if d.begin_ts:
                deleted_times.add(d.begin_ts)

        def already_imported(ts):
            for et in existing_times:
                if et is not None and abs((et - ts).total_seconds()) < 120:
                    return True
            return False

        def was_deleted(ts):
            for dt in deleted_times:
                if abs((dt - ts).total_seconds()) < 120:
                    return True
            return False

        new_acts = [a for a in activities if not already_imported(a['start_time'])]
        if not new_acts:
            logger.info("Автосинхронизация активностей: все активности уже в БД")
            return 0

        synced = 0
        errors = []
        max_act_ts = us.last_coros_sync
        for act in new_acts:
            if was_deleted(act['start_time']):
                logger.info("Автосинхронизация: пропуск ранее удалённой %s (%s)", act['name'], act['start_time'])
                continue
            logger.info("Автосинхронизация: загрузка %s (%s)", act['name'], act['start_time'])
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.fit')
            tmp.close()
            try:
                ok = client.download_fit(act['id'], act['sport_type'], tmp.name)
                if not ok:
                    logger.warning("Автосинхронизация: не удалось скачать %s", act['name'])
                    errors.append(f"{act['name']}: download failed")
                    continue

                data = parse_fit(tmp.name, max_hr=us.max_hr,
                                 max_credible_pace=us.max_credible_pace,
                                 max_gps_jump_m=us.max_gps_jump_m,
                                 min_hr_for_fast_pace=us.min_hr_for_fast_pace)
                if not data:
                    logger.warning("Автосинхронизация: не удалось распарсить %s", act['name'])
                    errors.append(f"{act['name']}: parse failed")
                    continue

                cleaning_log = data.pop('cleaning_log', None)
                flags_val = data.pop('suspect_flags', None)
                if data.get('training_type') in ('invalid', None):
                    logger.warning("Автосинхронизация: некорректные данные %s", act['name'])
                    errors.append(f"{act['name']}: invalid data")
                    continue

                session = TrainingSession(**data)
                if cleaning_log:
                    session.cleaning_log = cleaning_log
                if flags_val:
                    session.suspect_flags = flags_val
                session.user_id = user_id
                db.add(session)
                db.flush()
                session_id = session.id
                db.commit()
                synced += 1
                logger.info("Автосинхронизация: сохранена %s (%s)", act['name'], act['start_time'])
                # Уведомление + запрос оценки в Telegram (Notification + rating request)
                row1 = [{"text": str(i), "callback_data": f"feedback:{session_id}:{i}"} for i in range(0, 6)]
                row2 = [{"text": str(i), "callback_data": f"feedback:{session_id}:{i}"} for i in range(6, 11)]
                try:
                    _telegram_notify(
                        user_id,
                        f"🏃 *Новая тренировка!*\n"
                        f"▫️ {act['name']}\n"
                        f"▫️ {data.get('total_distance_km', 0):.1f} км\n\n"
                        f"Насколько тяжёлой была тренировка?\n"
                        f"`0` — вообще легко\n"
                        f"`10` — почти умер",
                        reply_markup={"inline_keyboard": [row1, row2]},
                    )
                except Exception as notify_err:
                    logger.warning("Не удалось отправить Telegram-уведомление о новой тренировке: %s", notify_err)
                if max_act_ts is None or act['start_time'] > max_act_ts:
                    max_act_ts = act['start_time']
            except Exception as e:
                logger.exception("Ошибка при обработке %s", act['name'])
                errors.append(f"{act['name']}: {str(e)}")
            finally:
                if os.path.exists(tmp.name):
                    os.unlink(tmp.name)

        if max_act_ts is not None and (us.last_coros_sync is None or max_act_ts > us.last_coros_sync):
            us.last_coros_sync = max_act_ts
            db.commit()
            logger.info("Автосинхронизация: last_coros_sync обновлён: %s", max_act_ts)

        logger.info("Автосинхронизация активностей: synced=%d, errors=%d", synced, len(errors))
        return synced
    except CorosAuthError as e:
        logger.warning("Автосинхронизация активностей: ошибка аутентификации: %s", e)
        return 0
    except CorosAPIError as e:
        logger.warning("Автосинхронизация активностей: ошибка Coros API: %s", e)
        return 0
    except Exception:
        logger.exception("Автосинхронизация активностей: неожиданная ошибка")
        return 0
    finally:
        db.close()

# Фоновый планировщик автосинхронизации (Background auto-sync scheduler)
def _start_auto_sync():
    import random

    with _AUTO_SYNC_LOCK:
        if hasattr(_start_auto_sync, '_started') and _start_auto_sync._started:
            return
        _start_auto_sync._started = True

    def _loop():
        logger.info("Автосинхронизация: запуск планировщика (health=%dс, activities=%dс)",
                     _HEALTH_SYNC_INTERVAL, _ACTIVITY_SYNC_INTERVAL)
        time.sleep(30)

        last_health = 0.0
        last_activity = 0.0

        while True:
            now = time.time()
            try:
                if now - last_health >= _HEALTH_SYNC_INTERVAL * random.uniform(0.8, 1.2):
                    logger.info("Автосинхронизация: health sync")
                    _auto_sync_health()
                    last_health = time.time()
            except Exception:
                logger.exception("Автосинхронизация: ошибка health sync")

            try:
                if now - last_activity >= _ACTIVITY_SYNC_INTERVAL * random.uniform(0.8, 1.2):
                    logger.info("Автосинхронизация: activity sync")
                    _auto_sync_activities()
                    last_activity = time.time()
            except Exception:
                logger.exception("Автосинхронизация: ошибка activity sync")

            time.sleep(300)

    thread = threading.Thread(target=_loop, daemon=True, name="coros-auto-sync")
    thread.start()
    logger.info("Автосинхронизация Coros: фоновый поток запущен")


# Запуск Telegram-бота (Start Telegram bot)
def _start_telegram_bot():
    try:
        import subprocess
        import sys
        bot_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_telegram_bot.py")
        proc = subprocess.Popen(
            [sys.executable, bot_script],
        )
        logger.info("Telegram-бот: процесс запущен (pid=%s)", proc.pid)
    except Exception as e:
        logger.error("Telegram-бот: ошибка запуска: %s", e)


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
