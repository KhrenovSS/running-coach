# Утренний вердикт (Morning verdict job) — DEV_PLAN §9 C7
# 09:30 (10:00 занято проверкой синка); гейт initiative ∈ {normal, high}.
# LLM через get_llm() (мост/ключ); при недоступности — детерминированный вердикт
# (fallback уже внутри handle_chat).

from __future__ import annotations

import asyncio

from src.coach import orchestrator
from src.coach.llm.prompts import MORNING_PROMPT
from src.config import settings
from src.models import SessionLocal, User
from src.telegram.utils import send_md_safe
from src.utils.logger import get_logger

logger = get_logger("telegram.jobs.coach_morning")


def _morning_turn_blocking(user_id: int) -> str | None:
    """Sync-обёртка: сессия живёт только внутри треда (session never crosses threads).

    None — инициатива пользователя ниже normal (вердикт не шлём).
    """
    db = SessionLocal()
    try:
        if orchestrator.get_initiative(user_id, db=db) not in ("normal", "high"):
            return None
        return orchestrator.handle_chat(user_id, MORNING_PROMPT,
                                        db=db, kind="morning").text
    finally:
        db.close()


async def morning_verdict_job(context) -> None:
    """Разослать утренний вердикт активным пользователям (send morning verdicts)."""
    if not settings.coach_enabled:
        return
    db = SessionLocal()
    try:
        # (user_id, chat_id) — скаляры, дальше сессия не нужна (scalars only)
        targets = [(u.id, u.telegram_chat_id) for u in db.query(User).filter(
            User.telegram_chat_id.isnot(None),
            User.is_active.is_(True),
        ).all()]
    finally:
        db.close()

    for user_id, chat_id in targets:
        try:
            text = await asyncio.to_thread(_morning_turn_blocking, user_id)
            if text is None:
                continue

            async def _send(t, **kw):
                return await context.bot.send_message(chat_id=chat_id, text=t, **kw)

            await send_md_safe(_send, text)
        except Exception as e:  # джоба не должна умирать на одном пользователе
            logger.error("Morning verdict failed for user=%s: %s",
                         user_id, e, exc_info=True)
