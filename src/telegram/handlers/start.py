import secrets

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from src.models import SessionLocal
from src.models import User
from src.services.auth import hash_password
from src.services.audit import AuditService
from src.config import settings
from src.telegram.config import EMAIL, PASSWORD
from src.telegram.utils import get_user, _get_web_app_url
from src.utils.logger import get_logger

logger = get_logger("telegram.handlers.start")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    if user:
        await update.message.reply_text(
            f"👋 С возвращением! Твой email: {user.email}\n"
            f"Используй /sync для синхронизации или /trainings для просмотра тренировок."
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "🏃 *Добро пожаловать в Running Coach!*\n\n"
        "Я помогу тебе анализировать тренировки с Coros.\n\n"
        "Для начала введи свой *email* для входа в веб-интерфейс:",
        parse_mode="Markdown",
    )
    return EMAIL


async def get_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    chat_id = update.effective_chat.id

    if "@" not in email or "." not in email:
        await update.message.reply_text("❌ Непохоже на email. Попробуй ещё раз:")
        return EMAIL

    db = SessionLocal()
    try:
        existing = db.query(User).filter(
            User.email == email,
            User.telegram_chat_id.isnot(None),
            User.telegram_chat_id != str(chat_id),
        ).first()
        if existing:
            await update.message.reply_text(
                "❌ Этот email уже используется другим пользователем Telegram.\n"
                "Попробуй другой email или обратись в поддержку."
            )
            return ConversationHandler.END

        user = db.query(User).filter(User.email == email).first()
        if user:
            if user.password_hash:
                user.telegram_chat_id = str(chat_id)
                db.commit()
                audit = AuditService(db)
                audit.log_settings_changed(
                    user_id=user.id,
                    changes={"telegram_chat_id": {"action": "linked"}},
                    source="telegram_start_existing",
                )
                await update.message.reply_text(
                    "✅ Email найден! Введи пароль для входа:"
                )
                return PASSWORD
            else:
                user.telegram_chat_id = str(chat_id)
                user.password_hash = hash_password(secrets.token_urlsafe(16))
                db.commit()
                audit = AuditService(db)
                audit.log_user_registered(user_id=user.id, source="telegram_start")
                await update.message.reply_text(
                    "✅ Регистрация завершена!\n"
                    "Пароль сгенерирован автоматически.\n"
                    "Используй /sync для синхронизации или /login_info чтобы увидеть данные для входа."
                )
                return ConversationHandler.END

        new_user = User(
            email=email,
            telegram_chat_id=str(chat_id),
            is_active=True,
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        audit = AuditService(db)
        audit.log_user_registered(user_id=new_user.id, source="telegram_start")
        await update.message.reply_text(
            f"✅ Регистрация начата!\n"
            f"Email: {email}\n\n"
            f"Теперь введи пароль (минимум {settings.password_min_length} символов):"
        )
        return PASSWORD
    except Exception as e:
        db.rollback()
        logger.error("Email save error: %s", e)
        await update.message.reply_text("😔 Ошибка при сохранении email.")
        return ConversationHandler.END
    finally:
        db.close()


async def get_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    password = update.message.text.strip()
    if len(password) < settings.password_min_length:
        await update.message.reply_text(
            f"Слишком короткий пароль (минимум {settings.password_min_length} символов). Попробуй ещё раз:"
        )
        return PASSWORD

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_chat_id == str(chat_id)).first()
        if not user:
            await update.message.reply_text("❌ Ошибка: пользователь не найден.")
            return ConversationHandler.END

        user.password_hash = hash_password(password)
        db.commit()
        audit = AuditService(db)
        audit.log_user_registered(user_id=user.id, source="telegram_password_set")

        web_app_url = _get_web_app_url()
        keyboard = [[
            InlineKeyboardButton("🌐 Открыть веб-панель", url=f"{web_app_url}/login"),
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"✅ Регистрация завершена!\n\n"
            f"Email: {user.email}\n"
            f"Теперь ты можешь:\n"
            f"  • Использовать /sync для синхронизации\n"
            f"  • Использовать /trainings для просмотра тренировок\n"
            f"  • Открыть веб-панель через кнопку ниже\n\n"
            f"🔑 Войди в веб-интерфейс, чтобы настроить интеграцию с Coros.",
            reply_markup=reply_markup,
        )
        return ConversationHandler.END
    except Exception as e:
        db.rollback()
        logger.error("Password save error: %s", e)
        await update.message.reply_text("😔 Ошибка при сохранении пароля.")
        return ConversationHandler.END
    finally:
        db.close()


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Регистрация отменена. Если захочешь продолжить — используй /start."
    )
    return ConversationHandler.END
