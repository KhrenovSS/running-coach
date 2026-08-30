# Приём скриншота сна в Telegram (Sleep-screenshot handler) — #257
#
# Пользователь присылает фото экрана сна Coros → vision-мост извлекает данные →
# запись в DailyMetrics. Числа в ответе — детерминированно из SleepShot, не из
# прозы модели. (Photo → vision → DailyMetrics; ack numbers are deterministic.)

from __future__ import annotations

import asyncio

import telegram.error
from telegram import Update
from telegram.ext import ContextTypes

from src.coach.vision import SleepShot, extract_sleep
from src.config import settings
from src.models import SessionLocal
from src.services.sleep_ingest import save_sleep_shot
from src.telegram.utils import get_user, send_md_safe
from src.utils.logger import get_logger

logger = get_logger("telegram.handlers.sleep_photo")

SLEEP_HINT = ("🌙 Пришли скриншот экрана сна из приложения Coros — "
              "я считаю длительность, фазы и оценку и учту их в тренировках.")


async def cmd_sleep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /sleep — попросить скриншот сна (ask for a sleep screenshot)."""
    if not get_user(update.effective_chat.id):
        await update.message.reply_text(
            "❌ Сначала используй /start чтобы зарегистрироваться.")
        return
    await update.message.reply_text(SLEEP_HINT)


async def handle_sleep_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Фото/картинка-документ → извлечь сон и сохранить (photo → sleep ingest)."""
    if not settings.coach_enabled:
        return
    user = get_user(update.effective_chat.id)
    if not user:
        return
    msg = update.message
    tg_file = None
    if msg.photo:
        tg_file = await msg.photo[-1].get_file()          # крупнейший размер
    elif msg.document and (msg.document.mime_type or "").startswith("image/"):
        tg_file = await msg.document.get_file()
    if tg_file is None:
        return

    await msg.reply_text("🌙 Читаю скриншот сна…")
    try:
        image_bytes = bytes(await tg_file.download_as_bytearray())
        text = await asyncio.to_thread(_ingest_blocking, user.id, image_bytes)
        await send_md_safe(msg.reply_text, text)
    except telegram.error.TelegramError as e:
        logger.error("Sleep photo error for user=%s: %s", user.id, e, exc_info=True)
        await msg.reply_text("😔 Не удалось обработать картинку — попробуй ещё раз.")


def _ingest_blocking(user_id: int, image_bytes: bytes) -> str:
    """Sync: vision → сохранение; сессия живёт внутри треда (thread-local session)."""
    shot = extract_sleep(image_bytes)
    if shot is None:
        return "😔 Тренер сейчас не смог прочитать картинку — попробуй чуть позже."
    if not shot.has_data():
        return ("🤔 Это не похоже на экран сна. Пришли скриншот именно экрана сна "
                "из приложения Coros (с длительностью и фазами).")
    db = SessionLocal()
    try:
        save_sleep_shot(user_id, shot, db=db)
    finally:
        db.close()
    return _render_ack(shot)


def _hm(minutes: int | None) -> str | None:
    if minutes is None:
        return None
    return f"{minutes // 60}ч {minutes % 60:02d}м"


def _render_ack(shot: SleepShot) -> str:
    """Подтверждение — числа детерминированно из SleepShot (deterministic ack)."""
    head = f"✅ Записал сон: *{_hm(shot.duration_min)}*" if shot.duration_min \
        else "✅ Записал данные сна"
    lines = [head]
    phases = []
    if shot.deep_pct is not None:
        phases.append(f"глубокий {shot.deep_pct}%")
    if shot.rem_pct is not None:
        phases.append(f"REM {shot.rem_pct}%")
    if shot.awake_min is not None:
        aw = f"бодрств. {_hm(shot.awake_min)}"
        if shot.awake_interruptions is not None:
            aw += f" ({shot.awake_interruptions} прерыв.)"
        phases.append(aw)
    if phases:
        lines.append(" · ".join(phases))
    tail = []
    if shot.sleep_stress is not None:
        tail.append(f"стресс сна {shot.sleep_stress}")
    if shot.bedtime_offset_min is not None:
        o = shot.bedtime_offset_min
        when = "позже" if o >= 0 else "раньше"
        tail.append(f"отход ко сну на {abs(o)} мин {when} обычного")
    if shot.score is not None:
        tail.append(f"оценка {shot.score}/100")
    if tail:
        lines.append(" · ".join(tail))
    return "\n".join(lines)
