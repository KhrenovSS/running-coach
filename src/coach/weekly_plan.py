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
from src.coach.knowledge.loader import plan_guides_queries
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
from src.coach.planning_safety import (
    apply_safety_to_targets,
    cap_long_run,
    cap_week_volume,
    easy_too_hard_counts_by_day,
    project_state,
    quality_blocked,
    quality_reopens_at,
)
from src.analysis.session_metrics import FLAG_EASY_TOO_HARD
from src.coach.config import EASY_TOO_HARD_LOOKBACK_DAYS
from src.services.repositories_insights import InsightRepository
from src.coach.segments import segments_from_schema
from src.coach.prescriber import finalize, save_prescription, user_max_hr
from src.services.repositories import latest_lthr
from src.coach.render_week import render_week_plan
from src.coach.safety import rehydrate
from src.coach.week_view import _active_rows, week_facts
from src.config.constants import RECOMMENDATION_STATUS_SUPERSEDED
from src.coach.rules.p1_safety import evaluate_safety
from src.coach.state import assess_state
from src.coach.tools.serialize import jsonable
from src.coach.turn_context import build_extras, recent_athlete_requests
from src.exceptions import CoachError, LLMUnavailableError
from src.coach.llm.schemas import CoachTurn
from src.models import Recommendation, User
from src.services.repositories_coach import CoachRepository
from src.utils.logger import get_logger
from src.utils.timeutils import WEEKDAYS_RU_SHORT, fmt_local, local_dt, user_now

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


def _no_days_text(targets: dict) -> str:
    """Окно доступности закрыло все дни планирования — честный текст без LLM (#294)."""
    names = targets["availability"].get("weekday_names")
    window = f"дни для бега: {', '.join(names)}" if names else "отменённые дни"
    return (f"На оставшиеся дни недели бегать некуда ({window}) — новый план составлю "
            "в воскресенье вечером. Изменились планы — напиши «могу бегать в любой день».")


