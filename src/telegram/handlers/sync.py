import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import ContextTypes

from src.telegram.utils import get_user
from src.telegram.sync_runner import run_sync_in_thread
from src.utils.logger import get_logger
from src.config import settings

logger = get_logger("telegram.handlers.sync")


def _get_progress_message(step: str, progress: float) -> str:
    filled = int(progress * 10)
    bar = "█" * filled + "░" * (10 - filled)
    return f"🔄 Синхронизация...\n{bar} {step}"


async def cmd_sync(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    if not user:
        await update.message.reply_text("❌ Сначала используй /start чтобы зарегистрироваться.")
        return

    await update.message.reply_text("🔄 Синхронизация запущена... Это может занять до 2 минут.")

    loop = asyncio.get_event_loop()
    success, message = await loop.run_in_executor(None, run_sync_in_thread, chat_id)

    await update.message.reply_text(message)

    if success:
        db = None
        try:
            from src.models import SessionLocal
            from src.models import User, TrainingSession
            db = SessionLocal()
            user_db = db.query(User).filter(User.telegram_chat_id == str(chat_id)).first()
            if user_db:
                today_start = datetime.now(ZoneInfo(settings.timezone)).replace(hour=0, minute=0, second=0, microsecond=0)
                today_count = db.query(TrainingSession).filter(
                    TrainingSession.user_id == user_db.id,
                    TrainingSession.begin_ts >= today_start,
                ).count()
                if today_count:
                    await update.message.reply_text(f"📊 Сегодняшних тренировок: {today_count}")
        except Exception as e:
            logger.error("Error fetching today count: %s", e)
        finally:
            if db:
                db.close()
