# Генерация недельного плана (Weekly plan generation) — решения владельца 29.08.2026
#
# LLM распределяет НЕДЕЛЮ по дням в рамках чисел, посчитанных planning.py;
# каждый день проходит finalize→clamp (Prescription только через safety);
# строки пишутся в recommendations со status='planned'. Fallback-плана нет:
# LLM недоступна → None (синтезировать неделю детерминированно небезопасно).
# (LLM distributes the week within deterministic targets; every day is clamped.)

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from src.coach import planning
from src.coach.contracts import Prescription, WorkoutProposal
from src.coach.llm.agent import run_turn
from src.coach.llm.anthropic_client import estimate_cost_usd
from src.coach.llm.client import CoachLLM, get_llm
from src.coach.llm.config import COACH_EFFORT_PLAN, COACH_MAX_TURNS_PER_DAY
from src.coach.llm.prompts import (
    PLAN_PROMPT,
    build_messages,
    build_system_blocks,
    build_today_block,
)
from src.coach.prescriber import finalize, save_prescription, user_max_hr
from src.services.repositories import latest_lthr
from src.coach.render_week import render_week_plan
from src.coach.safety import rehydrate
from src.coach.week_view import _active_rows, week_facts
from src.config.constants import RECOMMENDATION_STATUS_SUPERSEDED
from src.coach.rules.p1_safety import evaluate_safety
from src.coach.state import assess_state
from src.coach.tools.serialize import jsonable
from src.coach.turn_context import build_extras
from src.exceptions import CoachError, LLMUnavailableError
from src.models import Recommendation, User
from src.services.repositories_coach import CoachRepository
from src.utils.logger import get_logger
from src.utils.timeutils import fmt_local, local_dt, user_now

logger = get_logger("coach.weekly_plan")


def _clean_days(items: list[WorkoutProposal],
                allowed: list[int] | None = None) -> list[WorkoutProposal]:
    """Фильтр элементов плана: только дни из окна allowed (по умолчанию 1..7),
    без rest, последний на день побеждает. День 0 (сегодня) допустим только когда
    он в окне — остаток недели без пробежки сегодня (#293)."""
    allowed_set = set(allowed if allowed is not None else range(1, 8))
    by_day: dict[int, WorkoutProposal] = {}
    for it in items:
        if it.workout_type == "rest":
            continue  # пропуск дня = отдых (решение: rest не персистится)
        if it.for_days_ahead not in allowed_set:
            logger.info("Weekly plan item skipped: for_days_ahead=%s",
                        it.for_days_ahead)
            continue
        by_day[it.for_days_ahead] = it
    return [by_day[d] for d in sorted(by_day)]


