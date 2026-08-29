# Оркестратор коуча (Coach orchestrator) — DEV_PLAN §7/§9
#
# C4: детерминированные сценарии (без LLM). LLM-путь подключается в C6/C7 через
# DI-параметр `llm` — сигнатуры не изменятся. Все функции получают db от вызывающего.
# (C4: deterministic scenarios; the LLM path plugs in via the `llm` DI parameter.)

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from src.coach.contracts import Prescription, WorkoutProposal
from src.coach.llm.agent import run_turn
from src.coach.llm.client import CoachLLM, get_llm
from src.coach.llm.config import (
    COACH_EFFORT_CHAT,
    COACH_EFFORT_PLAN,
    COACH_ENRICH_RECENT_LIMIT,
    COACH_ENRICH_WEEKS,
    COACH_HISTORY_TURNS,
    COACH_MAX_TURNS_PER_DAY,
    COACH_RECENT_REVIEWS_LIMIT,
    COACH_WEEKLY_REPORT_RECENT,
    COACH_WEEKLY_REPORT_WEEKS,
    COACH_WEEKLY_REVIEWS_LIMIT,
)
from src.coach.llm.prompts import (
    REVIEW_PROMPT,
    WEEKLY_PROMPT,
    build_messages,
    build_system_blocks,
    build_today_block,
)
from src.coach.llm.schemas import LogSuggestion, ReviewAssessment
from src.coach.prescriber import finalize, save_prescription, user_max_hr
from src.coach.render import (
    render_prescription,
    render_prescription_short,
    render_review,
    render_state_card,
    render_weekly,
)
from src.coach.rules.p1_safety import evaluate_safety
from src.coach.skills import workout
from src.coach.state import assess_state
from src.coach.tools.registry import run_tool
from src.coach.tools.serialize import jsonable
from src.coach.turn_context import build_extras as _build_extras
from src.coach.turn_context import unchanged_today as _unchanged_today
from src.exceptions import CoachError, LLMUnavailableError
from src.models import TrainingFeedback, User, UserModel, WellnessReport
from src.services.repositories_coach import CoachRepository
from src.utils.logger import get_logger
from src.utils.timeutils import fmt_local, local_dt, user_now
from dataclasses import dataclass, field

logger = get_logger("coach.orchestrator")


@dataclass
class ChatReply:
    """Ответ коуча хендлеру: текст + опциональная кнопка записи боли (chat reply)."""
    text: str
    log_suggestion: LogSuggestion | None = None
    source: str = "fallback"          # llm | fallback
    assessment: ReviewAssessment | None = None   # D3: только kind=review
    assistant_message_id: int | None = None      # D3: link в workout_insights

INITIATIVE_LEVELS = ("off", "low", "normal", "high")
INITIATIVE_DEFAULT = "high"  # решение владельца 23.08.2026: старт на максимуме


def get_initiative(user_id: int, *, db: Session) -> str:
    """Уровень инициативы бота из UserModel.params_json (bot initiative level)."""
    um = db.query(UserModel).filter(UserModel.user_id == user_id).first()
    if um and um.params_json and um.params_json.get("initiative") in INITIATIVE_LEVELS:
        return um.params_json["initiative"]
    return INITIATIVE_DEFAULT


def set_initiative(user_id: int, level: str, *, db: Session) -> str:
    """Установить уровень инициативы (set initiative level); неизвестный → default."""
    if level not in INITIATIVE_LEVELS:
        level = INITIATIVE_DEFAULT
    um = db.query(UserModel).filter(UserModel.user_id == user_id).first()
    if um is None:
        um = UserModel(user_id=user_id, params_json={"initiative": level})
        db.add(um)
    else:
        params = dict(um.params_json or {})
        params["initiative"] = level
        um.params_json = params
    db.commit()
    return level


def morning_verdict(user_id: int, *, db: Session) -> str:
    """Утренний вердикт: состояние + назначение через safety (morning verdict)."""
    state = assess_state(user_id, db=db)
    user = db.query(User).filter(User.id == user_id).first()
    # Якорь дат — локальное «сейчас» пользователя (#262: не UTC-дата сервера)
    prescription = finalize(None, state, db=db, persist=True, now=user_now(user))
    return (render_state_card(state) + "\n\n"
            + render_prescription(prescription, max_hr=user_max_hr(user), user=user))


