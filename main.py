# Импорт компонентов FastAPI (FastAPI component imports)
import os
import time
import threading
import random
from pathlib import Path
from fastapi import FastAPI
from src.models import SessionLocal, User, get_settings, init_db
from src.logger import get_logger
from src.api.middleware import register_middleware
from src.api.routes.health import router as health_router
from src.api.routes.auth import router as auth_router
from src.web.routes import web_router
from src.deps import templates
from src.web.state import _pending, PENDING_DIR
from src.services.coros_sync_auto import health_sync_interval, activity_sync_interval, auto_sync_health, auto_sync_activities
from src.services.audit import AuditService
from src.config import CONFIG

logger = get_logger("app")

app = FastAPI(title="AI Running Coach")
register_middleware(app)
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(web_router)

os.makedirs("uploads", exist_ok=True)


# Событие при запуске сервера: инициализация БД, миграции и автосинхронизация (Startup event: DB init, migrations, auto-sync)
@app.on_event("startup")
def startup():
    from datetime import datetime
    init_db()
    try:
        from alembic.config import Config as AlembicConfig
        from alembic import command
        alembic_cfg = AlembicConfig("alembic.ini")
        command.upgrade(alembic_cfg, "head")
    except Exception as e:
        logger.error("Ошибка Alembic миграции: %s", e)

    for f in PENDING_DIR.glob("*.tcx"):
        f.unlink(missing_ok=True)
    _pending.clear()

    db = SessionLocal()
    try:
        admin_user = db.query(User).filter(User.id == 1).first()
        if not admin_user:
            admin_user = User(id=1, is_active=True, max_hr=177)
            db.add(admin_user)
            db.commit()
            db.refresh(admin_user)

        settings = get_settings()
        from src.models import WeightMeasurement
        existing = db.query(WeightMeasurement).filter(WeightMeasurement.user_id == admin_user.id).first()
        if not existing and settings.weight:
            wm = WeightMeasurement(weight_kg=settings.weight, measured_at=datetime.utcnow(), user_id=admin_user.id)
            db.add(wm)
            db.commit()

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

    from src.utils.logger import fix_logger_after_uvicorn
    fix_logger_after_uvicorn()

    _start_auto_sync()


_AUTO_SYNC_LOCK = threading.Lock()

# Фоновый планировщик автосинхронизации (Background auto-sync scheduler)
def _start_auto_sync():
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
