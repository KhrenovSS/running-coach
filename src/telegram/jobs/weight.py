from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram.ext import ContextTypes

from src.models import SessionLocal
from src.models import User, WeightMeasurement
from src.telegram.state import _awaiting_weight, _awaiting_weight_lock
from src.services.audit import AuditService
from src.utils.logger import get_logger
from src.config import settings

logger = get_logger("telegram.jobs.weight")


async def daily_weight_job(context: ContextTypes.DEFAULT_TYPE):
    """Запросить вес у пользователей, которые не ввели его сегодня (Prompt users who haven't logged weight today)"""
    db = SessionLocal()
    audit = AuditService(db)
    try:
        now = datetime.now(ZoneInfo(settings.timezone))
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        hour = now.hour

        users = db.query(User).filter(
            User.telegram_chat_id.isnot(None),
            User.is_active == True,
        ).all()
        for user in users:
            existing = db.query(WeightMeasurement).filter(
                WeightMeasurement.user_id == user.id,
                WeightMeasurement.measured_at >= today_start,
            ).first()
            if existing:
                continue

            if hour < 10:
                text = "⏰ *Доброе утро!* Введи свой сегодняшний вес (в кг):\nнапример: 75.5"
            else:
                text = "🔔 *Напоминание:* вес за сегодня ещё не введён.\nВведи свой вес (в кг):\nнапример: 75.5"

            try:
                await context.bot.send_message(
                    chat_id=user.telegram_chat_id,
                    text=text,
                    parse_mode="Markdown",
                )
                with _awaiting_weight_lock:
                    _awaiting_weight[user.telegram_chat_id] = True
                audit.log_telegram_sent(
                    user_id=user.id,
                    chat_id=user.telegram_chat_id,
                    message_preview="Daily weight prompt",
                    source="daily_weight_job",
                )
            except Exception as e:
                logger.warning("Failed to send weight prompt to %s: %s", user.telegram_chat_id, e)
                audit.log_telegram_failed(
                    user_id=user.id,
                    chat_id=user.telegram_chat_id,
                    error=str(e),
                    message_preview="Daily weight prompt",
                    source="daily_weight_job",
                )
    finally:
        db.close()
