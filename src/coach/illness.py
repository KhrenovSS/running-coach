# Болезнь и возврат после неё (#322, 07.09.2026; ступени — решение владельца 29.09.2026) — гайд 50:
# с температурой не бегать. После выздоровления — две ступени от даты, когда прошли симптомы:
# полный покой ILLNESS_REST_DAYS[kind] (правило 21 safety, allow_training=False), затем окно
# «только легко» ILLNESS_EASY_DAYS[kind] (правило 21b `illness_return`: Z2, без интенсива, короче).
# Состояние — UserModel.params_json["illness"] (без миграции; старые записи с pause_until считаются
# на чтении по новым константам). Safety читает его через сигналы состояния (прогноз по дню плана
# через day_offset), /plan — через закрытые даты (только полный покой), чат/утро — через
# blocked_reason. LLM только сообщает факт (CoachTurn.illness), сроки считает код.
# (Illness state and staged post-illness return; deterministic, no LLM numbers.)

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from src.coach.config import ILLNESS_EASY_DAYS, ILLNESS_REST_DAYS
from src.models import UserModel
from src.utils.logger import get_logger

logger = get_logger(__name__)

SICK_BLOCK_DAYS = 10_000   # болен без сообщения о выздоровлении — закрыто «до сообщения»
KIND_RU = {"cold": "ОРВИ/бронхит", "flu": "грипп", "angina": "ангина",
           "pneumonia": "пневмония", "other": "болезнь"}
DOCTOR_KINDS = ("angina", "pneumonia")   # осложнения на сердце — возврат с разрешения врача (гайд 50)


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


def _days(table: dict, kind: str | None) -> int:
    return table.get(kind or "other", table["other"])


def stages(state: dict) -> tuple[date, date] | None:
    """(rest_until, easy_until) для записи о выздоровлении; None — нет выздоровления.

    Старые записи (до 29.09.2026) несут только pause_until — ступени считаем от recovered_at по
    текущим константам, данные не мигрируем. (Staged dates; legacy rows computed on read.)
    """
    if state.get("status") != "recovered":
        return None
    if state.get("rest_until") and state.get("easy_until"):
        return date.fromisoformat(state["rest_until"]), date.fromisoformat(state["easy_until"])
    recovered = state.get("recovered_at")
    if not recovered:
        return None
    start = date.fromisoformat(recovered)
    kind = state.get("kind")
    return (start + timedelta(days=_days(ILLNESS_REST_DAYS, kind)),
            start + timedelta(days=_days(ILLNESS_EASY_DAYS, kind)))


