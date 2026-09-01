# Утренний вердикт (Morning verdict job) — DEV_PLAN §9 C7
# 09:30 (10:00 занято проверкой синка); гейт initiative ∈ {normal, high}.
# LLM через get_llm() (мост/ключ); при недоступности handle_chat(kind="morning")
# отдаёт ДЕТЕРМИНИРОВАННЫЙ вердикт со назначением (состояние + план дня, без LLM) —
# гарантированная доставка в 09:30. При ТРАНЗИЕНТНОМ сбое моста дополнительно
# ставится отложенный повтор (_morning_upgrade_job): если мост поднимется в окне —
# пользователь получит уточнённый LLM-вердикт (инцидент 01.09.2026).

from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from src.coach import orchestrator
from src.coach.llm.config import (COACH_MORNING_RETRY_DELAY_S,
                                  COACH_MORNING_RETRY_MAX,
                                  COACH_MORNING_RETRY_STOP_HOUR)
from src.coach.llm.prompts import MORNING_PROMPT
from src.config import settings
from src.models import SessionLocal, User
from src.services.audit import AuditService
from src.telegram.utils import send_md_safe
from src.utils.logger import get_logger

logger = get_logger("telegram.jobs.coach_morning")


def _morning_turn_blocking(user_id: int) -> orchestrator.ChatReply | None:
    """Sync-обёртка: сессия живёт только внутри треда (session never crosses threads).

    None — инициатива пользователя ниже normal (вердикт не шлём).
    Возвращает ChatReply целиком: джобе нужны source/retriable для решения о повторе.
    """
    db = SessionLocal()
    try:
        if orchestrator.get_initiative(user_id, db=db) not in ("normal", "high"):
            return None
        return orchestrator.handle_chat(user_id, MORNING_PROMPT, db=db, kind="morning")
    finally:
        db.close()


async def _send_verdict(context, chat_id: int, user_id: int, text: str,
                        *, preview: str) -> None:
    """Отправить вердикт с Markdown-fallback + аудит (send verdict, audited)."""
    async def _send(t, **kw):
        return await context.bot.send_message(chat_id=chat_id, text=t, **kw)

    await send_md_safe(_send, text)
    db = SessionLocal()
    try:
        AuditService(db).log_telegram_sent(
            user_id=user_id, chat_id=chat_id, message_preview=preview,
            source="morning_verdict_job")
    finally:
        db.close()


def _within_retry_window() -> bool:
    """Не ставим повтор после COACH_MORNING_RETRY_STOP_HOUR локального времени."""
    now = datetime.now(ZoneInfo(settings.timezone))
    return now.hour < COACH_MORNING_RETRY_STOP_HOUR


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

    deferred: list[tuple[int, int]] = []   # юзеры с транзиентным fallback → повтор
    for user_id, chat_id in targets:
        try:
            reply = await asyncio.to_thread(_morning_turn_blocking, user_id)
            if reply is None:
                continue
            await _send_verdict(context, chat_id, user_id, reply.text,
                                preview="Morning verdict")
            # Транзиентный сбой моста: вердикт со назначением уже доставлен,
            # но попробуем добрать LLM-версию, когда мост поднимется.
            if reply.source == "fallback" and reply.retriable:
                deferred.append((user_id, chat_id))
        except Exception as e:  # джоба не должна умирать на одном пользователе
            logger.error("Morning verdict failed for user=%s: %s",
                         user_id, e, exc_info=True)

    if deferred and _within_retry_window():
        logger.info("Morning verdict: %d юзеров в отложенном повторе (мост лёг)",
                    len(deferred))
        context.job_queue.run_once(
            _morning_upgrade_job, COACH_MORNING_RETRY_DELAY_S,
            data={"targets": deferred, "attempt": 1})


async def _morning_upgrade_job(context) -> None:
    """Отложенный повтор: добрать LLM-вердикт для юзеров, чей мост лёг в 09:30.

    Шлём уточнение ТОЛЬКО при успехе LLM (иначе у пользователя уже есть полноценный
    детерминированный вердикт — второе сообщение было бы шумом). Пока транзиентно и
    попытки не исчерпаны — переносим ещё раз (retry loop across scheduled runs).
    """
    if not settings.coach_enabled:
        return
    data = context.job.data or {}
    targets: list[tuple[int, int]] = data.get("targets", [])
    attempt: int = data.get("attempt", 1)

    still_deferred: list[tuple[int, int]] = []
    for user_id, chat_id in targets:
        try:
            reply = await asyncio.to_thread(_morning_turn_blocking, user_id)
            if reply is None:
                continue
            if reply.source == "llm":
                text = "🔄 Мост восстановился — уточнённый вердикт:\n\n" + reply.text
                await _send_verdict(context, chat_id, user_id, text,
                                    preview="Morning verdict (upgrade)")
            elif reply.retriable:
                still_deferred.append((user_id, chat_id))
            # постоянная ошибка → тихо: детерминированный вердикт уже доставлен утром
        except Exception as e:
            logger.error("Morning upgrade failed for user=%s: %s",
                         user_id, e, exc_info=True)

    if still_deferred and attempt < COACH_MORNING_RETRY_MAX and _within_retry_window():
        context.job_queue.run_once(
            _morning_upgrade_job, COACH_MORNING_RETRY_DELAY_S,
            data={"targets": still_deferred, "attempt": attempt + 1})
