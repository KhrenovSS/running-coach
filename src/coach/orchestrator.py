# Оркестратор коуча (Coach orchestrator) — DEV_PLAN §7/§9
#
# C4: детерминированные сценарии (без LLM). LLM-путь подключается в C6/C7 через
# DI-параметр `llm` — сигнатуры не изменятся. Все функции получают db от вызывающего.
# (C4: deterministic scenarios; the LLM path plugs in via the `llm` DI parameter.)
# #329 (11.09.2026): здесь — разбор тренировки (on_workout_completed) и недельный отчёт
# (weekly_report); LLM-ход чата/утра и инициатива — chat_flow.py.

from __future__ import annotations

from sqlalchemy.orm import Session

# #329 (11.09.2026): чат/утро/инициатива — chat_flow.py; имена реэкспортируются, вызовы
# `orchestrator.handle_chat(...)` из бота и тестов остаются валидными. (Re-exported chat flow.)
from src.coach.chat_flow import (  # noqa: F401 — реэкспорт
    INITIATIVE_DEFAULT,
    INITIATIVE_LEVELS,
    ChatReply,
    _llm_chat_turn,
    get_initiative,
    handle_chat,
    morning_verdict,
    set_initiative,
)
from src.coach.llm.client import CoachLLM, get_llm
from src.coach.llm.config import (
    COACH_EFFORT_PLAN,
    COACH_MAX_TURNS_PER_DAY,
    COACH_WEEKLY_REPORT_RECENT,
    COACH_WEEKLY_REPORT_WEEKS,
    COACH_WEEKLY_REVIEWS_LIMIT,
)
from src.coach.llm.prompts import REVIEW_PROMPT, WEEKLY_PROMPT
from src.coach.render import render_gps_warning, render_review
from src.coach.skills import workout
from src.coach.turn_context import build_extras as _build_extras
from src.coach.render_week_report import render_week_report
from src.coach.week_report import build_week_report
from src.exceptions import CoachError, LLMUnavailableError
from src.services.repositories_coach import CoachRepository
from src.utils.logger import get_logger

logger = get_logger("coach.orchestrator")


def _gps_warning_suffix(user_id: int, session_id: int, *, db: Session) -> str:
    """Хвост-предупреждение о недостоверном GPS для разбора; '' — GPS в порядке.
    (GPS-unreliable suffix for reviews; empty string when GPS is fine.)"""
    session, _ = CoachRepository.session_with_feedback(user_id, session_id, db=db)
    warning = render_gps_warning(session.gps_quality if session else None)
    return f"\n\n{warning}" if warning else ""


def _deterministic_review(user_id: int, session_id: int, *, db: Session) -> str:
    """Детерминированный разбор + персист в историю и итог (deterministic review path)."""
    from src.services.repositories_insights import InsightRepository
    text = (render_review(workout.evaluate_session(user_id, session_id, db=db))
            + _gps_warning_suffix(user_id, session_id, db=db))
    msg = CoachRepository.save_message(user_id, "assistant", text, db=db,
                                       kind="review", meta={"fallback": True})
    InsightRepository.finish(session_id, db=db, source="fallback",
                             coach_message_id=msg.id)
    return text


def _merged_flags(llm_flags: list[str], computed: dict | None) -> list[str]:
    """Флаги assessment = детерминированные из computed + субъективные LLM (§6.2).

    Маппинг имён (decoupling_* → hr_drift_high) зафиксирован кодом; LLM-флаги,
    дублирующие вычислимое, но отсутствующие в computed, отбрасываются.
    Детерминированные первыми, cap 4 (лимит схемы ReviewAssessment).
    """
    from typing import get_args

    from src.analysis.session_metrics import FLAG_TO_ASSESSMENT
    from src.coach.llm.schemas import SUBJECTIVE_FLAGS, FlagValue

    allowed = set(get_args(FlagValue))
    deterministic: list[str] = []
    for f in (computed or {}).get("flags") or []:
        mapped = FLAG_TO_ASSESSMENT.get(f, f)
        # heat/hilly/hr_*_baseline остаются контекстом в computed, в enum их нет
        if mapped in allowed and mapped not in deterministic:
            deterministic.append(mapped)
    subjective = [f for f in llm_flags
                  if f in SUBJECTIVE_FLAGS and f not in deterministic]
    return (deterministic + subjective)[:4]


