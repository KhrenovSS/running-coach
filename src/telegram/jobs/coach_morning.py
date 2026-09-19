# Утренний вердикт (Morning verdict) — DEV_PLAN §9 C7
# Обычный путь (19.09.2026): скриншот сна за сегодня → вердикт сразу
# (handlers/sleep_photo → maybe_deliver_after_sleep). Джоба 09:30 — РЕЗЕРВ для дней без
# скриншота; дедуп — заявка coach/morning_state (params_json), иначе резерв дублировал бы
# ранний вердикт. Гейт initiative ∈ {normal, high}.
# LLM через get_llm() (мост/ключ); при недоступности handle_chat(kind="morning")
# отдаёт ДЕТЕРМИНИРОВАННЫЙ вердикт со назначением (состояние + план дня, без LLM) —
# гарантированная доставка. При ТРАНЗИЕНТНОМ сбое моста дополнительно
# ставится отложенный повтор (_morning_upgrade_job): если мост поднимется в окне —
# пользователь получит уточнённый LLM-вердикт (инцидент 01.09.2026).

from __future__ import annotations

import asyncio
from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.coach import morning_state, orchestrator, planning
from src.coach.llm.config import (COACH_MORNING_RETRY_DELAY_S,
                                  COACH_MORNING_RETRY_MAX,
                                  COACH_MORNING_RETRY_STOP_HOUR,
                                  MORNING_SLEEP_RECHECK_DELAY_S)
from src.coach.llm.prompts import MORNING_PROMPT, MORNING_SLEEP_PROMPT
from src.coach.render import render_sleep_missing_note
from src.config import settings
from src.models import SessionLocal, User
from src.services.audit import AuditService
from src.services.repositories_coach import CoachRepository
from src.services.sleep_ingest import has_sleep_for_date
from src.telegram.utils import send_md_safe
from src.utils.logger import get_logger
from src.utils.timeutils import user_now

logger = get_logger("telegram.jobs.coach_morning")

RESEND_PREFIX = "🔄 С учётом сна:\n\n"
UNCHANGED_TEXT = "🌙 Сон учёл — план дня не меняется."
PROGRESS_TEXT = "🌅 Считаю план на день…"


def _morning_turn_blocking(user_id: int, prompt: str = MORNING_PROMPT,
                           suffix: str | None = None) -> orchestrator.ChatReply | None:
    """Sync-обёртка: сессия живёт только внутри треда (session never crosses threads).

    None — инициатива пользователя ниже normal (вердикт не шлём).
    Возвращает ChatReply целиком: джобе нужны source/retriable для решения о повторе.
    """
    db = SessionLocal()
    try:
        if orchestrator.get_initiative(user_id, db=db) not in ("normal", "high"):
            return None
        return orchestrator.handle_chat(user_id, prompt, db=db, kind="morning", suffix=suffix)
    finally:
        db.close()


def _morning_context_blocking(user_id: int) -> tuple[date, datetime, bool, str | None]:
    """Локальные «сегодня»/«сейчас», наличие скрина сна и пометка о его отсутствии.

    Зовётся из корутины напрямую: короткие запросы (в отличие от хода коуча, который
    уносится в тред). (Short reads stay in the loop; only the coach turn goes to a thread.)

    Пометка — только перед качественным днём (решение владельца 19.09.2026); чисел в ней нет.
    (Local day/now, sleep presence and the deterministic no-sleep note.)
    """
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        now = user_now(user)
        day = now.date()
        has_sleep = has_sleep_for_date(user_id, day, db=db)
        note = render_sleep_missing_note(
            has_sleep=has_sleep, hard_today=planning.hard_day_on(user_id, db=db, day=day))
        return day, now, has_sleep, ("\n\n" + note if note else None)
    finally:
        db.close()


def _last_morning_text_blocking(user_id: int) -> str | None:
    """Текст последнего утреннего сообщения коуча (для дедупа пересчёта со сном)."""
    db = SessionLocal()
    try:
        rows = CoachRepository.recent_messages(user_id, limit=4, db=db, kinds=("morning",))
        texts = [r.text for r in rows if r.role == "assistant" and r.text]
        return texts[-1] if texts else None
    finally:
        db.close()


def _claim_blocking(user_id: int, day: date, *, with_sleep: bool, now: datetime) -> bool:
    db = SessionLocal()
    try:
        return morning_state.claim(user_id, db=db, day=day, with_sleep=with_sleep, now=now)
    finally:
        db.close()


def _finish_blocking(user_id: int, day: date, *, sent: bool, with_sleep: bool,
                     now: datetime) -> None:
    db = SessionLocal()
    try:
        if sent:
            morning_state.mark_sent(user_id, db=db, day=day, with_sleep=with_sleep, now=now)
        else:
            morning_state.release(user_id, db=db, day=day)
    finally:
        db.close()


def _action_blocking(user_id: int) -> tuple[str, date, datetime]:
    """Решение по пришедшему скриншоту сна: (action, локальный день, локальное «сейчас»)."""
    day, now, has_sleep, _note = _morning_context_blocking(user_id)
    if not has_sleep:
        # Скрин распознан, но отнесён к другой дате (экран Coros часто несёт дату ночи):
        # сигнал сна читается только за сегодня (state.py) — ранний вердикт бессмыслен.
        return morning_state.SKIP, day, now
    db = SessionLocal()
    try:
        st = morning_state.state(user_id, db=db)
    finally:
        db.close()
    return morning_state.plan_action(st, day=day, now=now), day, now


