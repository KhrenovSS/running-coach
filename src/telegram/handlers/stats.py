from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from src.models import SessionLocal
from src.models import User, TrainingSession, DailyMetrics, WeightMeasurement
from src.telegram.utils import get_user
from src.services.audit import AuditService
from src.utils.logger import get_logger
from src.config import settings

logger = get_logger("telegram.handlers.stats")


class StatsPages:
    """Управление страницами статистики: общая, неделя, месяц, год"""

    def __init__(self, user: User):
        self.user = user

    def get_page(self, period: str) -> str:
        db = SessionLocal()
        try:
            now = datetime.now(ZoneInfo(settings.timezone))
            if period == "all":
                return self._overview(db, now)
            elif period == "week":
                return self._period_stats(db, now, days=7)
            elif period == "month":
                return self._period_stats(db, now, days=30)
            elif period == "year":
                return self._period_stats(db, now, days=365)
            return self._overview(db, now)
        finally:
            db.close()

    def _overview(self, db, now: datetime) -> str:
        user_id = self.user.id
        total_sessions = db.query(TrainingSession).filter(TrainingSession.user_id == user_id).count()
        total_distance = db.query(db.func.sum(TrainingSession.distance_km)).filter(
            TrainingSession.user_id == user_id,
        ).scalar() or Decimal("0")
        total_duration = db.query(db.func.sum(TrainingSession.duration_seconds)).filter(
            TrainingSession.user_id == user_id,
        ).scalar() or 0

        last_session = db.query(TrainingSession).filter(
            TrainingSession.user_id == user_id,
        ).order_by(TrainingSession.begin_ts.desc()).first()

        text = (
            f"📊 *Общая статистика для {self.user.email}*\n\n"
            f"🏃 Всего тренировок: {total_sessions}\n"
            f"📏 Общая дистанция: {float(total_distance):.1f} км\n"
            f"⏱ Общее время: {self._format_duration(total_duration)}\n"
        )
        if last_session:
            text += (
                f"\n*Последняя тренировка:*\n"
                f"  {last_session.sport or 'N/A'}: {float(last_session.distance_km or 0):.1f} км, "
                f"{self._format_duration(last_session.duration_seconds or 0)}\n"
                f"  📅 {last_session.begin_ts.strftime('%d.%m.%Y %H:%M') if last_session.begin_ts else 'N/A'}"
            )
        return text

    def _period_stats(self, db, now: datetime, days: int) -> str:
        user_id = self.user.id
        since = now - timedelta(days=days)
        label = {7: "неделю", 30: "месяц", 365: "год"}.get(days, f"{days} дней")

        sessions = db.query(TrainingSession).filter(
            TrainingSession.user_id == user_id,
            TrainingSession.begin_ts >= since,
        ).order_by(TrainingSession.begin_ts.desc()).all()

        if not sessions:
            return f"📊 Нет тренировок за последний(юю) {label}."

        total_distance = sum(float(s.distance_km or 0) for s in sessions)
        total_duration = sum(s.duration_seconds or 0 for s in sessions)
        total_count = len(sessions)

        text = (
            f"📊 *Статистика за {label}*\n\n"
            f"🏃 Тренировок: {total_count}\n"
            f"📏 Дистанция: {total_distance:.1f} км\n"
            f"⏱ Время: {self._format_duration(total_duration)}\n"
            f"📐 Средняя дистанция: {total_distance / total_count:.1f} км\n\n"
        )

        for s in sessions[:5]:
            d = s.begin_ts
            date_str = d.strftime("%d.%m") if d else "N/A"
            text += f"• {date_str} {s.sport or 'N/A'}: {float(s.distance_km or 0):.1f} км, {self._format_duration(s.duration_seconds or 0)}\n"

        return text

    @staticmethod
    def _format_duration(seconds: int) -> str:
        h, remainder = divmod(seconds, 3600)
        m, s = divmod(remainder, 60)
        if h > 0:
            return f"{h}ч {m}м"
        return f"{m}м {s}с"


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    if not user:
        await update.message.reply_text("❌ Сначала используй /start чтобы зарегистрироваться.")
        return

    stats = StatsPages(user)
    text = stats.get_page("all")

    keyboard = [
        [
            InlineKeyboardButton("📅 Неделя", callback_data="stats:week"),
            InlineKeyboardButton("📅 Месяц", callback_data="stats:month"),
        ],
        [
            InlineKeyboardButton("📅 Год", callback_data="stats:year"),
            InlineKeyboardButton("📊 Общая", callback_data="stats:all"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)


async def stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if not data or not data.startswith("stats:"):
        return
    period = data.split(":", 1)[1]

    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    if not user:
        await query.edit_message_text("❌ Пользователь не найден.")
        return

    stats = StatsPages(user)
    text = stats.get_page(period)

    keyboard = [
        [
            InlineKeyboardButton("📅 Неделя", callback_data="stats:week"),
            InlineKeyboardButton("📅 Месяц", callback_data="stats:month"),
        ],
        [
            InlineKeyboardButton("📅 Год", callback_data="stats:year"),
            InlineKeyboardButton("📊 Общая", callback_data="stats:all"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=reply_markup)