def on_workout_completed(user_id: int, session_id: int, *, db: Session,
                         llm: CoachLLM | None = None, use_llm: bool = True) -> str:
    """Разбор завершённой тренировки (workout review). C8: через LLM с fallback.

    use_llm=False — сразу детерминированная карточка (гейт initiative=low,
    старые тренировки батча). Дневной бюджет ходов уважается.
    """
    if not use_llm or CoachRepository.turns_today(user_id, db=db) >= COACH_MAX_TURNS_PER_DAY:
        return _deterministic_review(user_id, session_id, db=db)
    llm = llm if llm is not None else get_llm()
    try:
        # D6: proposal в разборе разрешён (решение владельца 24.08 — «оба канала»);
        # коррекция следующей тренировки идёт через обычный finalize/clamp.
        reply = _llm_chat_turn(
            user_id, REVIEW_PROMPT, db=db, llm=llm, kind="review",
            extras=_build_extras(user_id, db=db, session_id=session_id),
            allow_proposal=True,
            suffix=_gps_warning_suffix(user_id, session_id, db=db))
        # Итог разбора → workout_insights (пишет оркестратор из провалидированного
        # output — LLM в БД не пишет, инвариант §1.4). (Persist the review outcome.)
        from src.services.repositories_insights import InsightRepository
        from src.services.workout_insights import get_or_compute
        a = reply.assessment
        assessment = a.model_dump() if a else None
        if assessment is not None:
            assessment["flags"] = _merged_flags(
                assessment.get("flags") or [],
                get_or_compute(user_id, session_id, db=db))
        InsightRepository.finish(
            session_id, db=db, source="llm",
            assessment=assessment,
            effort_match=a.effort_match if a else None,
            carry_forward=a.carry_forward if a else None,
            coach_message_id=reply.assistant_message_id)
        return reply.text
    except (LLMUnavailableError, CoachError) as e:
        logger.info("LLM review fallback for user=%s: %s", user_id, e)
        return _deterministic_review(user_id, session_id, db=db)


def weekly_report(user_id: int, *, db: Session,
                  llm: CoachLLM | None = None, report: dict | None = None) -> ChatReply:
    """Недельный отчёт (C8 → C8.1, 03.09.2026): проза LLM (интерпретация) + детерминированная
    карточка «Итоги недели» (числа — код). report — уже посчитанные числа (джоб считает
    один раз для отчёта и плана). Персистентный план следующей недели создаёт
    weekly_plan.generate_weekly_plan отдельным ходом (решение владельца 29.08.2026).
    """
    if report is None:
        report = build_week_report(user_id, db=db)
    card = render_week_report(report)
    llm = llm if llm is not None else get_llm()
    try:
        if CoachRepository.turns_today(user_id, db=db) >= COACH_MAX_TURNS_PER_DAY:
            raise LLMUnavailableError("дневной бюджет ходов исчерпан")
        extras = _build_extras(user_id, db=db, weeks=COACH_WEEKLY_REPORT_WEEKS,
                               limit=COACH_WEEKLY_REPORT_RECENT,
                               insights_limit=COACH_WEEKLY_REVIEWS_LIMIT,
                               guides_query="объём прогрессия неделя план база")
        # weekly_summary дублирует week_report (и считал недели по UTC) — убираем из контекста
        extras.pop("weekly_summary (get_weekly_summary)", None)
        extras["week_report (week_report)"] = report
        return _llm_chat_turn(
            user_id, WEEKLY_PROMPT, db=db, llm=llm, kind="weekly",
            extras=extras, allow_proposal=False, effort=COACH_EFFORT_PLAN,
            extra_card=card)
    except (LLMUnavailableError, CoachError) as e:
        logger.info("LLM weekly fallback for user=%s: %s", user_id, e)
        text = "Тренер сейчас недоступен — вот цифры недели.\n\n" + card
        CoachRepository.save_message(user_id, "assistant", text, db=db,
                                     kind="weekly", meta={"fallback": True})
        return ChatReply(text=text, source="fallback")
