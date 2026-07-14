import os
from datetime import datetime, timedelta, time as dt_time
from zoneinfo import ZoneInfo

from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ConversationHandler, Defaults
from telegram import Update

from src.config import settings
from src.telegram.config import EMAIL, PASSWORD, NEW_PASSWORD
from src.telegram.handlers.start import start, get_email, get_password, cancel
from src.telegram.handlers.sync import cmd_sync
from src.telegram.handlers.stats import cmd_stats, stats_callback
from src.telegram.handlers.trainings import cmd_trainings, trainings_callback
from src.telegram.handlers.weight import cmd_weight, handle_weight_message
from src.telegram.handlers.account import cmd_delete_me, cmd_login_info, cmd_reset_password, get_new_password, cancel_reset_password
from src.telegram.handlers.feedback import feedback_callback
from src.telegram.jobs.weight import daily_weight_job
from src.telegram.jobs.recovery import daily_recovery_check_job
from src.utils.logger import get_logger

logger = get_logger("telegram.main")


def run_bot():
    """Запускает Telegram бота (блокирующий вызов — запускать в отдельном процессе)"""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN не задан — бот не запущен")
        return

    from telegram.ext import JobQueue
    application = (
        Application.builder()
        .token(token)
        .job_queue(JobQueue())
        .defaults(Defaults(tzinfo=ZoneInfo("Europe/Moscow")))
        .build()
    )

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_email)],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_password)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("sync", cmd_sync))
    application.add_handler(CommandHandler("stats", cmd_stats))
    application.add_handler(CommandHandler("trainings", cmd_trainings))
    application.add_handler(CommandHandler("weight", cmd_weight))
    application.add_handler(CommandHandler("delete_me", cmd_delete_me))
    application.add_handler(CommandHandler("login_info", cmd_login_info))

    reset_pw_handler = ConversationHandler(
        entry_points=[CommandHandler("reset_password", cmd_reset_password)],
        states={
            NEW_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_new_password)],
        },
        fallbacks=[CommandHandler("cancel", cancel_reset_password)],
    )
    application.add_handler(reset_pw_handler)

    application.add_handler(CallbackQueryHandler(feedback_callback, pattern="^feedback:"))
    application.add_handler(CallbackQueryHandler(stats_callback, pattern="^stats:"))
    application.add_handler(CallbackQueryHandler(trainings_callback, pattern="^trainings:"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_weight_message))

    for hour in [9, 12, 15, 18]:
        application.job_queue.run_daily(daily_weight_job, time=dt_time(hour=hour, minute=0))
    logger.info("Ежедневный опрос веса запланирован на 9:00, 12:00, 15:00, 18:00")

    now = datetime.now(ZoneInfo("Europe/Moscow"))
    if now.hour >= 9 and not (now.hour == 9 and now.minute == 0 and now.second < 5):
        logger.info("Бот запущен после 9:00 MSK — запускаем напоминание веса через 30 секунд")
        application.job_queue.run_once(daily_weight_job, when=timedelta(seconds=30))

    application.job_queue.run_daily(daily_recovery_check_job, time=dt_time(hour=10, minute=0))
    logger.info("Проверка данных сна запланирована на 10:00")

    logger.info("Telegram bot polling started")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
