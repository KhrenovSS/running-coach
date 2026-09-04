# Оркестратор коуча (Coach orchestrator) — DEV_PLAN §7/§9
#
# C4: детерминированные сценарии (без LLM). LLM-путь подключается в C6/C7 через
# DI-параметр `llm` — сигнатуры не изменятся. Все функции получают db от вызывающего.
# (C4: deterministic scenarios; the LLM path plugs in via the `llm` DI parameter.)

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from src.coach import planning
from src.coach.contracts import Prescription, WorkoutProposal
from src.coach.numeric_check import check_prose, prose_numbers
from src.coach.llm.agent import run_turn
from src.coach.llm.client import CoachLLM, get_llm
from src.coach.llm.config import (
    COACH_EFFORT_CHAT,
    COACH_EFFORT_PLAN,
    COACH_ENRICH_RECENT_LIMIT,
    COACH_ENRICH_WEEKS,
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
    render_gps_warning,
    render_prescription,
    render_prescription_short,
    render_review,
    render_state_card,
)
from src.coach.rules.p1_safety import evaluate_safety
from src.coach.skills import workout
from src.coach.state import assess_state
from src.coach.tools.serialize import jsonable
from src.coach.turn_context import build_extras as _build_extras
from src.coach.turn_context import history as _history
from src.coach.turn_context import profile as _profile
from src.coach.turn_context import unchanged_today as _unchanged_today
from src.coach.render_week import plan_change_line
from src.coach.render_week_report import render_week_report
from src.coach.week_report import build_week_report
from src.coach.week_view import render_stored_week_plan
from src.exceptions import CoachError, LLMTransientError, LLMUnavailableError
from src.models import TrainingFeedback, User, UserModel, WellnessReport
from src.services.repositories import latest_lthr
from src.services.repositories_coach import CoachRepository
from src.utils.logger import get_logger
from src.utils.timeutils import WEEKDAYS_RU_SHORT, fmt_local, local_dt, user_now
from dataclasses import dataclass, field

logger = get_logger("coach.orchestrator")


@dataclass
class ChatReply:
    """Ответ коуча хендлеру: текст + опциональная кнопка записи боли (chat reply)."""
    text: str
    log_suggestion: LogSuggestion | None = None
    source: str = "fallback"          # llm | fallback
    retriable: bool = False           # fallback из-за транзиентного сбоя моста → есть смысл повторить
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
            + render_prescription(prescription, max_hr=user_max_hr(user), user=user,
                                  lthr=latest_lthr(user_id, db=db)))


