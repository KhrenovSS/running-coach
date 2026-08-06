# Обработчик кнопок адаптивного max_hr (Adaptive max HR button handler)
#
# Кнопки приходят из уведомлений сервиса src/services/hr_max.py:
#   maxhr:set:<value> — установить max_hr в профиле
#   maxhr:ignore      — оставить без изменений

from telegram import Update
from telegram.ext import ContextTypes

from src.config.constants import MAX_HR_CAP
from src.models import SessionLocal, User
from src.services.audit import AuditService
from src.utils.logger import get_logger

logger = get_logger("telegram.handlers.hr_max")

MAX_HR_MIN = 100  # нижняя граница валидации (validation floor, matches src/exceptions.py range)


async def hr_max_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает подтверждение/отказ смены max_hr (Handle max HR confirm/ignore button press)"""
    query = update.callback_query
    await query.answer()
    data = query.data
    if not data or not data.startswith("maxhr:"):
        return
    parts = data.split(":")

    if len(parts) == 2 and parts[1] == "ignore":
        await query.edit_message_text("Ок, максимальный пульс оставил без изменений.")
        return

    if len(parts) != 3 or parts[1] != "set":
        return
    try:
        value = int(parts[2])
    except ValueError:
        return
    if value < MAX_HR_MIN or value > MAX_HR_CAP:
        await query.edit_message_text(f"❌ Недопустимое значение пульса: {value}.")
        return

    chat_id = update.effective_chat.id
    # Session-bound user в сессии хендлера — не detached из get_user() (уроки #236)
    # (Session-bound user inside the handler's session — never the detached get_user() object)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_chat_id == chat_id).first()
        if not user:
            await query.edit_message_text(
                "❌ Пользователь не найден. Используй /start чтобы зарегистрироваться."
            )
            return
        old_value = user.max_hr
        user.max_hr = value
        db.commit()
        AuditService(db).log_settings_changed(
            user_id=user.id,
            changes={"max_hr": {"old": old_value, "new": value}},
            source="telegram_button",
        )
        await query.edit_message_text(f"✅ Максимальный пульс обновлён: {value}.")
        logger.info("hr_max: user=%s max_hr %s → %d по кнопке (via button)", user.id, old_value, value)
    except Exception as e:
        db.rollback()
        logger.error("hr_max button error: %s", e)
        await query.edit_message_text("😔 Ошибка при обновлении максимального пульса.")
    finally:
        db.close()
