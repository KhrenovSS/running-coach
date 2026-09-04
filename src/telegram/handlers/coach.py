# Коуч в Telegram: /verdict + роутер свободного текста (Coach handlers) — DEV_PLAN §7
#
# Роутер чинит известный дефект: catch-all висел на handle_weight_message,
# который молча return'ил — новый текстовый хендлер никогда бы не сработал.
# (The router fixes the silent catch-all: weight flow keeps priority, then coach.)

from __future__ import annotations

import asyncio
import re

import telegram.error
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from src.config import settings
from src.exceptions import CoachError
from src.models import SessionLocal
from src.coach import orchestrator
from src.telegram.handlers.weight import handle_weight_message
from src.telegram.state import _awaiting_weight, _awaiting_weight_lock
from src.telegram.utils import get_user, send_md_safe
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
    try:
        text = await asyncio.to_thread(_verdict_blocking, user.id)
        await send_md_safe(update.message.reply_text, text)
    except (CoachError, telegram.error.TelegramError) as e:
        logger.error("Verdict error for user=%s: %s", user.id, e)
        await update.message.reply_text("😔 Не удалось собрать вердикт.")


def _verdict_blocking(user_id: int) -> str:
    """Sync-обёртка вердикта: сессия живёт только внутри этого треда (thread-local session)."""
    db = SessionLocal()
    try:
        return orchestrator.morning_verdict(user_id, db=db)
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


# Триггер СОСТАВЛЕНИЯ плана (LLM-ход /plan): «перепланируй», «составь/сформируй … план»,
# «переделать/изменить/поменять/скорректировать … план» (инцидент 03.09.2026: «нужно
# переделать план на неделю» ушло чат-ходом — воскресная строка плана осталась живой),
# «новый план на неделю». Вопросы «какой план / покажи план» — показ сохранённого (чат).
# (Compose-plan trigger; "show me the plan" stays a chat turn → stored card.)
_REPLAN_RE = re.compile(
    r"переплани\w+|(?:пересобери|пересостав\w*|составь|сформируй"
    r"|передел\w*|измени(?:ть|м|те)?|поменя(?:й|ть|ем|йте)?"
    r"|скорректир(?:уй|овать|уем|уйте))\s+(?:\S+\s+){0,2}план"
    r"|нов\w+ план на неделю|план на следующую неделю",
    re.IGNORECASE)


async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /plan — составить/пересоставить план недели (weekly plan on demand)."""
    user = get_user(update.effective_chat.id)
    if not user:
        await update.message.reply_text(
            "❌ Сначала используй /start чтобы зарегистрироваться.")
        return
    await update.message.reply_text("🗓 Составляю план недели…")
    try:
        text = await asyncio.to_thread(_plan_blocking, user.id)
        if text is None:
            await update.message.reply_text(
                "😔 Не удалось составить план — попробуй позже.")
            return
        await send_md_safe(update.message.reply_text, text)
    except (CoachError, telegram.error.TelegramError) as e:
        logger.error("Plan error for user=%s: %s", user.id, e, exc_info=True)
        await update.message.reply_text("😔 Не удалось составить план.")


def _plan_blocking(user_id: int) -> str | None:
    """Sync-обёртка плана: сессия живёт только внутри этого треда."""
    from src.coach.weekly_plan import generate_weekly_plan

    db = SessionLocal()
    try:
        return generate_weekly_plan(user_id, db=db)
    finally:
        db.close()


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /report — итоги текущей недели (пн–сегодня): проза LLM + карточка чисел (C8.1)."""
    user = get_user(update.effective_chat.id)
    if not user:
        await update.message.reply_text(
            "❌ Сначала используй /start чтобы зарегистрироваться.")
        return
    await update.message.reply_text("📊 Считаю итоги недели…")
    try:
        text = await asyncio.to_thread(_report_blocking, user.id)
        await send_md_safe(update.message.reply_text, text)
    except (CoachError, telegram.error.TelegramError) as e:
        logger.error("Report error for user=%s: %s", user.id, e, exc_info=True)
        await update.message.reply_text("😔 Не удалось собрать итоги недели.")


def _report_blocking(user_id: int) -> str:
    """Sync-обёртка отчёта: сессия живёт только внутри этого треда."""
    db = SessionLocal()
    try:
        return orchestrator.weekly_report(user_id, db=db).text
    finally:
        db.close()


async def cmd_week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /week — показать СОХРАНЁННЫЙ план текущей недели (read-only, без LLM).

    (Stored weekly plan card; no LLM turn, no daily-budget spend — 02.09.2026.)
    """
    user = get_user(update.effective_chat.id)
    if not user:
        await update.message.reply_text(
            "❌ Сначала используй /start чтобы зарегистрироваться.")
        return
    try:
        text = await asyncio.to_thread(_week_blocking, user.id)
        await send_md_safe(update.message.reply_text, text)
    except (CoachError, telegram.error.TelegramError) as e:
        logger.error("Week view error for user=%s: %s", user.id, e, exc_info=True)
        await update.message.reply_text("😔 Не удалось показать план недели.")


def _week_blocking(user_id: int) -> str:
    """Sync-обёртка карточки недели: сессия живёт только внутри этого треда."""
    from src.coach.week_view import render_stored_week_plan

    db = SessionLocal()
    try:
        return render_stored_week_plan(user_id, db=db)
    finally:
        db.close()


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
    if _REPLAN_RE.search(update.message.text or ""):
        # Детерминированный триггер перепланирования — до LLM-хода (/plan-путь)
        return await cmd_plan(update, context)
    try:
        # to_thread: синхронный LLM-вызов (до ~150с) не должен морозить event loop
        # всего бота (инцидент 23.08). Сессия БД живёт внутри треда целиком.
        reply = await asyncio.to_thread(_chat_turn_blocking, user.id,
                                        update.message.text or "")
        markup = None
        if reply.log_suggestion is not None:
            # Запись боли — только по явному тапу пользователя (log via explicit tap)
            v = reply.log_suggestion.value
            markup = InlineKeyboardMarkup([[InlineKeyboardButton(
                f"📝 записать дискомфорт {v}/10", callback_data=f"pain:today:{v}")]])
        await send_md_safe(update.message.reply_text, reply.text, reply_markup=markup)
    except (CoachError, telegram.error.TelegramError) as e:
        # Последний рубеж: пользователь ВСЕГДА получает ответ (bot must never go silent)
        logger.error("Coach chat error for user=%s: %s", user.id, e, exc_info=True)
        await update.message.reply_text("😔 Тренер сейчас недоступен — попробуй ещё раз чуть позже.")


def _chat_turn_blocking(user_id: int, text: str, kind: str = "chat"):
    """Sync-обёртка хода коуча: сессия живёт только внутри этого треда."""
    db = SessionLocal()
    try:
        return orchestrator.handle_chat(user_id, text, db=db, kind=kind)
    finally:
        db.close()
