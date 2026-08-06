# Еженедельная проверка снижения max_hr (Weekly max HR lowering check)
#
# Если за MAX_HR_LOWER_WINDOW_DAYS в интенсивных тренировках пульс давно не приближался
# к профильному max_hr — сервис предложит снизить (кнопка подтверждения, никогда авто).
# Кулдаун повторных предложений — внутри evaluate_max_hr_lowering (по аудит-событию).

from telegram.ext import ContextTypes

from src.models import SessionLocal, User
from src.services.hr_max import evaluate_max_hr_lowering
from src.utils.logger import get_logger

logger = get_logger("telegram.jobs.hr_max")


async def weekly_max_hr_check_job(context: ContextTypes.DEFAULT_TYPE):
    """Проверить всех активных пользователей на кандидатов к снижению max_hr
    (Check all active users for max HR lowering candidates)."""
    db = SessionLocal()
    try:
        users = db.query(User).filter(
            User.telegram_chat_id.isnot(None),
            User.is_active == True,
        ).all()
        for user in users:
            try:
                # Уведомление шлёт сам сервис через telegram_notify (service notifies itself)
                evaluate_max_hr_lowering(db, user.id)
            except Exception:
                logger.warning("weekly_max_hr_check: ошибка для user=%s (check failed)",
                               user.id, exc_info=True)
                db.rollback()
    finally:
        db.close()