def record_illness(report, user_id: int, *, db: Session, now: datetime) -> str:
    """Записать сообщение «заболел»/«выздоровел» и вернуть детерминированную строку ответа.

    report — IllnessReport (status, kind, days_ago). Ступени после выздоровления — от даты, когда
    прошли симптомы; kind без уточнения — из прежней записи, иначе «other».
    (Record the report; the stages are computed by code, not prose.)
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
                "посчитаю возврат к бегу.")
    rest_until = when + timedelta(days=_days(ILLNESS_REST_DAYS, kind))
    easy_until = when + timedelta(days=_days(ILLNESS_EASY_DAYS, kind))
    _save(user_id, {"status": "recovered", "kind": kind, "since": prev.get("since"),
                    "recovered_at": when.isoformat(), "rest_until": rest_until.isoformat(),
                    "easy_until": easy_until.isoformat(), "updated_at": now.isoformat()}, db=db)
    logger.info("Recovery recorded for user=%s: %s, rest until %s, easy until %s",
                user_id, kind, rest_until, easy_until)
    doctor = " (после «%s» — с разрешения врача)" % KIND_RU[kind] if kind in DOCTOR_KINDS else ""
    if easy_until <= today:
        return ("Выздоровление зафиксировано: окно возврата после болезни уже вышло — "
                "тренируемся в обычном режиме.")
    if rest_until <= today:
        return (f"Выздоровление зафиксировано. Бегать уже можно{doctor}, до {easy_until:%d.%m} — "
                "только лёгкие пробежки (2-я зона, без ускорений и интервалов, короче обычного), "
                "дальше обычный режим (гайд 50).")
    return (f"Выздоровление зафиксировано. После «{KIND_RU[kind]}» бег с {rest_until:%d.%m}{doctor}, "
            f"до {easy_until:%d.%m} — только лёгкие пробежки (2-я зона, без ускорений и интервалов, "
            "короче обычного), дальше обычный режим (гайд 50).")


def block_days(state: dict, today: date) -> int | None:
    """Сколько дней, начиная с today, бег закрыт полностью: None — блока нет; болен —
    SICK_BLOCK_DAYS; выздоровел — дни до rest_until (сам rest_until уже открыт). (Full block days.)"""
    if state.get("status") == "sick":
        return SICK_BLOCK_DAYS
    st = stages(state)
    if st is None:
        return None
    left = (st[0] - today).days
    return left if left > 0 else None


def easy_days(state: dict, today: date) -> int | None:
    """Сколько дней, начиная с today, действует окно «только легко» (включая дни полного покоя):
    None — окна нет. (Easy-only window length from today.)"""
    st = stages(state)
    if st is None:
        return None
    left = (st[1] - today).days
    return left if left > 0 else None


def is_blocked(state: dict, today: date, when: date) -> bool:
    days = block_days(state, today)
    return days is not None and (when - today).days < days


def paused_dates(state: dict, today: date, start: date, end: date) -> list[date]:
    """Даты [start, end], закрытые болезнью/полным покоем — для окна планирования."""
    return [start + timedelta(days=i) for i in range((end - start).days + 1)
            if is_blocked(state, today, start + timedelta(days=i))]


def illness_signals(state: dict, today: date) -> dict:
    """Сырьё правил 21/21b p1_safety (pure): блок и окно «легко» в днях от сегодня + статус."""
    block = block_days(state, today)
    easy = easy_days(state, today)
    st = stages(state)
    return {"illness_block_days": block,
            "illness_status": state.get("status") if block else None,
            "illness_rest_until": st[0].isoformat() if st else None,
            "illness_easy_days": easy,
            "illness_easy_until": st[1].isoformat() if st else None}


def context_block(state: dict, today: date) -> dict | None:
    """Блок для контекста LLM/плана: что система знает о болезни (None — ничего)."""
    block = block_days(state, today)
    easy = easy_days(state, today)
    if block is None and easy is None:
        return None
    st = stages(state)
    return {"status": state.get("status"), "kind": state.get("kind"),
            "since": state.get("since"), "recovered_at": state.get("recovered_at"),
            # полный покой: дней от сегодня (None при болезни — до сообщения о выздоровлении)
            "blocked_days_from_today": None if (block or 0) >= SICK_BLOCK_DAYS else block,
            "rest_until": st[0].isoformat() if st else None,
            # окно «только легко»: бег разрешён, Z2, без ускорений/интервалов, короче обычного
            "easy_until": st[1].isoformat() if st else None,
            "easy_days_from_today": easy}


def blocked_reason(user_id: int, *, db: Session, when: date, today: date) -> str | None:
    """Гвард чата/утра: назначение на день полного покоя отбрасывается (строка-отказ);
    окно «только легко» не блокирует — его сужает safety.clamp."""
    state = illness_state(user_id, db=db)
    if not is_blocked(state, today, when):
        return None
    if state.get("status") == "sick":
        return "Тренировку на этот день не назначаю: болезнь — сначала выздоровление."
    rest_until = stages(state)[0]
    return (f"Тренировку на этот день не назначаю: полный покой после болезни до "
            f"{rest_until:%d.%m}, дальше — только легко (гайд 50).")
