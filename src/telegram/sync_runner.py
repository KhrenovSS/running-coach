"""
Запуск синхронизации в отдельном потоке для Telegram-бота
Run sync in a dedicated thread for the Telegram bot.

Заменяющий изначальный вариант, ссылавшийся на несуществующие SyncService/SyncLog/full_sync.
Replaces the original version that referenced non-existent SyncService/SyncLog/full_sync.

TODO: AUDIT-006 — Telegram вызывает sync_activities_for_user/sync_health_for_user напрямую,
а не единый run_sync_for_user из sync_service.py. Это обоснованно: Telegram синхронизирует
все бренды пользователя за один вызов и формирует сводный отчёт. При миграции на единый entry point
потребуется run_sync_for_user_all_brands(chat_id) — отдельная задача.
TODO: AUDIT-006 — Telegram calls sync_activities_for_user/sync_health_for_user directly instead
of the unified run_sync_for_user. This is intentional: Telegram syncs all user brands in one
call and builds a summary. Migrating to the unified entry point would require
run_sync_for_user_all_brands(chat_id) — separate task.
"""

import asyncio
from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError

from src.models import SessionLocal, User, WatchCredential
from src.services.audit import AuditService
from src.services.sync_service import (
    sync_activities_for_user,
    sync_health_for_user,
)
from src.utils.logger import get_logger

logger = get_logger("telegram.sync_runner")


def _run_async(coro):
    """Запустить корутину в новом event loop (тред-безопасно) / Run a coroutine in a fresh event loop (thread-safe)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def run_sync_in_thread(chat_id: int) -> tuple[bool, str]:
    """
    Полная синхронизация (activity + health) для всех активных WatchCredential пользователя.
    Full sync (activity + health) for all active WatchCredential of a user.

    Возвращает (success, message) — успех и человеческое сообщение для Telegram.
    Returns (success, message) for display in Telegram.
    """
    db = SessionLocal()
    audit = AuditService(db)
    try:
        user = db.query(User).filter(User.telegram_chat_id == str(chat_id)).first()
        if not user:
            return False, "❌ Пользователь не найден."

        creds = (
            db.query(WatchCredential)
            .filter(
                WatchCredential.user_id == user.id,
                WatchCredential.is_active.is_(True),
            )
            .all()
        )
        if not creds:
            return False, "❌ Нет активных учётных данных часов. Добавь их через /start."

        total_new_activities = 0
        total_new_health = 0
        errors: list[str] = []

        for cred in creds:
            brand = cred.brand
            audit.log_sync_started(brand=brand, user_id=user.id, source="telegram")

            # Health sync / Синхронизация метрик здоровья
            try:
                new_health = _run_async(sync_health_for_user(cred, brand))
                if new_health >= 0:
                    total_new_health += new_health
            except Exception as e:
                logger.warning("Health sync failed (brand=%s user=%s): %s", brand, user.id, e)
                errors.append(f"{brand} health: {e}")

            # Activity sync / Синхронизация тренировок
            try:
                new_activities = _run_async(sync_activities_for_user(cred, brand))
                if new_activities >= 0:
                    total_new_activities += new_activities
            except Exception as e:
                logger.warning("Activity sync failed (brand=%s user=%s): %s", brand, user.id, e)
                errors.append(f"{brand} activity: {e}")

            audit.log_sync_completed(
                brand=brand,
                user_id=user.id,
                found=total_new_activities,
                processed=total_new_activities,
                source="telegram",
            )

        # Итоговое сообщение / Summary message
        lines = ["✅ Синхронизация завершена!"]
        if total_new_activities:
            lines.append(f"  🏃 Новых тренировок: {total_new_activities}")
        if total_new_health:
            lines.append(f"  📊 Дней здоровья: {total_new_health}")
        if errors and not (total_new_activities or total_new_health):
            return False, "❌ " + "; ".join(errors)
        if errors:
            lines.append(f"  ⚠️ Частичные ошибки: {'; '.join(errors)}")
        return True, "\n".join(lines)

    except SQLAlchemyError as e:
        logger.error("DB error during sync (chat_id=%s): %s", chat_id, e)
        db.rollback()
        return False, f"❌ Ошибка базы данных: {e}"
    except Exception as e:
        logger.error("Sync error (chat_id=%s): %s", chat_id, e)
        db.rollback()
        return False, f"❌ Ошибка: {e}"
    finally:
        db.close()