# Трекинг боли в Telegram (Pain tracking handlers) — DEV_PLAN §7
#
# Callbacks: pain:{sid}:{level} (после RPE), painphase:{sid}:{phase},
# pain:today:{level} (из чата), wellness:{level} (вечерний опрос).
# Хороший день = 2 тапа, плохой = 3 — всё в одном сообщении.

from __future__ import annotations

from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from src.models import SessionLocal, TrainingFeedback, WellnessReport
from src.telegram.utils import get_user
from src.utils.logger import get_logger

logger = get_logger("telegram.handlers.pain")

PAIN_LEVELS = ((0, "🚫 не беспокоило"), (2, "🟡 немного"), (5, "🔴 мешало"))
PAIN_PHASES = (("start", "старт"), ("middle", "середина"), ("end", "конец"), ("after", "после"))
DEFAULT_LOCATION = "knee"  # контекст владельца: колено (owner context: the knee)


def pain_keyboard(session_id: int | str) -> InlineKeyboardMarkup:
    """Строка кнопок боли (pain buttons row)."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(label, callback_data=f"pain:{session_id}:{level}")
        for level, label in PAIN_LEVELS
    ]])


def _phase_keyboard(session_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(label, callback_data=f"painphase:{session_id}:{phase}")
        for phase, label in PAIN_PHASES
    ]])


def _upsert_wellness_pain(db, user_id: int, level: int) -> None:
    """Записать боль в сегодняшний wellness-отчёт (upsert today's wellness pain)."""
    today = datetime.now(timezone.utc).date()
    report = db.query(WellnessReport).filter(
        WellnessReport.user_id == user_id,
        WellnessReport.report_date == today,
    ).first()
    if report is None:
        report = WellnessReport(user_id=user_id, report_date=today)
        db.add(report)
    report.pain_level = level
    report.pain_location = DEFAULT_LOCATION if level > 0 else None
    db.commit()


async def pain_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тап уровня боли: pain:{sid|today}:{level} (pain level tap)."""
    query = update.callback_query
    await query.answer()
    parts = (query.data or "").split(":")
    if len(parts) != 3:
        return
    _, sid_str, level_str = parts
    try:
        level = int(level_str)
    except ValueError:
        return
    if not 0 <= level <= 10:
        return
    user = get_user(update.effective_chat.id)
    if not user:
        return

    db = SessionLocal()
    try:
        if sid_str == "today":  # боль вне тренировки — из чата/log_suggestion
            _upsert_wellness_pain(db, user.id, level)
            await query.edit_message_reply_markup(reply_markup=None)
            await context.bot.send_message(
                update.effective_chat.id,
                f"✅ Записал: дискомфорт {level}/10 сегодня.")
            return
        session_id = int(sid_str)
        fb = db.query(TrainingFeedback).filter(
            TrainingFeedback.session_id == session_id,
            TrainingFeedback.user_id == user.id,
        ).first()
        if fb is None:
            # Боль без RPE: кнопки идут после оценки, но страхуемся (guard anyway)
            _upsert_wellness_pain(db, user.id, level)
            await query.edit_message_reply_markup(reply_markup=None)
            return
        fb.pain_level = level
        fb.pain_location = DEFAULT_LOCATION if level > 0 else None
        fb.pain_phase = None if level > 0 else "none"
        db.commit()
        if level == 0:
            await query.edit_message_reply_markup(reply_markup=None)
            await context.bot.send_message(update.effective_chat.id,
                                           "✅ Отлично, колено не беспокоило!")
        else:
            # Уточняем фазу — прямо про «первые 400–800 м» (ask the phase)
            await query.edit_message_reply_markup(reply_markup=_phase_keyboard(session_id))
    except (ValueError, TypeError):
        return
    except Exception as e:
        db.rollback()
        logger.error("Pain save error: %s", e, exc_info=True)
    finally:
        db.close()


async def pain_phase_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тап фазы боли: painphase:{sid}:{phase} (pain phase tap)."""
    query = update.callback_query
    await query.answer()
    parts = (query.data or "").split(":")
    if len(parts) != 3 or parts[2] not in dict(PAIN_PHASES):
        return
    user = get_user(update.effective_chat.id)
    if not user:
        return
    db = SessionLocal()
    try:
        session_id = int(parts[1])
        fb = db.query(TrainingFeedback).filter(
            TrainingFeedback.session_id == session_id,
            TrainingFeedback.user_id == user.id,
        ).first()
        if fb is None:
            return
        fb.pain_phase = parts[2]
        db.commit()
        await query.edit_message_reply_markup(reply_markup=None)
        phase_label = dict(PAIN_PHASES)[parts[2]]
        await context.bot.send_message(
            update.effective_chat.id,
            f"✅ Записал: дискомфорт {fb.pain_level}/10 ({phase_label}). Слежу за динамикой.")
    except (ValueError, TypeError):
        return
    except Exception as e:
        db.rollback()
        logger.error("Pain phase save error: %s", e, exc_info=True)
    finally:
        db.close()


async def wellness_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вечерний опрос: wellness:{level} (evening wellness tap)."""
    query = update.callback_query
    await query.answer()
    parts = (query.data or "").split(":")
    if len(parts) != 2:
        return
    try:
        level = int(parts[1])
    except ValueError:
        return
    if not 0 <= level <= 10:
        return
    user = get_user(update.effective_chat.id)
    if not user:
        return
    db = SessionLocal()
    try:
        _upsert_wellness_pain(db, user.id, level)
        await query.edit_message_text(
            "✅ Спасибо! Хорошего вечера." if level == 0
            else f"✅ Записал: колено {level}/10. Учту в завтрашнем вердикте.")
    except Exception as e:
        db.rollback()
        logger.error("Wellness save error: %s", e, exc_info=True)
    finally:
        db.close()
