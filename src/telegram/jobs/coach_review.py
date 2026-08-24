# Исполнение отложенных разборов (Deferred review execution) — DEV_PLAN §9 D5
#
# Три пути к одному run_pending_review (дедуп — атомарный claim в БД):
# 1) trigger_review — сразу после терминального тапа боли;
# 2) single_review_job — run_once через грейс после RPE-тапа;
# 3) pending_reviews_job — каждые 10 мин: таймаут 30 мин (синк из app-контейнера,
#    рестарты), re-claim зависших running, expire протухших pending.

from __future__ import annotations

import asyncio

from src.coach import review_flow
from src.config import settings
from src.config.constants import (
    REVIEW_PENDING_TTL_H,
    REVIEW_STALE_RUNNING_MIN,
    REVIEW_WAIT_MAX_MIN,
)
from src.models import SessionLocal, User
from src.services.repositories_insights import InsightRepository
from src.telegram.utils import send_md_safe
from src.utils.logger import get_logger

logger = get_logger("telegram.jobs.coach_review")


def _review_blocking(user_id: int, session_id: int) -> str | None:
    """Sync-обёртка: сессия живёт только внутри треда (session stays in-thread)."""
    db = SessionLocal()
    try:
        return review_flow.run_pending_review(session_id, db=db)
    finally:
        db.close()


async def _send_review(context, chat_id: int, text: str) -> None:
    async def _send(t, **kw):
        return await context.bot.send_message(chat_id=chat_id, text=t, **kw)
    await send_md_safe(_send, text)


async def trigger_review(context, chat_id: int, user_id: int, session_id: int) -> None:
    """Исполнить разбор сейчас (после тапа боли); LLM — только в to_thread."""
    try:
        text = await asyncio.to_thread(_review_blocking, user_id, session_id)
        if text:
            await _send_review(context, chat_id, text)
    except Exception as e:  # fire-and-forget не должен ронять loop бота
        logger.error("Triggered review failed for session=%s: %s",
                     session_id, e, exc_info=True)


async def single_review_job(context) -> None:
    """run_once после RPE-тапа: грейс истёк — разбираем с тем, что есть."""
    d = context.job.data or {}
    await trigger_review(context, d["chat_id"], d["user_id"], d["session_id"])


async def pending_reviews_job(context) -> None:
    """Периодический сборщик: таймауты, зависшие running, протухшие pending."""
    if not settings.coach_enabled:
        return
    db = SessionLocal()
    try:
        InsightRepository.reclaim_stale_running(REVIEW_STALE_RUNNING_MIN, db=db)
        expired = InsightRepository.expire_older_than(REVIEW_PENDING_TTL_H, db=db)
        if expired:
            logger.info("Expired %d stale pending reviews", expired)
        due = review_flow.due_review_sessions(REVIEW_WAIT_MAX_MIN, db=db)
        # (user_id → chat_id) скалярами, дальше сессия не нужна (scalars only)
        chat_ids = {u.id: u.telegram_chat_id for u in db.query(User).filter(
            User.id.in_({uid for uid, _ in due})).all()} if due else {}
    finally:
        db.close()

    for user_id, session_id in due:
        chat_id = chat_ids.get(user_id)
        if chat_id is None:
            continue
        try:
            text = await asyncio.to_thread(_review_blocking, user_id, session_id)
            if text:
                await _send_review(context, chat_id, text)
        except Exception as e:  # джоба не должна умирать на одном разборе
            logger.error("Pending review job failed for session=%s: %s",
                         session_id, e, exc_info=True)
