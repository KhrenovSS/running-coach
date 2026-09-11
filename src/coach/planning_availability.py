# Доступность подопечного и отмена дней (Athlete availability & day cancellation) — вынос из
# coach/planning.py (#329, 11.09.2026). Решения 03–04.09.2026 (#294): окно доступности —
# params_json.week_plan.availability; отменённые дни — rest-строки с маркером UNAVAILABLE_RATIONALE,
# переживают /plan; детерминированный гвард blocked_by_unavailable — чат/утро на такой день
# тренировку не назначают. (Weekday availability, cancel/reopen days, deterministic guard.)

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from src.coach.config import UNAVAILABLE_RATIONALE
from src.coach.contracts import AthleteState, WorkoutProposal
from src.coach.planning_rows import latest_rows_for_dates, supersede_rows_for_dates
from src.coach.prescriber import finalize, save_prescription
from src.coach.render_week import plan_change_line
from src.coach.turn_context import is_athlete_unavailable
from src.config.constants import RECOMMENDATION_STATUS_SUPERSEDED
from src.models import Recommendation, UserModel
from src.utils.logger import get_logger
from src.utils.timeutils import WEEKDAYS_RU_SHORT

logger = get_logger("coach.planning")


def _week_plan_meta(user_id: int, *, db: Session) -> dict:
    um = db.query(UserModel).filter(UserModel.user_id == user_id).first()
    if um and um.params_json:
        return um.params_json.get("week_plan") or {}
    return {}


def availability(user_id: int, *, db: Session) -> dict:
    """Окно доступности подопечного (#294): {"weekdays": [0..6] | None} из params_json.week_plan.
    None/пусто — бегать можно в любой день. (Persisted weekday availability.)"""
    meta = _week_plan_meta(user_id, db=db)
    return {"weekdays": (meta.get("availability") or {}).get("weekdays")}


def set_availability(user_id: int, *, db: Session, weekdays: list[int] | None) -> dict:
    """Записать дни недели, когда подопечный может бегать (merge-паттерн advance_mesocycle).
    Пустой список/None — снять ограничение. Возврат — сохранённое окно."""
    um = db.query(UserModel).filter(UserModel.user_id == user_id).first()
    if um is None:
        um = UserModel(user_id=user_id, params_json={})
        db.add(um)
    params = dict(um.params_json or {})
    meta = dict(params.get("week_plan") or {})
    days = sorted({d for d in (weekdays or []) if 0 <= d <= 6})
    meta["availability"] = {"weekdays": days or None,
                            "updated_at": datetime.now(timezone.utc).isoformat()}
    params["week_plan"] = meta
    um.params_json = params
    db.commit()
    logger.info("Availability set for user=%s: weekdays=%s", user_id, days or "any")
    return {"weekdays": days or None}


def unavailable_dates(user_id: int, *, db: Session, week_start: date) -> list[date]:
    """Даты недели week_start, отменённые подопечным (rest с маркером) — план их не трогает."""
    rows = db.query(Recommendation).filter(
        Recommendation.user_id == user_id,
        Recommendation.for_date >= week_start,
        Recommendation.for_date <= week_start + timedelta(days=6),
        Recommendation.status != RECOMMENDATION_STATUS_SUPERSEDED,
    ).order_by(Recommendation.id.asc()).all()
    latest = {r.for_date: r for r in rows}
    return sorted(d for d, r in latest.items() if is_athlete_unavailable(r))


def cancel_days(days_ahead: list[int], user_id: int, state: AthleteState, *,
                db: Session, now: datetime) -> str:
    """Снять назначения на дни, когда подопечный не сможет бегать (cancel planned days).

    На каждую дату: прежние строки без факта → superseded, новая строка rest
    (status 'adjusted' — осознанная замена плана, как в утреннем вердикте).
    Возврат — строки «Изменил план на Вс 06.09: 🛌 Отдых (было: …)» по одной на дату,
    детерминированные, не проза LLM. (Deterministic plan-change lines.)
    """
    today = now.date()
    days = sorted(set(days_ahead))
    dates = [today + timedelta(days=d) for d in days]
    old = latest_rows_for_dates(user_id, db=db, dates=dates)
    n = supersede_rows_for_dates(user_id, db=db, dates=dates)
    lines: list[str] = []
    for d, when in zip(days, dates):
        # Маркер «не сможет бегать» — в proposal_json.rationale; по нему чат/утро на этот
        # день назначение не дают (is_athlete_unavailable, blocked_by_unavailable).
        rest = finalize(WorkoutProposal(workout_type="rest", target_zone=1, for_days_ahead=d,
                                        rationale=[UNAVAILABLE_RATIONALE]),
                        state, db=db, persist=False, source="llm", now=now)
        save_prescription(rest, state, db=db, status="adjusted")
        lines.append(plan_change_line(when, rest, old.get(when)))
    logger.info("Cancelled %d planned rows for user=%s, rest on %s", n, user_id, dates)
    return "\n".join(lines)


def blocked_by_unavailable(user_id: int, *, db: Session, when: date) -> str | None:
    """День отменён подопечным («не смогу бегать») → строка-отказ для текста, иначе None.

    Гвард детерминированный: LLM-предложение тренировки на такой день отбрасывается
    (инцидент 04.09.2026: чат назначил пробежку на отменённую пятницу).
    (Athlete cancelled the day → refusal line; the proposal is dropped by the caller.)
    """
    row = latest_rows_for_dates(user_id, db=db, dates=[when]).get(when)
    if row is None or not is_athlete_unavailable(row):
        return None
    label = f"{WEEKDAYS_RU_SHORT[when.weekday()]} {when:%d.%m}"
    return (f"На {label} ты говорил, что бегать не сможешь — назначение не ставлю. "
            f"Если планы изменились, напиши «в этот день смогу побегать» или /plan.")


def reopen_days(days_ahead: list[int], user_id: int, *, db: Session, now: datetime) -> str:
    """Подопечный снова может бегать в эти дни → гасим строки отдыха с маркером
    (обратный путь к cancel_days). Возврат — строка для текста ('' — гасить было нечего)."""
    today = now.date()
    dates = [today + timedelta(days=d) for d in sorted(set(days_ahead))]
    rows = latest_rows_for_dates(user_id, db=db, dates=dates)
    reopened = [d for d in dates if d in rows and is_athlete_unavailable(rows[d])]
    if not reopened:
        return ""
    for d in reopened:
        rows[d].status = RECOMMENDATION_STATUS_SUPERSEDED
    db.commit()
    logger.info("Reopened %d cancelled days for user=%s: %s", len(reopened), user_id, reopened)
    labels = ", ".join(f"{WEEKDAYS_RU_SHORT[d.weekday()]} {d:%d.%m}" for d in reopened)
    return f"Снял отдых: {labels} — день снова свободен для назначения."
