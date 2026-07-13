from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from src.models import SessionLocal
from src.models import User, TrainingSession
from src.telegram.utils import get_user
from src.utils.logger import get_logger

logger = get_logger("telegram.handlers.trainings")


def trainings_keyboard(user_id: int) -> InlineKeyboardMarkup:
    db = SessionLocal()
    try:
        now = datetime.now(ZoneInfo("Europe/Moscow"))
        days_options = [7, 14, 30]
        keyboard = []
        for days in days_options:
            since = now - timedelta(days=days)
            count = db.query(TrainingSession).filter(
                TrainingSession.user_id == user_id,
                TrainingSession.begin_ts >= since,
            ).count()
            label = {7: "неделя", 14: "2 недели", 30: "месяц"}[days]
            keyboard.append([
                InlineKeyboardButton(f"📅 {label} ({count})", callback_data=f"trainings:{days}")
            ])
        keyboard.append([
            InlineKeyboardButton("📊 Статистика", callback_data="stats:all")
        ])
        return InlineKeyboardMarkup(keyboard)
    finally:
        db.close()


async def cmd_trainings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    if not user:
        await update.message.reply_text("❌ Сначала используй /start чтобы зарегистрироваться.")
        return

    text = "📋 *Твои тренировки*\nВыбери период:"
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=trainings_keyboard(user.id))


async def trainings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if not data or not data.startswith("trainings:"):
        return

    days = int(data.split(":", 1)[1])
    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    if not user:
        await query.edit_message_text("❌ Пользователь не найден.")
        return

    db = SessionLocal()
    try:
        since = datetime.now(ZoneInfo("Europe/Moscow")) - timedelta(days=days)
        sessions = db.query(TrainingSession).filter(
            TrainingSession.user_id == user.id,
            TrainingSession.begin_ts >= since,
        ).order_by(TrainingSession.begin_ts.desc()).all()

        if not sessions:
            await query.edit_message_text(
                f"Нет тренировок за последние {days} дней.",
                reply_markup=trainings_keyboard(user.id),
            )
            return

        label = {7: "7 дней", 14: "14 дней", 30: "30 дней"}[days]
        text = f"📋 *Тренировки за {label}*\n\n"
        for s in sessions:
            d = s.begin_ts
            date_str = d.strftime("%d.%m %H:%M") if d else "N/A"
            dur_str = f"{s.duration_seconds // 60} мин" if s.duration_seconds else "N/A"
            dist_str = f"{float(s.distance_km or 0):.1f} км"
            text += f"• {date_str} {s.sport or 'N/A'}: {dist_str}, {dur_str}\n"

        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=trainings_keyboard(user.id))
    except Exception as e:
        logger.error("Trainings callback error: %s", e)
        await query.edit_message_text("😔 Ошибка загрузки тренировок.")
    finally:
        db.close()