async def _send_verdict(context, chat_id: int, user_id: int, text: str,
                        *, preview: str, source: str = "morning_verdict_job") -> None:
    """Отправить вердикт с Markdown-fallback + аудит (send verdict, audited)."""
    async def _send(t, **kw):
        return await context.bot.send_message(chat_id=chat_id, text=t, **kw)

    await send_md_safe(_send, text)
    db = SessionLocal()
    try:
        AuditService(db).log_telegram_sent(
            user_id=user_id, chat_id=chat_id, message_preview=preview, source=source)
    finally:
        db.close()


async def _deliver(context, *, user_id: int, chat_id: int, day: date, now: datetime,
                   with_sleep: bool, prompt: str = MORNING_PROMPT,
                   suffix: str | None = None, prefix: str = "",
                   source: str = "morning_verdict_job",
                   preview: str = "Morning verdict",
                   dedup_text: str | None = None,
                   progress: str | None = None) -> orchestrator.ChatReply | None:
    """Заявка → ход коуча → отправка → пометка. None — не отправлено (занято/инициатива).

    claim берём СИНХРОННО из корутины, до `await`: внутри event loop переключений нет,
    поэтому заявка атомарна относительно других тасков бота (джоба 09:30 vs хендлер фото).
    (Claim, run the turn, send, mark; the claim must stay outside the thread.)
    """
    if not _claim_blocking(user_id, day, with_sleep=with_sleep, now=now):
        logger.info("Morning verdict skipped (already sent today) user=%s", user_id)
        return None
    sent = False
    try:
        if progress:
            # Строка ожидания — ПОСЛЕ заявки: иначе при гонке с резервом 09:30 она
            # осталась бы висеть без вердикта. (Progress line only once the day is ours.)
            await context.bot.send_message(chat_id=chat_id, text=progress)
        reply = await asyncio.to_thread(_morning_turn_blocking, user_id, prompt, suffix)
        if reply is None:
            return None                      # инициатива off/low — день не занимаем
        # Пересчёт слово в слово повторил утренний вердикт (типично для детерминированного
        # пути без моста: сон ничего не изменил) — вместо копии одна строка.
        same = dedup_text is not None and reply.text.strip() == dedup_text.strip()
        await _send_verdict(context, chat_id, user_id,
                            UNCHANGED_TEXT if same else prefix + reply.text,
                            preview=preview, source=source)
        sent = True
        return reply
    finally:
        _finish_blocking(user_id, day, sent=sent, with_sleep=with_sleep, now=now)


def _within_retry_window() -> bool:
    """Не ставим повтор после COACH_MORNING_RETRY_STOP_HOUR локального времени."""
    now = datetime.now(ZoneInfo(settings.timezone))
    return now.hour < COACH_MORNING_RETRY_STOP_HOUR


async def morning_verdict_job(context) -> None:
    """Резерв 09:30: вердикт тем, кому он сегодня ещё не уходил (fallback verdicts)."""
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
            day, now, has_sleep, note = _morning_context_blocking(user_id)
            reply = await _deliver(context, user_id=user_id, chat_id=chat_id, day=day,
                                   now=now, with_sleep=has_sleep, suffix=note)
            if reply is None:
                continue
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


async def maybe_deliver_after_sleep(context, *, user_id: int, chat_id: int) -> None:
    """Пришёл скриншот сна → вердикт дня (19.09.2026). Точка входа для хендлера фото.

    send — вердикта сегодня ещё не было; resend — он ушёл без сна, шлём пересчёт;
    wait — ход 09:30 в полёте, одна отложенная перепроверка; skip — тишина.
    (Sleep screenshot → today's verdict, or a single sleep-aware recompute.)
    """
    if not settings.coach_enabled:
        return
    action, day, now = _action_blocking(user_id)
    if action == morning_state.WAIT:
        if context.job_queue is not None:
            context.job_queue.run_once(
                _sleep_recheck_job, MORNING_SLEEP_RECHECK_DELAY_S,
                data={"user_id": user_id, "chat_id": chat_id})
        return
    if action == morning_state.SKIP:
        logger.info("Sleep screenshot: no morning verdict needed user=%s", user_id)
        return

    resend = action == morning_state.RESEND
    prev = _last_morning_text_blocking(user_id) if resend else None
    reply = await _deliver(
        context, user_id=user_id, chat_id=chat_id, day=day, now=now, with_sleep=True,
        prompt=MORNING_SLEEP_PROMPT if resend else MORNING_PROMPT,
        prefix=RESEND_PREFIX if resend else "",
        source="morning_verdict_resend" if resend else "morning_verdict_sleep",
        preview="Morning verdict (sleep)", dedup_text=prev,
        # Ход коуча — десятки секунд; короткая строка ожидания, как в /plan и /report
        progress=PROGRESS_TEXT)
    if reply is not None and reply.source == "fallback" and reply.retriable \
            and _within_retry_window() and context.job_queue is not None:
        context.job_queue.run_once(
            _morning_upgrade_job, COACH_MORNING_RETRY_DELAY_S,
            data={"targets": [(user_id, chat_id)], "attempt": 1})


async def _sleep_recheck_job(context) -> None:
    """Перепроверка после «ход 09:30 был в полёте»: ровно одна попытка (single recheck)."""
    data = context.job.data or {}
    user_id, chat_id = data.get("user_id"), data.get("chat_id")
    if user_id is None or chat_id is None:
        return
    try:
        await maybe_deliver_after_sleep(context, user_id=user_id, chat_id=chat_id)
    except Exception as e:
        logger.error("Sleep recheck failed for user=%s: %s", user_id, e, exc_info=True)


async def _morning_upgrade_job(context) -> None:
    """Отложенный повтор: добрать LLM-вердикт для юзеров, чей мост лёг утром.

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
                                    preview="Morning verdict (upgrade)",
                                    source="morning_verdict_job")
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
