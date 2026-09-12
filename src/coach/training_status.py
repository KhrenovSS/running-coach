# Статус подопечного из данных (Athlete training status) — решение владельца 12.09.2026.
#
# Раньше персона промпта утверждала «возвращающийся к форме после долгого перерыва» статично —
# независимо от того, что показывает история. Теперь фазу считает код: returning (пауза/возврат),
# stabilizing (регулярность закрепляется), stable (полноценный процесс). Фаза управляет дайджестом
# «возвратных» правил гайдов (knowledge/loader.key_rules_digest), лестницей качественных дней
# (quality_ladder.py) и блоком athlete_status в today-контексте LLM (turn_context.build_extras).
# Числовые ограничения объёма (detraining_return, правило 14 safety) остаются там, где были.
# (Deterministic continuity status; replaces the static "returning" persona line.)

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.orm import Session

from src.coach import concerns
from src.coach.config import (
    DETRAINING_MIN_DAYS_OFF,
    DETRAINING_RETURN_MIN_DAYS_OFF,
    STATUS_LOOKBACK_WEEKS,
    STATUS_MIN_RUNS_PER_WEEK,
    STATUS_STABLE_WEEKS,
)
from src.coach.illness import block_days, illness_state
from src.coach.planning_window import local_week_volumes
from src.models import TrainingSession, User
from src.utils.timeutils import session_local_dt

PHASE_RETURNING = "returning"
PHASE_STABILIZING = "stabilizing"
PHASE_STABLE = "stable"

PHASE_RU = {PHASE_RETURNING: "возврат после паузы — входим мягко",
            PHASE_STABILIZING: "регулярность ещё закрепляется",
            PHASE_STABLE: "стабильный тренировочный процесс"}


@dataclass(frozen=True)
class Pause:
    days: int            # длина паузы (дней без бега между двумя тренировками)
    ended_days_ago: int  # сколько дней назад пауза закончилась (первая тренировка после неё)


# ---------- чистые функции (pure, tested without DB) ----------

def find_pauses(run_dates: list[date], today: date,
                min_days: int = DETRAINING_MIN_DAYS_OFF) -> list[Pause]:
    """Паузы ≥ min_days между соседними датами тренировок, старые → новые (gaps between runs)."""
    days = sorted(set(run_dates))
    out: list[Pause] = []
    for prev, nxt in zip(days, days[1:]):
        gap = (nxt - prev).days
        if gap >= min_days:
            out.append(Pause(days=gap, ended_days_ago=(today - nxt).days))
    return out


def continuity_weeks(weeks: list[dict], run_dates: list[date],
                     min_runs: int = STATUS_MIN_RUNS_PER_WEEK,
                     pause_days: int = DETRAINING_MIN_DAYS_OFF) -> int:
    """Подряд идущие полные недели (назад от последней) с ≥ min_runs пробежками, серию рвёт
    пауза ≥ pause_days, начавшаяся в неделе и закончившаяся уже в следующей (две соседние недели
    могут иметь по 2+ пробежки и всё же прятать паузу «вт → пн»). Пауза целиком внутри недели
    серию не рвёт — неделя засчитана по числу пробежек. (Consecutive qualifying full weeks.)"""
    days = sorted(set(run_dates))
    gaps = [(p, n) for p, n in zip(days, days[1:]) if (n - p).days >= pause_days]
    count = 0
    for w in reversed(weeks):
        if w.get("session_count", 0) < min_runs:
            break
        ws = w["week_start"]
        if any(ws <= p < ws + timedelta(days=7) <= n for p, n in gaps):
            break
        count += 1
    return count


def classify(*, continuity: int, days_off: int | None, last_pause: Pause | None,
             stable_weeks: int = STATUS_STABLE_WEEKS) -> str:
    """Фаза по данным (pure).

    returning — сейчас пауза ≥ DETRAINING_MIN_DAYS_OFF (правило 14 safety уже действует), либо
    последняя пауза ≥ DETRAINING_RETURN_MIN_DAYS_OFF ещё «не отработана»: прошло меньше дней, чем
    длилась пауза (восстановление ≈ длине паузы, гайд 61 — как return_progress в week_structure).
    stabilizing — серия недель короче stable_weeks; stable — иначе.
    """
    if days_off is None or days_off >= DETRAINING_MIN_DAYS_OFF:
        return PHASE_RETURNING
    if (last_pause is not None and last_pause.days >= DETRAINING_RETURN_MIN_DAYS_OFF
            and last_pause.ended_days_ago < last_pause.days):
        return PHASE_RETURNING
    if continuity < stable_weeks:
        return PHASE_STABILIZING
    return PHASE_STABLE


# ---------- сборка из БД (DB-backed, read-only) ----------