def _apply_availability_from_turn(turn: CoachTurn, user_id: int, *, db: Session,
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
    if recompute:
        targets = apply_targets(planning.week_targets(user_id, db=db, today=today))
    cancelled = sorted(set(turn.unavailable_days_ahead or []))
    if cancelled:
        allowed = [d for d in targets["days_ahead_allowed"] if d not in cancelled]
        logger.info("Weekly plan: athlete unavailable days=%s user=%s", cancelled, user_id)
        targets = {**targets, "days_ahead_allowed": allowed}
    return targets, cancelled, "\n".join(tail)


def generate_weekly_plan(user_id: int, *, db: Session,
                         llm: CoachLLM | None = None,
                         now: datetime | None = None,
                         week_report: dict | None = None,
                         athlete_text: str | None = None) -> str | None:
    """Составить и записать план недели; вернуть текст карточки или None.

    None — бюджет ходов исчерпан, LLM недоступна или план пуст.
    Среди недели — остаток текущей недели с вычетом сделанного (#293, решение
    владельца 02.09.2026); now — локальное «сейчас» (DI для тестов).
    athlete_text — реплика подопечного, вызвавшая перепланирование из чата
    (инцидент 07.09.2026: «сегодня не могу» терялась — план ставил тренировку на сегодня);
    сохраняется как chat-сообщение и уходит LLM в контексте.
    """
    if CoachRepository.turns_today(user_id, db=db) >= COACH_MAX_TURNS_PER_DAY:
        logger.info("Weekly plan skipped: turn budget exhausted user=%s", user_id)
        return None
    llm = llm if llm is not None else get_llm()

    user = db.query(User).filter(User.id == user_id).first()
    now_local = now or user_now(user)
    today = now_local.date()
    targets = planning.week_targets(user_id, db=db, today=today)
    if not targets["days_ahead_allowed"] and not athlete_text:
        # #294: окно доступности закрыло все дни окна планирования — честно сказать, не звать LLM
        # (с репликой подопечного LLM всё же зовём: она может открыть дни заново)
        logger.info("Weekly plan skipped: no available days user=%s", user_id)
        return _no_days_text(targets)
    review = planning.week_plan_review(user_id, db=db)
    state = assess_state(user_id, db=db)
    verdict = evaluate_safety(state)
    # Правило 17 (лёгкие слишком быстро) — 7-дневное окно по дате тренировки: прогнозируем,
    # с какого дня недели оно перестанет срабатывать (07.09.2026: план обнулял качество на всю
    # неделю по сегодняшнему вердикту). Остальные правила прогнозу не поддаются — блок на окно.
    # (Project the rule-17 counter per day; other rules stay as of today.)
    counts = easy_too_hard_counts_by_day(
        InsightRepository.recent_flag_sessions(user_id, FLAG_EASY_TOO_HARD, db=db,
                                               days=EASY_TOO_HARD_LOOKBACK_DAYS),
        now=now_local)

    def _apply_targets(t: dict) -> dict:
        # Интенсив закрыт safety → потолки качества ДО промпта (06.09.2026: иначе LLM
        # закладывает темповую, clamp режет её молча, проза расходится с картой)
        reopen = (quality_reopens_at(state, counts, now=now_local, days=t["days_ahead_allowed"])
                  if quality_blocked(verdict) else None)
        out = apply_safety_to_targets(t, verdict, quality_from_days_ahead=reopen)
        if reopen is not None:
            out["quality_allowed_from_date"] = (today + timedelta(days=reopen)).isoformat()
            logger.info("Quality reopens on day +%s for user=%s (rule-17 projection)",
                        reopen, user_id)
        return out

    targets = _apply_targets(targets)
    state_json = jsonable(state)
    state_json.pop("signals", None)

    # Возврат после паузы → гайды ходьба→бег и план возврата (Швец 47 / Дэниелс 61)
    extras = build_extras(user_id, db=db, weeks=4,
                          guides_query=plan_guides_queries(targets))
    extras["week_targets (planning)"] = targets
    requests_ = recent_athlete_requests(user_id, db=db)
    if requests_:
        # Просьбы подопечного за неделю (06.09.2026): обещанное, но отложенное — назвать, не замолчать
        extras["athlete_requests (chat, 7d)"] = requests_
    if review is not None:
        extras["week_plan_review (planning)"] = review
    if week_report is not None:
        # Числа прошедшей недели (C8.1): план объясняет, что меняется и почему
        extras["week_report (week_report)"] = week_report
    if athlete_text:
        # Реплика-триггер перепланирования: LLM видит её и заполняет unavailable_days_ahead
        extras["athlete_message (now)"] = athlete_text

    verdict_json = jsonable(verdict)
    if verdict.earliest_next_hard is not None:
        verdict_json["earliest_next_hard"] = fmt_local(
            local_dt(verdict.earliest_next_hard, user))
    today_block = build_today_block(state_json, verdict_json,
                                    fmt_local(user_now(user)), extras=extras)
    system = build_system_blocks(_profile(user))
    messages = build_messages(_history(user_id, db=db), today_block, PLAN_PROMPT)
    if athlete_text:
        # Реплика не должна пропасть из истории и athlete_requests (после сборки history —
        # иначе два user-сообщения подряд). (Persist the trigger text as a chat message.)
        CoachRepository.save_message(user_id, "user", athlete_text, db=db, kind="chat")

    try:
        turn, usage = run_turn(llm, user_id=user_id, db=db,
                               system=system, messages=messages,
                               effort=COACH_EFFORT_PLAN)
    except (LLMUnavailableError, CoachError) as e:
        logger.warning("Weekly plan LLM failed for user=%s: %s", user_id, e)
        return None

    targets, cancelled, avail_tail = _apply_availability_from_turn(
        turn, user_id, db=db, targets=targets, apply_targets=_apply_targets, today=today,
        now_local=now_local)
    if not targets["days_ahead_allowed"]:
        # Все оставшиеся дни закрыты (в т.ч. только что отменённые) — отмены всё же записать
        tail = _cancel_tail(cancelled, user_id, state, db=db, now_local=now_local)
        logger.info("Weekly plan skipped after turn: no available days user=%s", user_id)
        return "\n\n".join(t for t in (avail_tail, tail, _no_days_text(targets)) if t)

    items = _clean_days([WorkoutProposal(
        workout_type=p.workout_type, target_zone=p.target_zone,
        duration_min=p.duration_min, distance_km=p.distance_km,
        target_pace_min_km=p.target_pace_min_km, structure=p.structure,
        # Сегменты (ускорения/структура) — как в чате (06.09.2026: терялись → обещанные
        # ускорения не доходили до карточки)
        segments=segments_from_schema(p.segments),
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
    plan_notes: list[str] = []

    def _finalize(proposal: WorkoutProposal) -> Prescription:
        # Safety дня — по прогнозному счётчику правила 17 на его дату (см. counts): темповая в
        # четверг не режется сегодняшним счётчиком, раньше открытия — режется детерминированно
        return finalize(proposal, project_state(state, counts, proposal.for_days_ahead or 0),
                        db=db, persist=False, source="llm", now=now_local)

    # (1) первый проход — нужны predicted (км по истории) для потолков; (2) потолок длительной;
    # (3) потолок объёма недели; (4) запись. Prescription по-прежнему рождается только в clamp —
    # урезанные предложения проходят finalize повторно. (Two-pass finalize with code-held caps.)
    prescriptions: list[Prescription] = [_finalize(it) for it in items]
    for i, (proposal, p) in enumerate(zip(items, prescriptions)):
        capped, note = cap_long_run(proposal, p, targets)
        if capped is not None:
            logger.info("Long run capped user=%s: %s→%s min (est %.1f km, cap %.1f km)",
                        user_id, proposal.duration_min, capped.duration_min,
                        (p.predicted or {}).get("distance_km") or 0.0,
                        targets.get("long_run_km_max") or 0.0)
            items[i] = capped
            prescriptions[i] = _finalize(capped)
            plan_notes.append(note)
        elif note:
            logger.warning("Long run above cap but structured user=%s: %s", user_id, note)
            plan_notes.append(note)
    long_run_capped = bool(plan_notes)
    scaled, note = cap_week_volume(items, prescriptions, targets)
    if scaled is not None:
        before = sum((p.predicted or {}).get("distance_km") or 0.0 for p in prescriptions)
        for i, (old, new) in enumerate(zip(items, scaled)):
            if new is not old:
                items[i] = new
                prescriptions[i] = _finalize(new)
        after = sum((p.predicted or {}).get("distance_km") or 0.0 for p in prescriptions)
        logger.info("Week volume capped user=%s: %.1f→%.1f km (target %.1f)",
                    user_id, before, after, targets.get("target_km") or 0.0)
        plan_notes.append(note)
    if dropped_days:
        plan_notes.append(f"⚠️ Беговых дней урезано до {run_days_cap}: "
                          "частота растёт не быстрее +1 в неделю.")
    for proposal, p in zip(items, prescriptions):
        status = "adjusted" if (proposal.for_days_ahead == 0 and had_today_row) else "planned"
        save_prescription(p, state, db=db, status=status)
    # Отменённые подопечным дни — rest с маркером, ПОСЛЕ гашения прежнего плана
    cancel_tail = _cancel_tail(cancelled, user_id, state, db=db, now_local=now_local)

    # Карточка — одна картина недели: прошедшие дни фактом (week_view) + новый остаток
    week_start = date.fromisoformat(targets["week_start"])
    rows = _active_rows(user_id, db=db, week_start=week_start)
    past = [rehydrate(r) for d, r in sorted(rows.items()) if d < today]
    text = ("\n\n".join(t for t in (turn.message, avail_tail, cancel_tail) if t) + "\n\n"
            + render_week_plan(past + prescriptions, targets, max_hr=user_max_hr(user),
                               lthr=latest_lthr(user_id, db=db), today=today,
                               facts=week_facts(rows, db=db, today=today),
                               notes=plan_notes))
    CoachRepository.save_message(user_id, "user", PLAN_PROMPT, db=db, kind="plan")
    CoachRepository.save_message(
        user_id, "assistant", text, db=db, kind="plan",
        meta={"days": len(prescriptions),
              "clamped": sum(1 for p in prescriptions if p.clamped),
              "superseded": superseded, "dropped_days": dropped_days,
              "cancelled_days": cancelled,
              "long_run_capped": long_run_capped,
              "week_volume_capped": scaled is not None,
              "prose": turn.message,   # #258: история берёт прозу без карточки
              "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0)},
        tokens_in=usage.get("input_tokens"), tokens_out=usage.get("output_tokens"),
        cost_usd=estimate_cost_usd(usage))
    planning.advance_mesocycle(user_id, db=db, targets=targets)
    logger.info("Weekly plan saved: user=%s days=%s week=%s superseded=%s dropped=%s",
                user_id, len(prescriptions), targets["week_start"], superseded,
                dropped_days)
    return text


def _cancel_tail(cancelled: list[int], user_id: int, state, *, db: Session,
                 now_local: datetime) -> str:
    """Rest-строки на отменённые дни + строки «Изменил план на …: 🛌 Отдых» ('' — нечего)."""
    if not cancelled:
        return ""
    return planning.cancel_days(cancelled, user_id, state, db=db, now=now_local)


def _profile(user: User) -> dict:
    from src.coach.turn_context import profile
    return profile(user)


def _history(user_id: int, *, db: Session) -> list[dict]:
    from src.coach.turn_context import history
    return history(user_id, db=db)
