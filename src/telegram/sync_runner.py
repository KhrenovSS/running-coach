import asyncio
import threading
import time

from src.database import SessionLocal
from src.models import User, SyncLog
from src.services.sync_service import SyncService
from src.services.audit import AuditService
from src.utils.logger import get_logger

logger = get_logger("telegram.sync_runner")


def run_sync_in_thread(chat_id: int) -> tuple[bool, str]:
    """Запускает синхронизацию в отдельном треде и возвращает результат"""
    db = SessionLocal()
    audit = AuditService(db)
    try:
        user = db.query(User).filter(User.telegram_chat_id == str(chat_id)).first()
        if not user:
            return False, "❌ Пользователь не найден."

        sync_log = SyncLog(user_id=user.id, status="in_progress")
        db.add(sync_log)
        db.commit()
        log_id = sync_log.id

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            service = SyncService(db)
            result = loop.run_until_complete(service.full_sync(user.id))
        finally:
            loop.close()

        sync_log = db.query(SyncLog).filter(SyncLog.id == log_id).first()
        if sync_log:
            sync_log.status = "completed" if result["success"] else "failed"
            sync_log.completed_at = db.func.now()
            db.commit()

        if result["success"]:
            audit.log_sync_completed(user_id=user.id, source="telegram_runner")
            msg = f"✅ Синхронизация завершена!\n"
            new_activities = result.get("new_activities", 0)
            new_health_days = result.get("new_health_days", 0)
            if new_activities:
                msg += f"  🏃 Тренировок: {new_activities}\n"
            if new_health_days:
                msg += f"  📊 Дней здоровья: {new_health_days}"
            return True, msg.strip()
        else:
            audit.log_sync_failed(user_id=user.id, error=result.get("error", "Unknown"), source="telegram_runner")
            return False, f"❌ Ошибка синхронизации: {result.get('error', 'Неизвестная ошибка')}"
    except Exception as e:
        logger.error("Sync error for %s: %s", chat_id, e)
        db.rollback()
        return False, f"❌ Ошибка: {e}"
    finally:
        db.close()
