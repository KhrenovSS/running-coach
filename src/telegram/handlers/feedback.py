from telegram import Update
from telegram.ext import ContextTypes

from src.database import SessionLocal
from src.models import TrainingFeedback
from src.telegram.utils import get_user
from src.utils.logger import get_logger

logger = get_logger("telegram.handlers.feedback")


async def feedback_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает нажатие кнопки оценки тренировки (Handle training rating button press)"""
    query = update.callback_query
    await query.answer()
    data = query.data
    if not data or not data.startswith("feedback:"):
        return
    parts = data.split(":")
    if len(parts) != 3:
        return
    _, session_id_str, rating_str = parts
    try:
        session_id = int(session_id_str)
        rating = int(rating_str)
    except ValueError:
        return
    if rating < 0 or rating > 10:
        return

    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    if not user:
        await query.edit_message_text(
            "❌ Пользователь не найден. Используй /start чтобы зарегистрироваться."
        )
        return

    db = SessionLocal()
    try:
        fb = db.query(TrainingFeedback).filter(
            TrainingFeedback.session_id == session_id,
            TrainingFeedback.user_id == user.id,
        ).first()
        if fb:
            await query.edit_message_text(
                f"✅ Оценка уже была сохранена ранее: {fb.rating}/10"
            )
            return

        fb = TrainingFeedback(
            session_id=session_id,
            user_id=user.id,
            rating=rating,
        )
        db.add(fb)
        db.commit()
        labels = {0: "😴", 1: "😌", 2: "🙂", 3: "😐", 4: "😅", 5: "💪",
                  6: "😤", 7: "🥵", 8: "😵", 9: "💀", 10: "⚰️"}
        await query.edit_message_text(
            f"✅ Спасибо! Оценка {rating}/10 {labels.get(rating, '')} сохранена."
        )
    except Exception as e:
        db.rollback()
        logger.error("Feedback save error: %s", e)
        await query.edit_message_text("😔 Ошибка при сохранении оценки.")
    finally:
        db.close()
