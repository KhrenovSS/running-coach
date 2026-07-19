# Фабрика приложения и startup-событие (App factory and startup event)
#
# !! DB SAFETY !!
# This file runs on EVERY app restart:
# - init_db() creates tables (safe, additive only)
# - Alembic upgrade head runs migrations (safe for upgrades)
# - Creates admin user if missing (safe, additive only)
# NEVER add drop_all, DELETE, or TRUNCATE here.
# User data (trainings, credentials, settings) must survive restarts.
import os
from fastapi import FastAPI
from sqlalchemy import text
from src.models import SessionLocal, User, get_settings, init_db, WeightMeasurement, utcnow
from src.utils.logger import get_logger
from src.api.middleware import register_middleware
from src.config import settings
from src.api.routes.health import router as health_router
from src.api.routes.auth import router as auth_router
from src.web.routes import web_router
from src.web.state import _pending, _pending_lock, PENDING_DIR
from src.services.audit import AuditService

logger = get_logger("app")


def on_startup():
    from datetime import datetime
    init_db()

    # DB SAFETY: warn if database has 0 users — possible volume loss
    try:
        _db_check = SessionLocal()
        _user_count = _db_check.execute(text("SELECT count(*) FROM users")).scalar()
        if _user_count == 0:
            logger.warning(
                "⚠️ Database has 0 users — possible volume loss! "
                "Check pgdata volume. Run bin/backup_db.sh before next deploy."
            )
        _db_check.close()
    except Exception:
        pass  # table may not exist yet (first boot)

    try:
        from alembic.config import Config as AlembicConfig
        from alembic import command
        alembic_cfg = AlembicConfig("alembic.ini")
        command.upgrade(alembic_cfg, "head")
    except Exception as e:
        logger.exception("Ошибка Alembic миграции —硬 остановка (hard stop)")
        raise SystemExit(1)

    for f in PENDING_DIR.glob("*.tcx"):
        f.unlink(missing_ok=True)
    with _pending_lock:
        _pending.clear()

    db = SessionLocal()
    try:
        admin_user = db.query(User).filter(User.id == 1).first()
        if not admin_user:
            admin_user = User(id=1, is_active=True, max_hr=settings.default_max_hr)
            db.add(admin_user)
            db.commit()
            db.execute(text("SELECT setval('users_id_seq', (SELECT MAX(id) FROM users))"))
            db.refresh(admin_user)

        settings = get_settings(admin_user.id)
        existing = db.query(WeightMeasurement).filter(WeightMeasurement.user_id == admin_user.id).first()
        if not existing and settings.weight:
            wm = WeightMeasurement(weight_kg=settings.weight, measured_at=utcnow(), user_id=admin_user.id)
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

    from src.scheduler import AutoSyncScheduler
    AutoSyncScheduler().start()


def create_app():
    app = FastAPI(title="AI Running Coach")
    register_middleware(app)
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(web_router)
    os.makedirs("uploads", exist_ok=True)
    app.on_event("startup")(on_startup)
    app.on_event("shutdown")(on_shutdown)
    return app


def on_shutdown():
    """Graceful shutdown: остановка планировщика (Stop scheduler gracefully)"""
    from src.scheduler import AutoSyncScheduler
    AutoSyncScheduler().stop()