def _run_dates(user_id: int, *, db: Session, since: date) -> list[date]:
    user = db.query(User).filter(User.id == user_id).first()
    rows = db.query(TrainingSession).filter(TrainingSession.user_id == user_id).all()
    out = []
    for s in rows:
        if s.begin_ts is None:
            continue
        d = session_local_dt(s.begin_ts, s, user).date()
        if d >= since:
            out.append(d)
    return sorted(out)


def _first_run_date(user_id: int, *, db: Session) -> date | None:
    row = db.query(TrainingSession).filter(TrainingSession.user_id == user_id).order_by(
        TrainingSession.begin_ts.asc()).first()
    if row is None or row.begin_ts is None:
        return None
    user = db.query(User).filter(User.id == user_id).first()
    return session_local_dt(row.begin_ts, row, user).date()


def compute_status(user_id: int, *, db: Session, today: date) -> dict:
    """Статус подопечного на today (read-only; ничего не пишет в params_json)."""
    weeks = local_week_volumes(user_id, db=db, today=today, weeks=STATUS_LOOKBACK_WEEKS)
    since = weeks[0]["week_start"] if weeks else today
    run_dates = _run_dates(user_id, db=db, since=since)
    first = _first_run_date(user_id, db=db)
    days_off = (today - run_dates[-1]).days if run_dates else None
    pauses = find_pauses(run_dates, today)
    last_pause = pauses[-1] if pauses else None
    continuity = continuity_weeks(weeks, run_dates)
    phase = classify(continuity=continuity, days_off=days_off, last_pause=last_pause)

    restrictions: list[str] = []
    ill = illness_state(user_id, db=db)
    if block_days(ill, today) is not None:
        restrictions.append(f"illness: {ill.get('status')} ({ill.get('kind')})")
    active = concerns.active_concerns(user_id, db=db, today=today)
    active_injury = any(c.get("kind") == "injury" for c in active)
    for c in active:
        label = c.get("label") or concerns.KIND_RU.get(c.get("kind"), "проблема")
        loc = concerns.LOCATION_RU.get(c.get("location"), c.get("location"))
        restrictions.append(f"{c.get('kind')}: {label}" + (f" ({loc})" if loc else ""))
    if days_off is not None and days_off >= DETRAINING_RETURN_MIN_DAYS_OFF:
        restrictions.append("detraining_return")

    # Якорь зон (M3.2, 12.09.2026): полевой ПАНО → Coros → %max_hr — LLM видит, чему верить
    from src.services.repositories import field_lthr, latest_lthr
    anchor = ("lthr_field" if field_lthr(user_id, db=db) is not None
              else "coros" if latest_lthr(user_id, db=db) is not None else "max_hr")

    return {
        "phase": phase,
        "zone_anchor": anchor,
        "training_age_days": (today - first).days if first else None,
        "continuity_weeks": continuity,
        "weeks_with_runs_last_4": [w["session_count"] for w in weeks[-4:]],
        "last_pause": ({"days": last_pause.days, "ended_days_ago": last_pause.ended_days_ago}
                       if last_pause else None),
        "days_off": days_off,
        "active_injury": active_injury,
        "restrictions": restrictions,
    }


def summary_ru(status: dict) -> str:
    """Одна строка для LLM: стаж, серия недель, последняя пауза, ограничения (RU summary)."""
    parts = []
    age = status.get("training_age_days")
    if age is not None:
        parts.append(f"стаж в системе {age // 30} мес" if age >= 60 else f"стаж в системе {age} дн")
    cont = status.get("continuity_weeks", 0)
    runs = (status.get("weeks_with_runs_last_4") or [])[-cont:] if cont else []
    if runs:
        parts.append(f"{cont} нед подряд по {min(runs)}–{max(runs)} пробежек"
                     if min(runs) != max(runs) else f"{cont} нед подряд по {runs[0]} пробежки")
    else:
        parts.append("серии регулярных недель пока нет")
    lp = status.get("last_pause")
    if lp:
        parts.append(f"последняя пауза {lp['days']} дн, закончилась {lp['ended_days_ago']} дн назад")
    else:
        parts.append("пауз ≥ 6 дн в окне нет")
    r = status.get("restrictions") or []
    parts.append("ограничения: " + "; ".join(r) if r else "ограничений по здоровью нет")
    return f"{PHASE_RU.get(status.get('phase'), status.get('phase'))}; " + ", ".join(parts)


def context_block(status: dict) -> dict:
    """Блок today-контекста для LLM — только относительные числа, без ISO-дат
    (в system-блоки не кладём: test_prompt_stability, кэш). (LLM context block.)"""
    return {
        "phase": status["phase"],
        "phase_ru": PHASE_RU.get(status["phase"], status["phase"]),
        "zone_anchor": status.get("zone_anchor"),
        "training_age_days": status["training_age_days"],
        "continuity_weeks": status["continuity_weeks"],
        "weeks_with_runs_last_4": status["weeks_with_runs_last_4"],
        "last_pause": status["last_pause"],
        "days_off": status["days_off"],
        "restrictions": status["restrictions"],
        "summary": summary_ru(status),
    }
