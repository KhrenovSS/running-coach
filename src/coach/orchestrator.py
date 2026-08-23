# Оркестратор коуча (Coach orchestrator) — DEV_PLAN §7/§9
#
# C4: детерминированные сценарии (без LLM). LLM-путь подключается в C6/C7 через
# DI-параметр `llm` — сигнатуры не изменятся. Все функции получают db от вызывающего.
# (C4: deterministic scenarios; the LLM path plugs in via the `llm` DI parameter.)

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from src.coach.contracts import WorkoutProposal
from src.coach.llm.agent import run_turn
from src.coach.llm.client import CoachLLM, get_llm
from src.coach.llm.config import COACH_HISTORY_TURNS, COACH_MAX_TURNS_PER_DAY
from src.coach.llm.prompts import build_messages, build_system_blocks, build_today_block
from src.coach.llm.schemas import LogSuggestion
from src.coach.prescriber import finalize
from src.coach.render import render_prescription, render_review, render_state_card
from src.coach.rules.p1_safety import evaluate_safety
from src.coach.skills import workout
from src.coach.state import assess_state
from src.coach.tools.serialize import jsonable
from src.exceptions import CoachError, LLMUnavailableError
from src.models import TrainingFeedback, User, UserModel, WellnessReport
from src.services.repositories_coach import CoachRepository
from src.utils.logger import get_logger
from dataclasses import dataclass, field

logger = get_logger("coach.orchestrator")


@dataclass
class ChatReply:
    """Ответ коуча хендлеру: текст + опциональная кнопка записи боли (chat reply)."""
    text: str
    log_suggestion: LogSuggestion | None = None
    source: str = "fallback"          # llm | fallback

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
    prescription = finalize(None, state, db=db, persist=True)
    return render_state_card(state) + "\n\n" + render_prescription(prescription)


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
                   llm: CoachLLM, kind: str) -> ChatReply:
    """LLM-ход: state+verdict в контекст → агент → clamp → рендер (one LLM turn)."""
    from datetime import date as _date

    user = db.query(User).filter(User.id == user_id).first()
    state = assess_state(user_id, db=db)
    verdict = evaluate_safety(state)
    state_json = jsonable(state)
    state_json.pop("signals", None)
    today_block = build_today_block(state_json, jsonable(verdict),
                                    _date.today().isoformat())
    system = build_system_blocks(_profile(user))
    messages = build_messages(_history(user_id, db=db), today_block, message)

    turn, usage = run_turn(llm, user_id=user_id, db=db,
                           system=system, messages=messages)

    text = turn.message
    if turn.proposal is not None:
        proposal = WorkoutProposal(
            workout_type=turn.proposal.workout_type,
            target_zone=turn.proposal.target_zone,
            duration_min=turn.proposal.duration_min,
            distance_km=turn.proposal.distance_km,
            structure=turn.proposal.structure,
            rationale=list(turn.proposal.rationale),
        )
        prescription = finalize(proposal, state, db=db, persist=True, source="llm")
        text += "\n\n" + render_prescription(prescription)
    if turn.followup_question:
        text += "\n\n" + turn.followup_question

    from src.coach.llm.anthropic_client import estimate_cost_usd
    CoachRepository.save_message(user_id, "user", message, db=db, kind=kind)
    CoachRepository.save_message(
        user_id, "assistant", text, db=db, kind=kind,
        meta={"stop_reason": "end_turn", "tool_calls": usage.get("tool_calls", []),
              "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
              "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0)},
        tokens_in=usage.get("input_tokens"), tokens_out=usage.get("output_tokens"),
        cost_usd=estimate_cost_usd(usage))
    return ChatReply(text=text, log_suggestion=turn.log_suggestion, source="llm")


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
        text = ("Чат с тренером пока работает в базовом режиме (LLM не настроен).\n"
                "Вот твоё текущее состояние:\n\n" + render_state_card(state))
        CoachRepository.save_message(user_id, "user", message, db=db, kind=kind)
        CoachRepository.save_message(user_id, "assistant", text, db=db, kind=kind,
                                     meta={"fallback": True})
        return ChatReply(text=text, source="fallback")


def on_workout_completed(user_id: int, session_id: int, *, db: Session, llm=None) -> str:
    """Разбор завершённой тренировки (workout review). C4: детерминированный."""
    review = workout.evaluate_session(user_id, session_id, db=db)
    return render_review(review)


def evening_check_needed(user_id: int, *, db: Session) -> bool:
    """Нужен ли вечерний вопрос: пропускаем, если боль сегодня уже записана.

    (Evening question needed? Skipped when today's pain is already recorded.)
    """
    today = datetime.now(timezone.utc).date()
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
