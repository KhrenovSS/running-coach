from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram.ext import ContextTypes

from src.models import SessionLocal
from src.models import User, DailyMetrics
from src.services.audit import AuditService
from src.utils.logger import get_logger

logger = get_logger("telegram.jobs.recovery")


async def daily_recovery_check_job(context: ContextTypes.DEFAULT_TYPE):
    """Проверка данных сна: старт в 10:00, повтор каждые 2 часа. Если данные есть — следующая проверка вечером (18:00). Если нет — продолжаем каждые 2 часа до 18:00"""
    db = SessionLocal()
    audit = AuditService(db)
    try:
        now = datetime.now(ZoneInfo("Europe/Moscow"))
        hour = now.hour

        if hour < 8 or hour >= 20:
            next_run = now.replace(hour=10, minute=0, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            context.job_queue.run_once(daily_recovery_check_job, int((next_run - now).total_seconds()))
            return

        cutoff = now - timedelta(hours=12)
        users = db.query(User).filter(
            User.telegram_chat_id.isnot(None),
            User.is_active == True,
        ).all()

        any_missing = False
        for user in users:
            latest_metrics = db.query(DailyMetrics).filter(
                DailyMetrics.user_id == user.id,
                DailyMetrics.date >= cutoff.date(),
            ).order_by(DailyMetrics.date.desc()).first()

            if not latest_metrics:
                any_missing = True
                sync_recently = (
                    user.last_health_sync_at is not None
                    and (now - user.last_health_sync_at).total_seconds() < 14400
                )
                if sync_recently:
                    msg = ("🌙 *Нет свежих данных о восстановлении*\n\n"
                           "Синхронизация с Coros выполнялась недавно, но данные о сне и HRV за последние 12 часов не найдены.\n"
                           "Возможно, часы не синхронизированы с приложением Coros.\n"
                           "Попробуй открыть Coros app, потянуть экран вниз для синхронизации, "
                           "затем используй /sync.")
                else:
                    msg = ("🌙 *Нет данных о восстановлении*\n\n"
                           "У тебя нет свежих данных о сне и HRV за последние 12 часов.\n"
                           "Используй /sync чтобы синхронизировать данные с Coros.")
                try:
                    await context.bot.send_message(
                        chat_id=user.telegram_chat_id,
                        text=msg,
                        parse_mode="Markdown",
                    )
                    logger.info("Sent recovery reminder to user %s (chat_id=%s)", user.id, user.telegram_chat_id)
                    audit.log_telegram_sent(
                        user_id=user.id,
                        chat_id=user.telegram_chat_id,
                        message_preview="Recovery reminder",
                        source="daily_recovery_check_job",
                    )
                except Exception as e:
                    logger.warning("Failed to send recovery reminder to %s: %s", user.telegram_chat_id, e)
                    audit.log_telegram_failed(
                        user_id=user.id,
                        chat_id=user.telegram_chat_id,
                        error=str(e),
                        message_preview="Recovery reminder",
                        source="daily_recovery_check_job",
                    )

        if any_missing:
            next_run = now + timedelta(hours=2)
        else:
            evening_run = now.replace(hour=18, minute=0, second=0, microsecond=0)
            if evening_run <= now:
                evening_run += timedelta(days=1)
            next_run = evening_run

        context.job_queue.run_once(daily_recovery_check_job, int((next_run - now).total_seconds()))
    finally:
        db.close()
