# Роуты настроек: GET/POST /settings (Settings page routes)

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from src.models import get_db, User, WeightMeasurement, WatchCredential, get_settings
from src.deps import templates
from src.api.deps import get_current_user
from src.services.audit import AuditService
from src.services.watch_credentials import upsert_watch_credential
from src.utils.logger import get_logger

logger = get_logger("app")
router = APIRouter()


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
    # Читаем ВСЕ активные WatchCredential (Read ALL active WatchCredential — brand-agnostic)
    creds = db.query(WatchCredential).filter(
        WatchCredential.user_id == current_user.id,
        WatchCredential.is_active == True,
    ).all()
    # Формируем список credentials для шаблона (Build credentials list for template)
    watch_creds = []
    for cred in creds:
        watch_creds.append({
            'brand': cred.brand,
            'brand_display': cred.brand.capitalize(),
            'email': cred.encrypted_user or '',
            'has_password': bool(cred.encrypted_password),
            'pw_placeholder': '********' if cred.encrypted_password else '',
            'activity_sync_interval': cred.activity_sync_interval if cred.activity_sync_interval else '',
            'health_sync_interval': cred.health_sync_interval if cred.health_sync_interval else '',
        })
    user_name = current_user.name or current_user.telegram_username or "Бегун"
    user_header = f"👤 {user_name} | <a href='/auth/logout'>Выйти</a>"
    return templates.TemplateResponse(request, "settings.html", {
        "user_header": user_header,
        "max_hr": m, "weight": settings.weight, "z1": z1, "z2": z2, "z3": z3, "z4": z4, "z5": z5,
        "max_credible_pace": settings.max_credible_pace,
        "max_gps_jump_m": settings.max_gps_jump_m,
        "min_hr_for_fast_pace": settings.min_hr_for_fast_pace,
        "watch_creds": watch_creds,
    })


@router.post('/settings')
async def settings_save(max_hr: int = Form(...), weight: float = Form(...),
                        max_credible_pace: float = Form(3.0),
                        max_gps_jump_m: float = Form(100.0),
                        min_hr_for_fast_pace: int = Form(130),
                        watch_brand: str = Form(''),
                        watch_email: str = Form(''),
                        watch_password: str = Form(''),
                        activity_sync_interval: int = Form(None),
                        health_sync_interval: int = Form(None),
                        db: Session = Depends(get_db),
                        current_user: User = Depends(get_current_user)):
    user = db.query(User).filter(User.id == current_user.id).first()
    audit = AuditService(db)
    if not user:
        user = User(id=current_user.id)
        db.add(user)
    old_weight = user.weight_kg
    old_max_hr = user.max_hr

    # Читаем старый email для audit-diff (Read old email for audit diff — brand-agnostic)
    old_watch_email = ''
    if watch_brand:
        old_cred = db.query(WatchCredential).filter(
            WatchCredential.user_id == current_user.id,
            WatchCredential.brand == watch_brand,
        ).first()
        old_watch_email = old_cred.encrypted_user if old_cred else ''

    user.max_hr = max_hr
    user.weight_kg = weight
    user.max_credible_pace = max_credible_pace
    user.max_gps_jump_m = max_gps_jump_m
    user.min_hr_for_fast_pace = min_hr_for_fast_pace

    # Сохраняем credentials через сервис (Save credentials via service — brand-agnostic)
    if watch_brand:
        upsert_watch_credential(
            db, current_user.id, watch_brand,
            email=watch_email, password=watch_password,
            activity_sync_interval=activity_sync_interval,
            health_sync_interval=health_sync_interval,
        )
    if old_weight != weight:
        wm = WeightMeasurement(weight_kg=weight, measured_at=datetime.now(timezone.utc), user_id=current_user.id)
        db.add(wm)
    db.commit()

    changes = {}
    if old_max_hr != max_hr:
        changes['max_hr'] = {'old': old_max_hr, 'new': max_hr}
    if old_weight != weight:
        changes['weight_kg'] = {'old': old_weight, 'new': weight}
    if old_watch_email != (watch_email or None):
        changes['watch_email'] = {'old': old_watch_email, 'new': watch_email or None}
    if changes:
        audit.log_settings_changed(
            user_id=current_user.id,
            changes=changes,
        )
    return RedirectResponse(url='/', status_code=303)