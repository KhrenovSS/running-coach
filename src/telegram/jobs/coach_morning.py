# Утренний вердикт (Morning verdict job) — DEV_PLAN §9 C7
# 09:30 (10:00 занято проверкой синка); гейт initiative ∈ {normal, high}.
# LLM через get_llm() (мост/ключ); при недоступности — детерминированный вердикт
# (fallback уже внутри handle_chat).

from __future__ import annotations

from src.coach import orchestrator
from src.config import settings
from src.models import SessionLocal, User
from src.utils.logger import get_logger

logger = get_logger("telegram.jobs.coach_morning")

MORNING_PROMPT = ("Утренний вердикт: что мне сегодня делать — тренироваться или "
                  "отдыхать, и если бежать, то как?")


async def morning_verdict_job(context) -> None:
    """Разослать утренний вердикт активным пользователям (send morning verdicts)."""
    if not settings.coach_enabled:
        return
    db = SessionLocal()
    try:
        users = db.query(User).filter(
            User.telegram_chat_id.isnot(None),
            User.is_active.is_(True),
        ).all()
        for user in users:
            if orchestrator.get_initiative(user.id, db=db) not in ("normal", "high"):
                continue
            try:
                reply = orchestrator.handle_chat(user.id, MORNING_PROMPT,
                                                 db=db, kind="morning")
                await context.bot.send_message(chat_id=user.telegram_chat_id,
                                               text=reply.text, parse_mode="Markdown")
            except Exception as e:  # джоба не должна умирать на одном пользователе
                logger.error("Morning verdict failed for user=%s: %s",
                             user.id, e, exc_info=True)
    finally:
        db.close()
