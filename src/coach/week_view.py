# Карточка СОХРАНЁННОГО плана недели (stored week plan view) — инцидент 02.09.2026
#
# Read-only: строки recommendations текущей локальной недели (пн–вс), последняя на
# дату побеждает (как planned_workouts в turn_context). Ничего не пересчитываем и не
# re-clamp'им — показываем план записи; числа уже прошли safety при сохранении.
# Точки входа: команда /week, флаг show_week_plan в ходе LLM, weekly_plan в чате.
# (Read-only view of the persisted weekly plan; no LLM, no writes, no re-clamp.)

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from src.coach.contracts import Prescription
from src.coach.planning import _MESO_LEN, _monday_of
from src.coach.prescriber import user_max_hr
from src.coach.render import render_week_plan
from src.coach.safety import rehydrate
from src.config.constants import RECOMMENDATION_STATUS_SUPERSEDED
from src.models import Recommendation, User, UserModel
from src.services.repositories import latest_lthr
from src.utils.timeutils import user_now

NO_PLAN_TEXT = "На эту неделю плана нет — составить: /plan"


def stored_week_prescriptions(user_id: int, *, db: Session,
                              today: date) -> list[Prescription]:
    """Назначения недели пн–вс из recommendations (последняя строка на дату).

    (Latest recommendation row per date of the current local week.)
    """
    week_start = _monday_of(today)
    rows = db.query(Recommendation).filter(
        Recommendation.user_id == user_id,
        Recommendation.for_date >= week_start,
        Recommendation.for_date <= week_start + timedelta(days=6),
        Recommendation.status != RECOMMENDATION_STATUS_SUPERSEDED,
    ).order_by(Recommendation.id.asc()).all()
    latest_by_date = {r.for_date: r for r in rows if r.for_date is not None}
    # Конструктор Prescription — только в safety.py (гвард test_no_prescription_bypass)
    return [rehydrate(r) for _, r in sorted(latest_by_date.items())]


def week_targets_stored(user_id: int, *, db: Session, week_start: date) -> dict:
    """Мета недели из params_json.week_plan (пишет planning.advance_mesocycle);
    неделя другая → минимальный dict без мезоцикла (stored week meta or minimal).
    """
    um = db.query(UserModel).filter(UserModel.user_id == user_id).first()
    meta = ((um.params_json or {}).get("week_plan") or {}) if um else {}
    targets: dict = {"week_start": week_start.isoformat()}
    if meta.get("week_start") == week_start.isoformat():
        targets.update(meta)
        # advance_mesocycle длину цикла не пишет — константа планирования
        targets.setdefault("mesocycle_length", _MESO_LEN)
    return targets


def render_stored_week_plan(user_id: int, *, db: Session) -> str:
    """Текст карточки сохранённого плана текущей недели или подсказка /plan."""
    user = db.query(User).filter(User.id == user_id).first()
    today = user_now(user).date()
    prescriptions = stored_week_prescriptions(user_id, db=db, today=today)
    if not prescriptions:
        return NO_PLAN_TEXT
    targets = week_targets_stored(user_id, db=db, week_start=_monday_of(today))
    return render_week_plan(prescriptions, targets, max_hr=user_max_hr(user),
                            lthr=latest_lthr(user_id, db=db), today=today)
