# Напоминание прислать скриншот сна (Sleep-screenshot reminder) — #257
# 09:00 по локальному поясу (19.09.2026: было 10:00 — то есть ПОСЛЕ утреннего вердикта;
# теперь за 30 мин до резервной отправки в 09:30, чтобы сон успел в вердикт дня):
# если скриншот сна за сегодня не прислан — мягкий запрос.
# Условие узкое (именно скриншот, sleep_source='coros_screenshot'), в отличие от
# daily_recovery_check_job (та про отсутствие HRV-синка). Гейт инициативы — как у
# morning/weekly. (Ask for a sleep screenshot at 09:00 if none came today.)

from __future__ import annotations

from telegram.ext import ContextTypes

from src.coach import orchestrator
from src.config import settings
from src.models import SessionLocal, User
from src.services.sleep_ingest import has_sleep_for_date
from src.utils.logger import get_logger
from src.utils.timeutils import user_now

logger = get_logger("telegram.jobs.sleep_reminder")

REMINDER_TEXT = ("🌙 Не вижу скриншот сна за сегодня. Пришли скрин экрана сна "
                 "из приложения Coros — учту длительность, фазы и стресс сна "
                 "в тренировках (или команда /sleep).")


def _needs_reminder(user: User, *, db) -> bool:
    """Нужно ли напоминание: инициатива ≥ normal и нет скрина сна за сегодня."""
    if orchestrator.get_initiative(user.id, db=db) not in ("normal", "high"):
        return False
    return not has_sleep_for_date(user.id, user_now(user).date(), db=db)


async def sleep_screenshot_reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Разослать напоминание тем, кто не прислал скриншот сна (send reminders)."""
    if not settings.coach_enabled:
        return
    db = SessionLocal()
    try:
        # (chat_id, need) — скаляры, дальше сессия не нужна (scalars only)
        targets = [(u.telegram_chat_id, _needs_reminder(u, db=db))
                   for u in db.query(User).filter(
                       User.telegram_chat_id.isnot(None),
                       User.is_active.is_(True),
                   ).all()]
    finally:
        db.close()

    for chat_id, need in targets:
        if not need:
            continue
        try:
            await context.bot.send_message(chat_id=chat_id, text=REMINDER_TEXT)
        except Exception as e:  # джоба не должна умирать на одном пользователе
            logger.warning("Sleep reminder failed for chat=%s: %s", chat_id, e)
