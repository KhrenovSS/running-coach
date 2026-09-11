# LLM-ход коуча: чат, утро, инициатива (Coach chat flow) — вынос из orchestrator.py (#329, 11.09.2026)
#
# Один LLM-ход `_llm_chat_turn`: state+verdict в контекст → агент → детерминированные
# пост-обработки (отмена/возврат дней, болезнь, concerns, гвард «день отменён») → clamp → рендер.
# `handle_chat` — свободный чат и утро с детерминированным fallback (kind="morning" → вердикт
# с назначением, инцидент 01.09.2026). Разбор тренировки и недельный отчёт — в orchestrator.py.
# (One LLM turn with deterministic post-processing; chat/morning with fallback.)

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.orm import Session

from src.coach import concerns, illness, planning
from src.coach.contracts import Prescription, WorkoutProposal
from src.coach.numeric_check import check_prose, prose_numbers
from src.coach.llm.agent import run_turn
from src.coach.llm.client import CoachLLM, get_llm
from src.coach.llm.config import COACH_EFFORT_CHAT, COACH_MAX_TURNS_PER_DAY
from src.coach.llm.prompts import build_messages, build_system_blocks, build_today_block
from src.coach.llm.schemas import LogSuggestion, ReviewAssessment
from src.coach.prescriber import finalize, save_prescription, user_max_hr
from src.coach.render import (
    render_prescription,
    render_prescription_short,
    render_state_card,
)
from src.coach.rules.p1_safety import evaluate_safety
from src.coach.state import assess_state
from src.coach.tools.serialize import jsonable
from src.coach.turn_context import build_extras as _build_extras
from src.coach.turn_context import history as _history
from src.coach.turn_context import profile as _profile
from src.coach.turn_context import unchanged_today as _unchanged_today
from src.coach.render_week import plan_change_line
from src.coach.week_view import render_stored_week_plan
from src.exceptions import CoachError, LLMTransientError, LLMUnavailableError
from src.models import User, UserModel
from src.services.repositories import latest_lthr
from src.services.repositories_coach import CoachRepository
from src.utils.logger import get_logger
from src.utils.timeutils import WEEKDAYS_RU_SHORT, fmt_local, local_dt, user_now

logger = get_logger("coach.orchestrator")

INITIATIVE_LEVELS = ("off", "low", "normal", "high")
INITIATIVE_DEFAULT = "high"  # решение владельца 23.08.2026: старт на максимуме


@dataclass
class ChatReply:
    """Ответ коуча хендлеру: текст + опциональная кнопка записи боли (chat reply)."""
    text: str
    log_suggestion: LogSuggestion | None = None
    source: str = "fallback"          # llm | fallback
    retriable: bool = False           # fallback из-за транзиентного сбоя моста → есть смысл повторить
    assessment: ReviewAssessment | None = None   # D3: только kind=review
    assistant_message_id: int | None = None      # D3: link в workout_insights


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
    if turn.illness is not None and kind in ("chat", "morning"):
        # #322: болезнь/выздоровление — паузу ведёт код (гайд 50); safety закрывает тренировки
        text += "\n\n" + illness.record_illness(turn.illness, user_id, db=db, now=user_now(user))
    if turn.concern is not None and kind in ("chat", "morning"):
        # 10.09.2026: «подвернул ногу» / «уже не беспокоит» — контроль и снятие ведёт код
        text += "\n\n" + concerns.record_concern(turn.concern, user_id, db=db, now=user_now(user))
    if proposal is not None and proposal.workout_type != "rest" and kind in ("chat", "morning"):
        # Детерминированный гвард (инцидент 04.09.2026): на день, который подопечный
        # отменил сам, тренировку не назначаем — предложение LLM отбрасывается.
        # #322: то же для дней болезни и паузы после неё.
        when = user_now(user).date() + timedelta(days=proposal.for_days_ahead or 0)
        blocked = (planning.blocked_by_unavailable(user_id, db=db, when=when)
                   or illness.blocked_reason(user_id, db=db, when=when, today=user_now(user).date()))
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