def _profile(user: User) -> dict:
    """Стабильный профиль для кэшируемого system-блока (stable cached profile)."""
    return {
        "age": user.age, "max_hr": user.max_hr, "sport_level": user.sport_level,
        "goal_type": user.goal_type, "goal_target": user.goal_target,
        "weight_kg": user.weight_kg,
        "injuries": "колено — возврат после травмы (беречь)",
    }


def _history(user_id: int, *, db: Session) -> list[dict]:
    rows = CoachRepository.recent_messages(user_id, limit=COACH_HISTORY_TURNS, db=db)
    return [{"role": m.role, "content": m.text}
            for m in rows if m.role in ("user", "assistant")]


def _llm_chat_turn(user_id: int, message: str, *, db: Session,
                   llm: CoachLLM, kind: str, extras: dict | None = None,
                   allow_proposal: bool = True,
                   effort: str = COACH_EFFORT_CHAT) -> ChatReply:
    """LLM-ход: state+verdict в контекст → агент → clamp → рендер (one LLM turn)."""
    user = db.query(User).filter(User.id == user_id).first()
    state = assess_state(user_id, db=db)
    verdict = evaluate_safety(state)
    state_json = jsonable(state)
    state_json.pop("signals", None)
    if extras is None:
        extras = _build_extras(user_id, db=db)
    # Только JSON-копия: clamp() сравнивает earliest_next_hard в UTC
    # (JSON copy only — clamp() keeps comparing in UTC)
    verdict_json = jsonable(verdict)
    if verdict.earliest_next_hard is not None:
        verdict_json["earliest_next_hard"] = fmt_local(
            local_dt(verdict.earliest_next_hard, user))
    today_block = build_today_block(state_json, verdict_json,
                                    fmt_local(user_now(user)), extras=extras)
    system = build_system_blocks(_profile(user))
    messages = build_messages(_history(user_id, db=db), today_block, message)

    turn, usage = run_turn(llm, user_id=user_id, db=db,
                           system=system, messages=messages, effort=effort)

    text = turn.message
    max_hr = user_max_hr(user)
    if turn.proposal is not None and not allow_proposal:
        # Разбор/отчёт — про прошлое: назначение даёт утренний вердикт/чат (C8).
        # (Reviews look backward: proposals are dropped, not clamped/persisted.)
        logger.info("Proposal dropped for kind=%s user=%s", kind, user_id)
    elif turn.proposal is not None:
        proposal = WorkoutProposal(
            workout_type=turn.proposal.workout_type,
            target_zone=turn.proposal.target_zone,
            duration_min=turn.proposal.duration_min,
            distance_km=turn.proposal.distance_km,
            target_pace_min_km=turn.proposal.target_pace_min_km,
            structure=turn.proposal.structure,
            rationale=list(turn.proposal.rationale),
            for_days_ahead=turn.proposal.for_days_ahead,
        )
        prescription = finalize(proposal, state, db=db, persist=False, source="llm",
                                now=user_now(user))
        if kind == "chat" and _unchanged_today(prescription, user_id, db=db):
            # Дедуп (решение владельца 26.08.2026): назначение не изменилось —
            # одна строка-напоминание, без новой строки в recommendations.
            # (Unchanged plan → one reminder line, no duplicate recommendation row.)
            text += "\n\n" + render_prescription_short(prescription, max_hr=max_hr)
        else:
            save_prescription(prescription, state, db=db)
            text += "\n\n" + render_prescription(prescription, max_hr=max_hr, user=user)
    if turn.followup_question:
        text += "\n\n" + turn.followup_question

    assessment = turn.assessment
    if assessment is not None and kind != "review":
        # Оценка уместна только в разборе — в чате/утре игнорируем (D3)
        logger.warning("Unexpected assessment for kind=%s user=%s — dropped", kind, user_id)
        assessment = None

    from src.coach.llm.anthropic_client import estimate_cost_usd
    CoachRepository.save_message(user_id, "user", message, db=db, kind=kind)
    assistant_msg = CoachRepository.save_message(
        user_id, "assistant", text, db=db, kind=kind,
        meta={"stop_reason": "end_turn", "tool_calls": usage.get("tool_calls", []),
              "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
              "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0)},
        tokens_in=usage.get("input_tokens"), tokens_out=usage.get("output_tokens"),
        cost_usd=estimate_cost_usd(usage))
    return ChatReply(text=text, log_suggestion=turn.log_suggestion, source="llm",
                     assessment=assessment, assistant_message_id=assistant_msg.id)


def handle_chat(user_id: int, message: str, *, db: Session,
                llm: CoachLLM | None = None, kind: str = "chat") -> ChatReply:
    """Свободный чат: LLM при наличии ключа, иначе детерминированный fallback.

    (Free chat: the LLM path with a key, deterministic fallback otherwise.)
    """
    llm = llm if llm is not None else get_llm()
    turns = CoachRepository.turns_today(user_id, db=db)
    if turns >= COACH_MAX_TURNS_PER_DAY:
        return ChatReply(text="На сегодня лимит разговоров исчерпан — продолжим завтра. "
                              "Твоё состояние всегда доступно по /verdict.")
    try:
        return _llm_chat_turn(user_id, message, db=db, llm=llm, kind=kind)
    except (LLMUnavailableError, CoachError) as e:
        logger.info("LLM chat fallback for user=%s: %s", user_id, e)
        state = assess_state(user_id, db=db)
        text = ("Тренер сейчас отвечает в базовом режиме.\n"
                "Вот твоё текущее состояние:\n\n" + render_state_card(state))
        CoachRepository.save_message(user_id, "user", message, db=db, kind=kind)
        CoachRepository.save_message(user_id, "assistant", text, db=db, kind=kind,
                                     meta={"fallback": True})
        return ChatReply(text=text, source="fallback")


def _deterministic_review(user_id: int, session_id: int, *, db: Session) -> str:
    """Детерминированный разбор + персист в историю и итог (deterministic review path)."""
    from src.services.repositories_insights import InsightRepository
    text = render_review(workout.evaluate_session(user_id, session_id, db=db))
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
            allow_proposal=True)
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
                  llm: CoachLLM | None = None) -> ChatReply:
    """Недельный отчёт (weekly report, C8): итоги недели + план прозой.

    План недели живёт только строкой coach_messages kind='weekly' (DEV_PLAN §12).
    """
    llm = llm if llm is not None else get_llm()
    try:
        if CoachRepository.turns_today(user_id, db=db) >= COACH_MAX_TURNS_PER_DAY:
            raise LLMUnavailableError("дневной бюджет ходов исчерпан")
        return _llm_chat_turn(
            user_id, WEEKLY_PROMPT, db=db, llm=llm, kind="weekly",
            extras=_build_extras(user_id, db=db, weeks=COACH_WEEKLY_REPORT_WEEKS,
                                 limit=COACH_WEEKLY_REPORT_RECENT,
                                 insights_limit=COACH_WEEKLY_REVIEWS_LIMIT,
                                 guides_query="объём прогрессия неделя план база"),
            allow_proposal=False, effort=COACH_EFFORT_PLAN)
    except (LLMUnavailableError, CoachError) as e:
        logger.info("LLM weekly fallback for user=%s: %s", user_id, e)
        summary = run_tool("get_weekly_summary", {"weeks": COACH_ENRICH_WEEKS},
                           user_id=user_id, db=db)
        text = render_weekly(summary)
        CoachRepository.save_message(user_id, "assistant", text, db=db,
                                     kind="weekly", meta={"fallback": True})
        return ChatReply(text=text, source="fallback")


def evening_check_needed(user_id: int, *, db: Session) -> bool:
    """Нужен ли вечерний вопрос: пропускаем, если боль сегодня уже записана.

    (Evening question needed? Skipped when today's pain is already recorded.)
    """
    # «Сегодня» — по поясу пользователя (#267: вечер 21:00 MSK = уже завтра в UTC+)
    user = db.query(User).filter(User.id == user_id).first()
    today = user_now(user).date()
    wellness = db.query(WellnessReport).filter(
        WellnessReport.user_id == user_id,
        WellnessReport.report_date == today,
        WellnessReport.pain_level.isnot(None),
    ).first()
    if wellness is not None:
        return False
    since = datetime.now(timezone.utc) - timedelta(hours=20)
    fb = db.query(TrainingFeedback).filter(
        TrainingFeedback.user_id == user_id,
        TrainingFeedback.created_at >= since,
        TrainingFeedback.pain_level.isnot(None),
    ).first()
    return fb is None
