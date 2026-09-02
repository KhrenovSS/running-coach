# Окно планирования недели и «уже сделано» (Planning window & week-to-date) — #293, 02.09.2026
#
# Решение владельца: /plan среди недели планирует ОСТАТОК текущей недели — с сегодня
# (если пробежки ещё не было) по воскресенье; вычитая уже выполненный объём, беговые и
# качественные дни. Вс вечером — вся следующая неделя (как раньше). Вынесено из
# planning.py по лимиту ~400 строк/файл.
# (Mid-week /plan = rest of the current week minus what is already done.)

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy.orm import Session

from src.analysis.week_structure import is_quality_session
from src.models import TrainingSession, User
from src.services.repositories import latest_lthr
from src.utils.timeutils import session_local_dt


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def plan_window(today: date, trained_today: bool) -> tuple[date, int, int]:
    """(week_start, first_offset, last_offset) — какие for_days_ahead планировать.

    Воскресенье → следующая неделя целиком (1..7). Иначе — остаток текущей:
    с сегодня (0), если сегодня ещё не бегали, иначе с завтра (1), до воскресенья.
    (Sunday → next full week; otherwise the rest of this week.)
    """
    if today.weekday() == 6:
        return today + timedelta(days=1), 1, 7
    last = 6 - today.weekday()
    return monday_of(today), (1 if trained_today else 0), last


def week_done(user_id: int, *, db: Session, week_start: date, today: date) -> dict:
    """Факт текущей недели по ЛОКАЛЬНОЙ дате тренировки: км, пробежки, качественные,
    была ли пробежка сегодня. Качество — по пульсу (is_quality_session), не по ярлыку
    классификатора (#290). (Week-to-date facts by local session date.)
    """
    user = db.query(User).filter(User.id == user_id).first()
    since = datetime.combine(week_start - timedelta(days=1), time.min, tzinfo=timezone.utc)
    sessions = db.query(TrainingSession).filter(
        TrainingSession.user_id == user_id,
        TrainingSession.begin_ts >= since,
    ).all()
    lthr = latest_lthr(user_id, db=db)
    max_hr = getattr(user, "max_hr", None)
    km, runs, quality, trained_today = 0.0, 0, 0, False
    for s in sessions:
        if s.begin_ts is None:
            continue
        d = session_local_dt(s.begin_ts, s, user).date()
        if not week_start <= d <= today:
            continue
        runs += 1
        km += float(s.total_distance_km or 0.0)
        if d == today:
            trained_today = True
        if is_quality_session(s.training_type, s.avg_heart_rate, max_hr, lthr):
            quality += 1
    return {"km": round(km, 1), "runs": runs, "quality_runs": quality,
            "trained_today": trained_today}
