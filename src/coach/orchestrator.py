# Оркестратор коуча (Coach orchestrator) — DEV_PLAN §7/§9
#
# C4: детерминированные сценарии (без LLM). LLM-путь подключается в C6/C7 через
# DI-параметр `llm` — сигнатуры не изменятся. Все функции получают db от вызывающего.
# (C4: deterministic scenarios; the LLM path plugs in via the `llm` DI parameter.)

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from src.coach.prescriber import finalize
from src.coach.render import render_prescription, render_review, render_state_card
from src.coach.skills import workout
from src.coach.state import assess_state
from src.models import TrainingFeedback, UserModel, WellnessReport
from src.utils.logger import get_logger

logger = get_logger("coach.orchestrator")

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


def handle_chat(user_id: int, message: str, *, db: Session, llm=None) -> str:
    """Свободный чат. C4: детерминированный ответ (LLM подключается в C6/C7).

    (Free chat; deterministic in C4, the LLM path arrives with C6/C7.)
    """
    state = assess_state(user_id, db=db)
    return ("Чат с тренером пока работает в базовом режиме (LLM не настроен).\n"
            "Вот твоё текущее состояние:\n\n" + render_state_card(state))


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
