import asyncio

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from src.models import SessionLocal
from src.models import User, TrainingSession, DailyMetrics, WeightMeasurement, DeletedTraining, WatchCredential
from src.services.auth import hash_password
from src.services.audit import AuditService
from src.config import settings
from src.telegram.config import NEW_PASSWORD
from src.telegram.utils import get_user, _get_web_app_url
from src.utils.logger import get_logger

logger = get_logger("telegram.handlers.account")


async def cmd_delete_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    if not user:
        await update.message.reply_text("❌ Нет данных для удаления.")
        return

    db = SessionLocal()
    audit = AuditService(db)
    try:
        db.query(TrainingSession).filter(TrainingSession.user_id == user.id).delete()
        db.query(DailyMetrics).filter(DailyMetrics.user_id == user.id).delete()
        db.query(WeightMeasurement).filter(WeightMeasurement.user_id == user.id).delete()
        db.query(DeletedTraining).filter(DeletedTraining.user_id == user.id).delete()
        db.query(WatchCredential).filter(WatchCredential.user_id == user.id).delete()
        user.telegram_chat_id = None
        db.commit()
        audit.log_settings_changed(
            user_id=user.id,
            changes={"account": {"action": "delete_all_data"}},
            source="telegram_delete_me",
        )
        await update.message.reply_text(
            "🗑 Все твои данные удалены.\n"
            "Если захочешь начать заново — используй /start."
        )
    except Exception as e:
        db.rollback()
        logger.error("Delete error: %s", e)
        await update.message.reply_text("😔 Ошибка при удалении данных.")
    finally:
        db.close()


async def cmd_login_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать email для входа в веб (Show login email)"""
    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    if not user:
        await update.message.reply_text("❌ Сначала используй /start чтобы зарегистрироваться.")
        return
    if not user.email:
        await update.message.reply_text(
            "У вас ещё не установлен email для входа.\n"
            "Используйте /start чтобы получить ссылку на регистрацию."
        )
        return
    await update.message.reply_text(
        f"📧 Ваш email для входа: {user.email}\n\n"
        f"Форма входа: {_get_web_app_url()}/login\n"
        f"Сменить пароль: /reset_password"
    )


async def cmd_reset_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сброс пароля — запросить новый пароль (Reset password — prompt for new password)"""
    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    if not user:
        await update.message.reply_text("❌ Сначала используй /start чтобы зарегистрироваться.")
        return
    if not user.email:
        await update.message.reply_text(
            "❌ У вас ещё не установлен email. Сначала зарегистрируйтесь через /start."
        )
        return ConversationHandler.END
    from src.config import settings
    await update.message.reply_text(
        f"🔑 Введите новый пароль (минимум {settings.password_min_length} символов).\n"
        f"🔒 Пароль будет показан 2 секунды, затем сообщение удалится (как при вводе пароля Coros)."
    )
    return NEW_PASSWORD


async def get_new_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получить новый пароль, сохранить хеш, показать и удалить (Receive new password, save hash, show and delete)"""
    from src.config import settings
    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    if not user:
        await update.message.reply_text("❌ Пользователь не найден.")
        return ConversationHandler.END

    password = update.message.text.strip()
    if len(password) < settings.password_min_length:
        await update.message.reply_text(
            f"Слишком короткий пароль (минимум {settings.password_min_length} символов). Попробуйте ещё раз:"
        )
        return NEW_PASSWORD

    # Сохраняем хеш пароля (Save password hash)
    db = SessionLocal()
    audit = AuditService(db)
    try:
        user_db = db.query(User).filter(User.id == user.id).first()
        user_db.password_hash = hash_password(password)
        db.commit()
        # Удаляем сообщение с паролем (Delete password message)
        try:
            await update.message.delete()
        except Exception:
            pass
        # Показываем пароль 2 секунды затем удаляем (Show password for 2 sec then delete)
        confirmation = await update.message.reply_text(
            f"✅ Пароль установлен: {password}\n"
            f"🔒 Это сообщение будет удалено через 2 секунды."
        )
        await asyncio.sleep(2)
        try:
            await confirmation.delete()
        except Exception:
            pass
        audit.log_settings_changed(
            user_id=user.id,
            changes={"password": {"action": "reset"}},
            source="telegram_reset_password",
        )
        await update.message.reply_text(
            "✅ Пароль изменён. Теперь вы можете войти через /login_info или /start."
        )
    except Exception as e:
        db.rollback()
        logger.error("Password reset error: %s", e)
        await update.message.reply_text("😔 Ошибка при смене пароля.")
    finally:
        db.close()
    return ConversationHandler.END


async def cancel_reset_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена сброса пароля (Cancel password reset)"""
    await update.message.reply_text("Смена пароля отменена.")
    return ConversationHandler.END