def _llm_chat_turn(user_id: int, message: str, *, db: Session,
                   llm: CoachLLM, kind: str, extras: dict | None = None,
                   allow_proposal: bool = True,
                   effort: str = COACH_EFFORT_CHAT,
                   suffix: str | None = None,
                   extra_card: str | None = None) -> ChatReply:
    """LLM-ход: state+verdict в контекст → агент → clamp → рендер (one LLM turn).

    extra_card — готовая детерминированная карточка хода (недельный отчёт, C8.1):
    ставится после прозы, перед followup-вопросом. (Pre-rendered deterministic card.)
    """
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
    lthr = latest_lthr(user_id, db=db)  # зоны/потолки от порога (F4/M3.1)
    week_card: str | None = None
    if kind == "chat" and (turn.show_week_plan or turn.weekly_plan is not None):
        # Вопрос «какой план на неделю»: план в чате не персистится (решение
        # 29.08) — показываем СОХРАНЁННЫЙ (инцидент 02.09: молчаливый дроп → «общие слова»)
        logger.info("Week plan card requested in chat user=%s (weekly_plan=%s)",
                    user_id, turn.weekly_plan is not None)
        week_card = render_stored_week_plan(user_id, db=db)
    elif turn.weekly_plan is not None:
        # Недельный план строится только отдельным ходом kind='plan' (weekly_plan.py)
        logger.warning("Unexpected weekly_plan for kind=%s user=%s — dropped",
                       kind, user_id)
    proposal = None
    if turn.proposal is not None:
        from src.coach.segments import segments_from_schema
        proposal = WorkoutProposal(
            workout_type=turn.proposal.workout_type,
            target_zone=turn.proposal.target_zone,
            duration_min=turn.proposal.duration_min,
            distance_km=turn.proposal.distance_km,
            target_pace_min_km=turn.proposal.target_pace_min_km,
            structure=turn.proposal.structure,
            segments=segments_from_schema(turn.proposal.segments),
            rationale=list(turn.proposal.rationale),
            for_days_ahead=turn.proposal.for_days_ahead,
        )
    card: Prescription | None = None   # карточка хода — для numeric-checker (#247)
    if turn.available_again_days_ahead and kind in ("chat", "morning"):
        # Обратный путь отмены: «в субботу всё-таки смогу» → снимаем отдых-отмену
        reopened = planning.reopen_days(turn.available_again_days_ahead, user_id,
                                        db=db, now=user_now(user))
        if reopened:
            text += "\n\n" + reopened
    if turn.available_weekdays is not None and kind == "chat":
        # #294: постоянное окно доступности — персистим, /plan его учитывает
        saved = planning.set_availability(user_id, db=db, weekdays=turn.available_weekdays)
        if saved["weekdays"]:
            names = ", ".join(WEEKDAYS_RU_SHORT[d] for d in saved["weekdays"])
            text += f"\n\nЗапомнил дни для бега: {names}. План недели будет ставить тренировки только в них."
        else:
            text += "\n\nЗапомнил: бегать можно в любой день недели."
    if proposal is not None and proposal.workout_type != "rest" and kind in ("chat", "morning"):
        # Детерминированный гвард (инцидент 04.09.2026): на день, который подопечный
        # отменил сам, тренировку не назначаем — предложение LLM отбрасывается.
        when = user_now(user).date() + timedelta(days=proposal.for_days_ahead or 0)
        blocked = planning.blocked_by_unavailable(user_id, db=db, when=when)
        if blocked:
            logger.info("Proposal blocked: athlete unavailable on %s user=%s", when, user_id)
            text += "\n\n" + blocked
            proposal = None
    morning_result = (planning.confirm_or_adjust_morning(
        proposal, user_id, state, db=db, now=user_now(user))
        if kind == "morning" else None)
    if morning_result is not None:
        # План дня есть: подтверждение (UPDATE status) или осознанная замена
        # (решение владельца 29.08.2026). (Confirm or consciously adjust the plan.)
        card, mode, plan_row = morning_result
        logger.info("Morning plan %s for user=%s", mode, user_id)
        if mode == "adjusted":
            # Строка «Изменил план на … (было: …)» над карточкой (решение владельца 03.09.2026)
            text += "\n\n" + plan_change_line(card.when, card, plan_row)
        text += "\n\n" + render_prescription(card, max_hr=max_hr, user=user, lthr=lthr)
    elif proposal is not None and not allow_proposal:
        # Разбор/отчёт — про прошлое: назначение даёт утренний вердикт/чат (C8).
        # (Reviews look backward: proposals are dropped, not clamped/persisted.)
        logger.info("Proposal dropped for kind=%s user=%s", kind, user_id)
    elif proposal is not None:
        card = finalize(proposal, state, db=db, persist=False, source="llm",
                        now=user_now(user))
        if kind == "chat" and _unchanged_today(card, user_id, db=db):
            # Дедуп (решение владельца 26.08.2026): назначение не изменилось —
            # одна строка-напоминание, без новой строки в recommendations.
            # (Unchanged plan → one reminder line, no duplicate recommendation row.)
            text += "\n\n" + render_prescription_short(card, max_hr=max_hr, lthr=lthr)
        else:
            # Уже данное назначение на этот день → строка «Изменил план на …» над карточкой
            old = planning.latest_rows_for_dates(user_id, db=db, dates=[card.when]).get(card.when)
            save_prescription(card, state, db=db)
            if old is not None:
                text += "\n\n" + plan_change_line(card.when, card, old)
            text += "\n\n" + render_prescription(card, max_hr=max_hr, user=user, lthr=lthr)
    if turn.unavailable_days_ahead and kind in ("chat", "morning"):
        # Подопечный не сможет бегать в эти дни → детерминированно гасим назначения и ставим
        # отдых, чтобы planned_workouts и /week не «оживляли» отменённый день (инцидент
        # 03.09.2026: «воскресную отменяем» осталось прозой, коуч дальше ждал воскресную).
        # (Cancel planned days deterministically: supersede rows, write rest rows.)
        text += "\n\n" + planning.cancel_days(turn.unavailable_days_ahead, user_id, state,
                                              db=db, now=user_now(user))
    if extra_card is not None:
        week_card = extra_card
    if week_card is not None:
        text += "\n\n" + week_card
    if turn.followup_question:
        text += "\n\n" + turn.followup_question
    if suffix:
        # Детерминированный хвост хода (напр. GPS-предупреждение) — до персиста,
        # чтобы история и отправленный текст совпадали (append before persist)
        text += suffix

    assessment = turn.assessment
    if assessment is not None and kind != "review":
        # Оценка уместна только в разборе — в чате/утре игнорируем (D3)
        logger.warning("Unexpected assessment for kind=%s user=%s — dropped", kind, user_id)
        assessment = None

    from src.coach.llm.anthropic_client import estimate_cost_usd
    meta = {"stop_reason": "end_turn", "tool_calls": usage.get("tool_calls", []),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
            "prose": turn.message}   # #258: история берёт прозу без карточки
    if card is not None:
        # #247 v1: детект расхождений проза↔карточка — лог+метка, текст не режем
        mismatches = check_prose(turn.message, card, max_hr, lthr=lthr)
        if mismatches:
            logger.warning("Numeric mismatch for kind=%s user=%s: %s",
                           kind, user_id, "; ".join(mismatches))
            meta["numeric_mismatch"] = mismatches
    elif kind == "weekly":
        # Числа недели даёт карточка — проза их называть не должна (C8.1; #247: лог+метка)
        found = prose_numbers(turn.message)
        if found:
            logger.warning("Weekly prose carries numbers user=%s: %s", user_id, found)
            meta["numeric_mismatch"] = found
    CoachRepository.save_message(user_id, "user", message, db=db, kind=kind)
    assistant_msg = CoachRepository.save_message(
        user_id, "assistant", text, db=db, kind=kind, meta=meta,
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
        transient = isinstance(e, LLMTransientError)
        if kind == "morning":
            # Утро: детерминированный вердикт со НАЗНАЧЕНИЕМ через safety (как /verdict),
            # а не generic-карточка состояния — иначе теряется план дня (инцидент 01.09).
            text = morning_verdict(user_id, db=db)
        else:
            state = assess_state(user_id, db=db)
            text = ("Тренер сейчас отвечает в базовом режиме.\n"
                    "Вот твоё текущее состояние:\n\n" + render_state_card(state))
        CoachRepository.save_message(user_id, "user", message, db=db, kind=kind)
        CoachRepository.save_message(user_id, "assistant", text, db=db, kind=kind,
                                     meta={"fallback": True, "transient": transient})
        return ChatReply(text=text, source="fallback", retriable=transient)


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
