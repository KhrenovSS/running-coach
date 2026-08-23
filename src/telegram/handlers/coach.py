# Коуч в Telegram: /verdict + роутер свободного текста (Coach handlers) — DEV_PLAN §7
#
# Роутер чинит известный дефект: catch-all висел на handle_weight_message,
# который молча return'ил — новый текстовый хендлер никогда бы не сработал.
# (The router fixes the silent catch-all: weight flow keeps priority, then coach.)

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from src.config import settings
from src.exceptions import CoachError
from src.models import SessionLocal
from src.coach import orchestrator
from src.telegram.handlers.weight import handle_weight_message
from src.telegram.state import _awaiting_weight, _awaiting_weight_lock
from src.telegram.utils import get_user
from src.utils.logger import get_logger

logger = get_logger("telegram.handlers.coach")


def _is_awaiting_weight(chat_id: int) -> bool:
    with _awaiting_weight_lock:
        return _awaiting_weight.get(chat_id, False)


async def cmd_verdict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /verdict — вердикт по запросу (on-demand verdict)."""
    user = get_user(update.effective_chat.id)
    if not user:
        await update.message.reply_text(
            "❌ Сначала используй /start чтобы зарегистрироваться.")
        return
    db = SessionLocal()
    try:
        text = orchestrator.morning_verdict(user.id, db=db)
        await update.message.reply_text(text, parse_mode="Markdown")
    except CoachError as e:
        logger.error("Verdict error for user=%s: %s", user.id, e)
        await update.message.reply_text("😔 Не удалось собрать вердикт.")
    finally:
        db.close()


_INITIATIVE_LABELS = (("off", "🔕 выкл"), ("low", "🔈 минимум"),
                      ("normal", "🔔 обычная"), ("high", "📣 максимум"))


async def cmd_coach_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /coach_settings — уровень инициативы бота (initiative setting)."""
    user = get_user(update.effective_chat.id)
    if not user:
        await update.message.reply_text(
            "❌ Сначала используй /start чтобы зарегистрироваться.")
        return
    db = SessionLocal()
    try:
        current = orchestrator.get_initiative(user.id, db=db)
    finally:
        db.close()
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(("✅ " if lvl == current else "") + label,
                             callback_data=f"initiative:{lvl}")
        for lvl, label in _INITIATIVE_LABELS
    ]])
    await update.message.reply_text(
        "Насколько активно тренер пишет сам?\n"
        "📣 максимум — утро, разбор, вечерний вопрос, недельный итог\n"
        "🔔 обычная — утро и разбор\n"
        "🔈 минимум — только разбор тренировок\n"
        "🔕 выкл — только по твоему запросу",
        reply_markup=keyboard)


async def initiative_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тап уровня инициативы: initiative:{level} (initiative tap)."""
    query = update.callback_query
    await query.answer()
    parts = (query.data or "").split(":")
    if len(parts) != 2:
        return
    user = get_user(update.effective_chat.id)
    if not user:
        return
    db = SessionLocal()
    try:
        level = orchestrator.set_initiative(user.id, parts[1], db=db)
    finally:
        db.close()
    label = dict(_INITIATIVE_LABELS).get(level, level)
    await query.edit_message_text(f"✅ Инициатива тренера: {label}")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Роутер свободного текста: вес (приоритет старого флоу) → коуч (text router)."""
    chat_id = update.effective_chat.id
    if _is_awaiting_weight(chat_id):
        return await handle_weight_message(update, context)
    if not settings.coach_enabled:
        return
    user = get_user(chat_id)
    if not user:
        return
    db = SessionLocal()
    try:
        reply = orchestrator.handle_chat(user.id, update.message.text or "", db=db)
        markup = None
        if reply.log_suggestion is not None:
            # Запись боли — только по явному тапу пользователя (log via explicit tap)
            v = reply.log_suggestion.value
            markup = InlineKeyboardMarkup([[InlineKeyboardButton(
                f"📝 записать дискомфорт {v}/10", callback_data=f"pain:today:{v}")]])
        await update.message.reply_text(reply.text, parse_mode="Markdown",
                                        reply_markup=markup)
    except CoachError as e:
        logger.error("Coach chat error for user=%s: %s", user.id, e)
        await update.message.reply_text("😔 Тренер сейчас недоступен.")
    finally:
        db.close()