def generate_weekly_plan(user_id: int, *, db: Session,
                         llm: CoachLLM | None = None,
                         now: datetime | None = None,
                         week_report: dict | None = None) -> str | None:
    """Составить и записать план недели; вернуть текст карточки или None.

    None — бюджет ходов исчерпан, LLM недоступна или план пуст.
    Среди недели — остаток текущей недели с вычетом сделанного (#293, решение
    владельца 02.09.2026); now — локальное «сейчас» (DI для тестов).
    """
    if CoachRepository.turns_today(user_id, db=db) >= COACH_MAX_TURNS_PER_DAY:
        logger.info("Weekly plan skipped: turn budget exhausted user=%s", user_id)
        return None
    llm = llm if llm is not None else get_llm()

    user = db.query(User).filter(User.id == user_id).first()
    now_local = now or user_now(user)
    today = now_local.date()
    targets = planning.week_targets(user_id, db=db, today=today)
    if not targets["days_ahead_allowed"]:
        # #294: окно доступности закрыло все дни окна планирования — честно сказать, не звать LLM
        names = targets["availability"].get("weekday_names")
        window = f"дни для бега: {', '.join(names)}" if names else "отменённые дни"
        logger.info("Weekly plan skipped: no available days user=%s", user_id)
        return (f"На оставшиеся дни недели бегать некуда ({window}) — новый план составлю "
                "в воскресенье вечером. Изменились планы — напиши «могу бегать в любой день».")
    review = planning.week_plan_review(user_id, db=db)
    state = assess_state(user_id, db=db)
    verdict = evaluate_safety(state)
    state_json = jsonable(state)
    state_json.pop("signals", None)

    extras = build_extras(user_id, db=db, weeks=4,
                          guides_query="план недели мезоцикл фазы объём прогрессия")
    extras["week_targets (planning)"] = targets
    if review is not None:
        extras["week_plan_review (planning)"] = review
    if week_report is not None:
        # Числа прошедшей недели (C8.1): план объясняет, что меняется и почему
        extras["week_report (week_report)"] = week_report

    verdict_json = jsonable(verdict)
    if verdict.earliest_next_hard is not None:
        verdict_json["earliest_next_hard"] = fmt_local(
            local_dt(verdict.earliest_next_hard, user))
    today_block = build_today_block(state_json, verdict_json,
                                    fmt_local(user_now(user)), extras=extras)
    system = build_system_blocks(_profile(user))
    messages = build_messages(_history(user_id, db=db), today_block, PLAN_PROMPT)

    try:
        turn, usage = run_turn(llm, user_id=user_id, db=db,
                               system=system, messages=messages,
                               effort=COACH_EFFORT_PLAN)
    except (LLMUnavailableError, CoachError) as e:
        logger.warning("Weekly plan LLM failed for user=%s: %s", user_id, e)
        return None

    items = _clean_days([WorkoutProposal(
        workout_type=p.workout_type, target_zone=p.target_zone,
        duration_min=p.duration_min, distance_km=p.distance_km,
        target_pace_min_km=p.target_pace_min_km, structure=p.structure,
        rationale=list(p.rationale), for_days_ahead=p.for_days_ahead,
    ) for p in (turn.weekly_plan or [])], allowed=targets["days_ahead_allowed"])
    if not items:
        logger.warning("Weekly plan empty for user=%s", user_id)
        return None
    # Потолок беговых дней на ОСТАТОК недели — детерминированно (решение владельца 02.09.2026)
    run_days_cap = targets["remaining_run_days_max"]
    items, dropped_days = planning.enforce_run_days(items, run_days_cap)

    first_offset = targets["days_ahead_allowed"][0]
    # День 0 при уже данном назначении на сегодня — осознанная замена (adjusted),
    # как утренний вердикт; проверяем ДО гашения. (Day-0 replaces today's row → adjusted.)
    had_today_row = first_offset == 0 and db.query(Recommendation).filter(
        Recommendation.user_id == user_id, Recommendation.for_date == today,
        Recommendation.status != RECOMMENDATION_STATUS_SUPERSEDED).first() is not None
    # Прежний план с первого планируемого дня гасим ДО записи нового (инцидент 02.09.2026:
    # строки первого /plan «ожили» после перепланирования). (Supersede before saving.)
    superseded = planning.supersede_future_rows(
        user_id, db=db, from_date=today + timedelta(days=first_offset))
    prescriptions: list[Prescription] = []
    for proposal in items:
        p = finalize(proposal, state, db=db, persist=False, source="llm",
                     now=now_local)
        status = "adjusted" if (proposal.for_days_ahead == 0 and had_today_row) else "planned"
        save_prescription(p, state, db=db, status=status)
        prescriptions.append(p)

    # Карточка — одна картина недели: прошедшие дни фактом (week_view) + новый остаток
    week_start = date.fromisoformat(targets["week_start"])
    rows = _active_rows(user_id, db=db, week_start=week_start)
    past = [rehydrate(r) for d, r in sorted(rows.items()) if d < today]
    text = (turn.message + "\n\n"
            + render_week_plan(past + prescriptions, targets, max_hr=user_max_hr(user),
                               lthr=latest_lthr(user_id, db=db), today=today,
                               facts=week_facts(rows, db=db, today=today)))
    if dropped_days:
        text += (f"\n⚠️ Беговых дней урезано до {run_days_cap}: "
                 "частота растёт не быстрее +1 в неделю.")
    CoachRepository.save_message(user_id, "user", PLAN_PROMPT, db=db, kind="plan")
    CoachRepository.save_message(
        user_id, "assistant", text, db=db, kind="plan",
        meta={"days": len(prescriptions),
              "clamped": sum(1 for p in prescriptions if p.clamped),
              "superseded": superseded, "dropped_days": dropped_days,
              "prose": turn.message,   # #258: история берёт прозу без карточки
              "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0)},
        tokens_in=usage.get("input_tokens"), tokens_out=usage.get("output_tokens"),
        cost_usd=estimate_cost_usd(usage))
    planning.advance_mesocycle(user_id, db=db, targets=targets)
    logger.info("Weekly plan saved: user=%s days=%s week=%s superseded=%s dropped=%s",
                user_id, len(prescriptions), targets["week_start"], superseded,
                dropped_days)
    return text


def _profile(user: User) -> dict:
    from src.coach.turn_context import profile
    return profile(user)


def _history(user_id: int, *, db: Session) -> list[dict]:
    from src.coach.turn_context import history
    return history(user_id, db=db)
