# Болезнь и пауза после неё (#322, 07.09.2026) — гайд 50 (Швец): с температурой не бегать,
# после выздоровления — перерыв по таблице (нижняя граница, ILLNESS_PAUSE_DAYS). Состояние —
# UserModel.params_json["illness"] (без миграции). Safety читает его через сигналы состояния
# (правило 21 p1_safety, прогноз по дню плана через day_offset), /plan — через заблокированные
# даты, чат/утро — через blocked_reason. LLM только сообщает факт (CoachTurn.illness), сроки
# считает код. (Illness state and post-illness pause; deterministic, no LLM numbers.)

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from src.coach.config import ILLNESS_PAUSE_DAYS
from src.models import UserModel
from src.utils.logger import get_logger

logger = get_logger(__name__)

SICK_BLOCK_DAYS = 10_000   # болен без сообщения о выздоровлении — закрыто «до сообщения»
KIND_RU = {"cold": "ОРВИ/бронхит", "flu": "грипп", "angina": "ангина",
           "pneumonia": "пневмония", "other": "болезнь"}


def illness_state(user_id: int, *, db: Session) -> dict:
    """Сохранённое состояние болезни ({} — записей нет). (Persisted illness record.)"""
    um = db.query(UserModel).filter(UserModel.user_id == user_id).first()
    if um is None or not um.params_json:
        return {}
    return dict(um.params_json.get("illness") or {})


def _save(user_id: int, data: dict, *, db: Session) -> None:
    um = db.query(UserModel).filter(UserModel.user_id == user_id).first()
    if um is None:
        um = UserModel(user_id=user_id, params_json={})
        db.add(um)
    params = dict(um.params_json or {})
    params["illness"] = data
    um.params_json = params
    db.commit()


def record_illness(report, user_id: int, *, db: Session, now: datetime) -> str:
    """Записать сообщение «заболел»/«выздоровел» и вернуть детерминированную строку ответа.

    report — IllnessReport (status, kind, days_ago). Пауза после выздоровления —
    ILLNESS_PAUSE_DAYS[kind] от даты выздоровления; kind без уточнения — из прежней записи,
    иначе «other». (Record the report; the pause is computed by code, not prose.)
    """
    today = now.date()
    when = today - timedelta(days=int(report.days_ago or 0))
    prev = illness_state(user_id, db=db)
    kind = report.kind or prev.get("kind") or "other"
    if report.status == "sick":
        _save(user_id, {"status": "sick", "kind": kind, "since": when.isoformat(),
                        "updated_at": now.isoformat()}, db=db)
        logger.info("Illness recorded for user=%s: %s since %s", user_id, kind, when)
        return (f"Зафиксировал болезнь ({KIND_RU[kind]}): тренировки закрыты до выздоровления — "
                "с температурой и симптомами не бегаем. Напиши, когда симптомы уйдут, "
                "посчитаю паузу перед возвращением.")
    pause_days = ILLNESS_PAUSE_DAYS.get(kind, ILLNESS_PAUSE_DAYS["other"])
    until = when + timedelta(days=pause_days)
    _save(user_id, {"status": "recovered", "kind": kind, "since": prev.get("since"),
                    "recovered_at": when.isoformat(), "pause_until": until.isoformat(),
                    "updated_at": now.isoformat()}, db=db)
    logger.info("Recovery recorded for user=%s: %s, pause until %s", user_id, kind, until)
    if until <= today:
        return ("Выздоровление зафиксировано: пауза после болезни уже вышла — возвращаемся мягко, "
                "первые пробежки короткие и разговорным темпом.")
    return (f"Выздоровление зафиксировано. После «{KIND_RU[kind]}» перерыв {pause_days} дн. "
            f"(гайд 50): бег не раньше {until:%d.%m}, дальше — мягкий вход.")


def block_days(state: dict, today: date) -> int | None:
    """Сколько дней, начиная с today, бег закрыт: None — блока нет; болен — SICK_BLOCK_DAYS;
    выздоровел — дни до pause_until (сам pause_until уже открыт). (Blocked days from today.)"""
    status = state.get("status")
    if status == "sick":
        return SICK_BLOCK_DAYS
    if status == "recovered" and state.get("pause_until"):
        left = (date.fromisoformat(state["pause_until"]) - today).days
        return left if left > 0 else None
    return None


def is_blocked(state: dict, today: date, when: date) -> bool:
    days = block_days(state, today)
    return days is not None and (when - today).days < days


def paused_dates(state: dict, today: date, start: date, end: date) -> list[date]:
    """Даты [start, end], закрытые болезнью/паузой — для окна планирования."""
    return [start + timedelta(days=i) for i in range((end - start).days + 1)
            if is_blocked(state, today, start + timedelta(days=i))]


def illness_signals(state: dict, today: date) -> dict:
    """Сырьё правила 21 p1_safety (pure): блок в днях от сегодня + статус для причины."""
    return {"illness_block_days": block_days(state, today),
            "illness_status": state.get("status") if block_days(state, today) else None,
            "illness_pause_until": state.get("pause_until")}


def context_block(state: dict, today: date) -> dict | None:
    """Блок для контекста LLM/плана: что система знает о болезни (None — ничего)."""
    days = block_days(state, today)
    if days is None:
        return None
    return {"status": state.get("status"), "kind": state.get("kind"),
            "since": state.get("since"), "recovered_at": state.get("recovered_at"),
            "pause_until": state.get("pause_until"),
            "blocked_days_from_today": None if days >= SICK_BLOCK_DAYS else days}


def blocked_reason(user_id: int, *, db: Session, when: date, today: date) -> str | None:
    """Гвард чата/утра: назначение на закрытый болезнью день отбрасывается (строка-отказ)."""
    state = illness_state(user_id, db=db)
    if not is_blocked(state, today, when):
        return None
    if state.get("status") == "sick":
        return "Тренировку на этот день не назначаю: болезнь — сначала выздоровление."
    return (f"Тренировку на этот день не назначаю: пауза после болезни до "
            f"{date.fromisoformat(state['pause_until']):%d.%m} (гайд 50).")
