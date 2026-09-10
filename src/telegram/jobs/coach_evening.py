# Вечерний вопрос о самочувствии (Evening wellness question) — DEV_PLAN §7
# 21:00; гейт по initiative (high); только при активной проблеме (coach/concerns.py,
# решение владельца 10.09.2026); пропуск, если боль сегодня уже записана.

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from src.coach import concerns, orchestrator
from src.config import settings
from src.models import SessionLocal, User
from src.utils.timeutils import user_now
from src.utils.logger import get_logger

logger = get_logger("telegram.jobs.coach_evening")

WELLNESS_BUTTONS = ((0, "🟢 всё ок"), (2, "🟡 ныло"), (5, "🔴 болело"))


async def evening_wellness_job(context: ContextTypes.DEFAULT_TYPE):
    """Вечером спросить про активную проблему (evening question about the active concern)."""
    if not settings.coach_enabled:
        return
    db = SessionLocal()
    try:
        users = db.query(User).filter(
            User.telegram_chat_id.isnot(None),
            User.is_active.is_(True),
        ).all()
        for user in users:
            if orchestrator.get_initiative(user.id, db=db) != "high":
                continue  # вечерний вопрос — только на максимальной инициативе
            if not concerns.evening_check_needed(user.id, db=db):
                continue
            active = concerns.active_concerns(user.id, db=db, today=user_now(user).date())
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton(label, callback_data=f"wellness:{level}")
                for level, label in WELLNESS_BUTTONS
            ]])
            try:
                await context.bot.send_message(
                    chat_id=user.telegram_chat_id,
                    text=concerns.evening_question(active),
                    reply_markup=keyboard,
                )
            except Exception as e:
                logger.warning("Evening wellness send failed for %s: %s",
                               user.telegram_chat_id, e)
    finally:
        db.close()
