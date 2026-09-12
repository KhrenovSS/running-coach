# Полевой ПАНО в Telegram (Field LTHR in Telegram, M3.2 — 12.09.2026)
#
#   /lthr <уд/мин>   — ручной ввод (тест вне системы / лаборатория): запись, пересчёт, потолки зон
#   lthr:set:<v>     — кнопка подтверждения результата теста из карточки разбора
#   lthr:ignore      — оставить якорь Coros
# Session-bound user в сессии хендлера (уроки #236); тяжёлое — в потоке.

import asyncio
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import ContextTypes

from src.coach import lthr_field
from src.models import SessionLocal, User
from src.utils.logger import get_logger

logger = get_logger("telegram.handlers.lthr")


def _apply_blocking(chat_id: int, value: int, method: str, source: str) -> str:
    """Записать ПАНО и пересчитать окно тренировок (в потоке, своя сессия)."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_chat_id == chat_id).first()
        if not user:
            return "❌ Пользователь не найден. Используй /start чтобы зарегистрироваться."
        if not lthr_field.valid_value(value, user.max_hr):
            return (f"❌ Значение {value} вне разумного диапазона: ПАНО должен быть выше "
                    f"{lthr_field.LTHR_SANITY_MIN} и ниже максимума {user.max_hr}.")
        lthr_field.set_field_lthr(user.id, value, db=db, method=method,
                                  now=datetime.now(timezone.utc), source=source)
        n = lthr_field.reanalyze_recent(db, user.id)
        zones = lthr_field.zone_ceilings_text(user.max_hr, value) if user.max_hr else ""
        return (f"✅ Полевой ПАНО {value} уд/мин сохранён — теперь это якорь зон "
                f"(Coros — запасной). {zones}\n↻ Пересчитано тренировок: {n}.")
    except Exception as e:
        db.rollback()
        logger.error("lthr apply error: %s", e, exc_info=True)
        return "😔 Ошибка при сохранении ПАНО."
    finally:
        db.close()


async def cmd_lthr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/lthr <уд/мин> — ручной ввод полевого ПАНО."""
    args = context.args or []
    if len(args) != 1 or not args[0].isdigit():
        await update.message.reply_text(
            "Использование: /lthr <пульс>, например /lthr 158 — средний пульс последних 20 минут "
            "30-минутного ровного максимального усилия (полевой тест ПАНО).")
        return
    text = await asyncio.to_thread(_apply_blocking, update.effective_chat.id, int(args[0]),
                                   "manual", "telegram_command")
    await update.message.reply_text(text)


async def lthr_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Кнопки lthr:set:<v> / lthr:ignore из карточки разбора теста."""
    query = update.callback_query
    await query.answer()
    parts = (query.data or "").split(":")
    if len(parts) == 2 and parts[1] == "ignore":
        await query.edit_message_text("Ок, якорь зон оставил как есть (ПАНО Coros).")
        return
    if len(parts) != 3 or parts[1] != "set" or not parts[2].isdigit():
        return
    text = await asyncio.to_thread(_apply_blocking, update.effective_chat.id, int(parts[2]),
                                   "test30", "telegram_button")
    await query.edit_message_text(text)
