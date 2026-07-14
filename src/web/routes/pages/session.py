# Роуты тренировок: /session/{id}, /session/{id}/delete, /session/{id}/feedback (Session page routes)

import json
from datetime import timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from src.models import get_db, User, TrainingSession, DailyMetrics, TrainingFeedback
from src.deps import templates
from src.api.deps import get_current_user
from src.parsers.weather import weather_icon
from src.services.stats import fmt_duration
from src.config import settings
from src.services.recovery_view import hrv_status, tired_label, readiness_label, load_label
from src.services.training_service import delete_training, upsert_feedback
from src.services.reanalyze import reanalyze_training
from src.web.state import TRAINING_TYPES_RU
from src.utils.logger import get_logger

logger = get_logger("app")
router = APIRouter()


@router.get('/session/{session_id}', response_class=HTMLResponse)
async def session_detail(request: Request, session_id: int, db: Session = Depends(get_db),
                         current_user: User = Depends(get_current_user)):
    s = db.query(TrainingSession).filter(TrainingSession.id == session_id, TrainingSession.user_id == current_user.id).first()
    if not s:
        return HTMLResponse("<h2>Тренировка не найдена</h2><a href='/'>Назад</a>", status_code=404)

    recovery_info = None
    if s.begin_ts:
        tz_name = current_user.timezone or s.timezone or settings.timezone
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


@router.post('/session/{session_id}/delete')
async def session_delete(session_id: int, db: Session = Depends(get_db),
                         current_user: User = Depends(get_current_user)):
    delete_training(db, current_user.id, session_id)
    return RedirectResponse(url='/', status_code=303)


@router.post('/session/{session_id}/feedback')
async def session_feedback(session_id: int, rating: int = Form(...),
                           db: Session = Depends(get_db),
                           current_user: User = Depends(get_current_user)):
    fb = upsert_feedback(db, current_user.id, session_id, rating)
    if not fb:
        return HTMLResponse("<h2>Тренировка не найдена</h2><a href='/'>Назад</a>", status_code=404)
    return RedirectResponse(url=f'/session/{session_id}', status_code=303)


@router.post('/session/{session_id}/reanalyze')
async def session_reanalyze(session_id: int,
                             training_type_override: str = Form(''),
                             db: Session = Depends(get_db),
                             current_user: User = Depends(get_current_user)):
    """Пересчитать тренировку с возможностью смены типа (Reanalyze training with type override)"""
    result = reanalyze_training(db, session_id, current_user.id, training_type_override)
    if result is None:
        return HTMLResponse("<h2>Ошибка пересчёта</h2><p>Нет трекпоинтов или тренировка не найдена.</p><a href='/'>Назад</a>", status_code=400)
    return RedirectResponse(url=f'/session/{session_id}', status_code=303)