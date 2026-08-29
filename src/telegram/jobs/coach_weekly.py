# Недельный отчёт коуча (Weekly coach report job) — DEV_PLAN §9 C8
# Воскресенье 19:00 (до вечернего опроса 21:00); гейт initiative ∈ {normal, high}.
# LLM через get_llm() (мост/ключ); при недоступности — детерминированный дайджест
# (fallback уже внутри weekly_report).

from __future__ import annotations

import asyncio

from src.coach import orchestrator
from src.config import settings
from src.models import SessionLocal, User
from src.telegram.utils import send_md_safe
from src.utils.logger import get_logger

logger = get_logger("telegram.jobs.coach_weekly")


def _weekly_turn_blocking(user_id: int) -> tuple[str | None, str | None]:
    """Sync-обёртка: сессия живёт только внутри треда (session never crosses threads).

    (report, plan): отчёт + карточка плана следующей недели (второе сообщение,
    решение владельца 29.08.2026). (None, None) — инициатива ниже normal.
    """
    from src.coach.weekly_plan import generate_weekly_plan

    db = SessionLocal()
    try:
        if orchestrator.get_initiative(user_id, db=db) not in ("normal", "high"):
            return None, None
        report = orchestrator.weekly_report(user_id, db=db).text
        try:
            plan = generate_weekly_plan(user_id, db=db)
        except Exception as e:  # план не должен ронять отчёт
            logger.error("Weekly plan failed for user=%s: %s", user_id, e,
                         exc_info=True)
            plan = None
        return report, plan
    finally:
        db.close()


async def coach_weekly_job(context) -> None:
    """Разослать недельный отчёт активным пользователям (send weekly reports)."""
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
            report, plan = await asyncio.to_thread(_weekly_turn_blocking, user_id)
            if report is None:
                continue

            async def _send(t, **kw):
                return await context.bot.send_message(chat_id=chat_id, text=t, **kw)

            await send_md_safe(_send, report)
            if plan is not None:
                await send_md_safe(_send, plan)
        except Exception as e:  # джоба не должна умирать на одном пользователе
            logger.error("Weekly report failed for user=%s: %s",
                         user_id, e, exc_info=True)
