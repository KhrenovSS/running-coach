from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import ContextTypes

from src.database import SessionLocal
from src.models import User, WeightMeasurement
from src.telegram.utils import get_user
from src.telegram.state import _awaiting_weight
from src.services.audit import AuditService
from src.utils.logger import get_logger

logger = get_logger("telegram.handlers.weight")


def _get_weight_stats_text(user_id: int) -> str:
    db = SessionLocal()
    try:
        now = datetime.now(ZoneInfo("Europe/Moscow"))
        month_ago = now - timedelta(days=30)
        measurements = db.query(WeightMeasurement).filter(
            WeightMeasurement.user_id == user_id,
            WeightMeasurement.measured_at >= month_ago,
        ).order_by(WeightMeasurement.measured_at.desc()).all()

        if not measurements:
            return "Нет данных о весе за последние 30 дней."

        recent = measurements[0]
        text = f"📊 *Вес за 30 дней:* {len(measurements)} записей\n\n"

        if len(measurements) >= 2:
            first = measurements[-1]
            diff = float(recent.weight_kg) - float(first.weight_kg)
            arrow = "📈" if diff > 0 else "📉" if diff < 0 else "➡️"
            text += f"{arrow} Изменение за месяц: {diff:+.1f} кг\n"
            avg = sum(float(m.weight_kg) for m in measurements) / len(measurements)
            text += f"📊 Средний: {avg:.1f} кг\n"

        text += f"\n*Последние записи:*\n"
        for m in measurements[:7]:
            date_str = m.measured_at.strftime("%d.%m") if m.measured_at else "N/A"
            text += f"• {date_str}: {float(m.weight_kg):.1f} кг\n"

        return text
    finally:
        db.close()


async def cmd_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    if not user:
        await update.message.reply_text("❌ Сначала используй /start чтобы зарегистрироваться.")
        return

    text = _get_weight_stats_text(user.id)
    await update.message.reply_text(text, parse_mode="Markdown")


async def handle_weight_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in _awaiting_weight or not _awaiting_weight[chat_id]:
        return

    user = get_user(chat_id)
    if not user:
        return

    text = update.message.text.strip().replace(",", ".")
    try:
        weight = float(text)
        if weight < 20 or weight > 300:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "❌ Пожалуйста, введи корректный вес (например: 75.5):"
        )
        return

    db = SessionLocal()
    audit = AuditService(db)
    try:
        measurement = WeightMeasurement(
            user_id=user.id,
            weight_kg=Decimal(str(weight)),
            measured_at=datetime.now(ZoneInfo("Europe/Moscow")),
        )
        db.add(measurement)
        db.commit()
        _awaiting_weight[chat_id] = False
        audit.log_telegram_received(
            user_id=user.id,
            message_preview=f"Weight logged: {weight} kg",
            source="telegram_weight",
        )
        await update.message.reply_text(f"✅ Вес {weight:.1f} кг сохранён! Спасибо! 🙌")
    except Exception as e:
        db.rollback()
        logger.error("Weight save error: %s", e)
        await update.message.reply_text("😔 Ошибка при сохранении веса.")
    finally:
        db.close()
