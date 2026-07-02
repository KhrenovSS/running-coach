"""
Health check endpoint

Проверка здоровья приложения для мониторинга и самодиагностики.
Application health check for monitoring and self-diagnostics.
"""

import os
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from src.api.deps import get_db
from src.utils.logger import get_logger

router = APIRouter(prefix="/health", tags=["health"])
logger = get_logger("app")

# Время старта процесса (Process start time)
_process_start_time = time.time()


def _format_uptime(seconds: float) -> str:
    """Форматировать uptime в человекочитаемый вид (Format uptime)"""
    return str(timedelta(seconds=int(seconds)))


@router.get("/")
async def health_check(db: Session = Depends(get_db)):
    """
    Проверить состояние приложения
    Check application health
    """
    checks = {}
    overall_status = "healthy"
    
    # Проверка БД (Database check)
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = {"status": "ok", "message": "Database connection successful"}
    except Exception as e:
        checks["database"] = {"status": "error", "message": f"Database error: {str(e)}"}
        overall_status = "unhealthy"
        logger.error("Health check: database error", extra={"context": "Health", "error": str(e)})
    
    # Проверка миграций (Migrations check)
    try:
        from alembic.migration import MigrationContext
        from sqlalchemy import create_engine
        
        context = MigrationContext.configure(db.connection())
        current_rev = context.get_current_revision()
        checks["migrations"] = {
            "status": "ok",
            "message": "Migrations applied",
            "current_revision": current_rev,
        }
    except Exception as e:
        checks["migrations"] = {"status": "error", "message": f"Migration check failed: {str(e)}"}
        overall_status = "degraded"
    
    # Системные метрики (System metrics)
    uptime_seconds = time.time() - _process_start_time
    memory_info = {}
    try:
        import psutil
        process = psutil.Process(os.getpid())
        memory_mb = process.memory_info().rss / (1024 * 1024)
        memory_info = {
            "used_mb": round(memory_mb, 2),
            "percent": round(process.memory_percent(), 2),
        }
    except ImportError:
        memory_info = {"used_mb": None, "percent": None, "note": "psutil not installed"}
    
    response = {
        "status": overall_status,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "application": {
            "name": "AI Running Coach",
            "uptime_seconds": int(uptime_seconds),
            "uptime_formatted": _format_uptime(uptime_seconds),
            "memory": memory_info,
        },
        "checks": checks,
    }
    
    from fastapi.responses import JSONResponse
    status_code = 200 if overall_status in ("healthy", "degraded") else 503
    return JSONResponse(content=response, status_code=status_code)
