# Факты из ответа LLM при построении плана (Plan-turn facts) — вынос из weekly_plan.py (лимит ~400
# строк/файл, 17.09.2026). Реплика «переделай план, сегодня не смогу / через неделю бегу десятку» уходит
# /plan-путём, минуя чат-ход, поэтому доступность, болезнь, проблемы и старты применяем здесь кодом.
# (Deterministic application of turn facts on the /plan path.)

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.orm import Session

from src.coach import concerns, illness, planning, races
from src.coach.llm.schemas import CoachTurn
from src.utils.logger import get_logger
from src.utils.timeutils import WEEKDAYS_RU_SHORT

logger = get_logger("coach.weekly_plan")


def apply_turn_facts(turn: CoachTurn, user_id: int, *, db: Session,
                                  targets: dict, apply_targets, today: date,
                                  now_local: datetime) -> tuple[dict, list[int], str]:
    """Доступность из ответа LLM применить детерминированно (инцидент 07.09.2026).

    Реплика «переделай план, сегодня не смогу» уходит /plan-путём, минуя чат-ход, поэтому
    отмены дней применяем здесь: available_weekdays → окно недели, available_again_days_ahead
    → снять отдых-отмену, unavailable_days_ahead → вычесть из days_ahead_allowed (rest-строки
    с маркером пишет вызывающий ПОСЛЕ гашения прежнего плана — иначе они погаснут).
    Возврат: (targets, cancelled_days, текст-хвост). (Deterministic availability from the turn.)
    """
    tail: list[str] = []
    recompute = False
    if turn.available_weekdays is not None:
        saved = planning.set_availability(user_id, db=db, weekdays=turn.available_weekdays)
        recompute = True
        if saved["weekdays"]:
            tail.append("Запомнил дни для бега: "
                        + ", ".join(WEEKDAYS_RU_SHORT[d] for d in saved["weekdays"]) + ".")
        else:
            tail.append("Запомнил: бегать можно в любой день недели.")
    if turn.available_again_days_ahead:
        reopened = planning.reopen_days(turn.available_again_days_ahead, user_id,
                                        db=db, now=now_local)
        if reopened:
            recompute = True
            tail.append(reopened)
    if turn.illness is not None:
        # #322: «заболел, переделай план» — запись болезни, дни паузы выпадают из окна
        tail.append(illness.record_illness(turn.illness, user_id, db=db, now=now_local))
        recompute = True
    if turn.concern is not None:
        # 10.09.2026: проблема названа в просьбе о плане — фиксируем, план её увидит в контексте
        tail.append(concerns.record_concern(turn.concern, user_id, db=db, now=now_local))
    for report in turn.races or []:
        # 17.09.2026 (#243 ч.1): «через неделю бегу десятку, переделай план» — старт в календарь, план
        # пересчитывается под новую фазу (тейпер/неделя старта)
        tail.append(races.record_race(report, user_id, db=db, now=now_local))
        recompute = True
    if recompute:
        targets = apply_targets(planning.week_targets(user_id, db=db, today=today,
                                                      now=now_local))
    cancelled = sorted(set(turn.unavailable_days_ahead or []))
    if cancelled:
        allowed = [d for d in targets["days_ahead_allowed"] if d not in cancelled]
        logger.info("Weekly plan: athlete unavailable days=%s user=%s", cancelled, user_id)
        targets = {**targets, "days_ahead_allowed": allowed}
    return targets, cancelled, "\n".join(tail)
