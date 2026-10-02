from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram.ext import ContextTypes

from src.models import SessionLocal
from src.models import User, WeightMeasurement
from src.telegram.state import _awaiting_weight, _awaiting_weight_lock
from src.services.audit import AuditService
from src.utils.logger import get_logger
from src.config import settings
from src.config.constants import WEIGHT_PROMPT_WEEKDAY

logger = get_logger("telegram.jobs.weight")

# Телеграм-бот (PTB) нумерует дни недели с воскресенья: 0 = вс, 1 = пн … Python — с понедельника.
# (PTB weekday numbering starts at Sunday = 0; convert from Python's Monday = 0.)
WEIGHT_PROMPT_PTB_DAYS: tuple[int, ...] = ((WEIGHT_PROMPT_WEEKDAY + 1) % 7,)


def is_weigh_in_day(now: datetime) -> bool:
    """День взвешивания по локальной дате (Is `now` the weekly weigh-in day)."""
    return now.weekday() == WEIGHT_PROMPT_WEEKDAY


def week_start(now: datetime) -> datetime:
    """Понедельник 00:00 локальной недели, в которую попадает `now` (local Monday 00:00)."""
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return today_start - timedelta(days=now.weekday())


def users_to_prompt(db, now: datetime) -> list[User]:
    """Активные пользователи с Telegram, не вводившие вес на этой неделе.
    Вне дня взвешивания — пусто (догон при старте бота безопасен).
    (Active Telegram users without a weigh-in this week; empty outside the weigh-in day.)"""
    if not is_weigh_in_day(now):
        return []
    since = week_start(now)
    users = db.query(User).filter(
        User.telegram_chat_id.isnot(None),
        User.is_active == True,
    ).all()
    result = []
    for user in users:
        existing = db.query(WeightMeasurement).filter(
            WeightMeasurement.user_id == user.id,
            WeightMeasurement.measured_at >= since,
        ).first()
        if existing is None:
            result.append(user)
    return result


def prompt_text(now: datetime) -> str:
    """Текст запроса: утром — приглашение, позже — напоминание (morning invite vs. reminder)."""
    if now.hour < 10:
        return ("⚖️ *Доброе утро!* Сегодня день контрольного взвешивания — "
                "введи свой вес (в кг):\nнапример: 75.5")
    return ("🔔 *Напоминание:* вес за эту неделю ещё не введён.\n"
            "Введи свой вес (в кг):\nнапример: 75.5")


async def weekly_weight_job(context: ContextTypes.DEFAULT_TYPE):
    """Раз в неделю запросить вес у тех, кто не ввёл его на этой неделе
    (Weekly prompt for users who haven't logged weight this week)."""
    db = SessionLocal()
    audit = AuditService(db)
    try:
        now = datetime.now(ZoneInfo(settings.timezone))
        text = prompt_text(now)
        for user in users_to_prompt(db, now):
            try:
                await context.bot.send_message(
                    chat_id=user.telegram_chat_id,
                    text=text,
                    parse_mode="Markdown",
                )
                with _awaiting_weight_lock:
                    _awaiting_weight[user.telegram_chat_id] = True
                audit.log_telegram_sent(
                    user_id=user.id,
                    chat_id=user.telegram_chat_id,
                    message_preview="Weekly weight prompt",
                    source="weekly_weight_job",
                )
            except Exception as e:
                logger.warning("Failed to send weight prompt to %s: %s", user.telegram_chat_id, e)
                audit.log_telegram_failed(
                    user_id=user.id,
                    chat_id=user.telegram_chat_id,
                    error=str(e),
                    message_preview="Weekly weight prompt",
                    source="weekly_weight_job",
                )
    finally:
        db.close()
