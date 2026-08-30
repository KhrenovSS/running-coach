# Запись данных сна из скриншота в DailyMetrics (Sleep-screenshot ingest) — #257
#
# Upsert по (user_id, date) — паттерн save_dashboard_data (sync/health.py):
# не перетираем HRV/recovery из Coros-синка, пишем только поля сна из скрина.
# (Upsert sleep-screenshot fields into DailyMetrics without clobbering Coros HRV.)

from __future__ import annotations

from datetime import date as _date

from sqlalchemy.orm import Session

from src.coach.vision import SleepShot
from src.models import DailyMetrics, User
from src.utils.logger import get_logger
from src.utils.timeutils import user_now

logger = get_logger("services.sleep_ingest")

SLEEP_SOURCE = "coros_screenshot"


def save_sleep_shot(user_id: int, shot: SleepShot, *, db: Session) -> DailyMetrics:
    """Записать сон из скрина в DailyMetrics за локальную «сегодня» пользователя.

    Дата — из скрина, если распознана и валидна, иначе локальная дата пользователя
    (сон = ночь, завершившаяся этим утром). (Attribute to the user's local day.)
    """
    user = db.query(User).filter(User.id == user_id).first()
    day = _resolve_date(shot.date, user)
    dm = db.query(DailyMetrics).filter(
        DailyMetrics.user_id == user_id, DailyMetrics.date == day).first()
    if dm is None:
        dm = DailyMetrics(user_id=user_id, date=day)
        db.add(dm)
        db.flush()
    dm.sleep_duration_min = shot.duration_min
    dm.sleep_awake_min = shot.awake_min
    dm.sleep_deep_min = shot.deep_min          # минуты фаз — если экран их показывает
    dm.sleep_rem_min = shot.rem_min
    dm.sleep_score = shot.score
    dm.sleep_extra = shot.extra()              # deep_pct/rem_pct/stress/bedtime/note
    dm.sleep_source = SLEEP_SOURCE
    db.commit()
    logger.info("Sleep shot saved: user=%s date=%s dur=%s extra=%s",
                user_id, day, shot.duration_min, bool(shot.extra()))
    return dm


def _resolve_date(shot_date: str | None, user: User | None) -> _date:
    if shot_date:
        try:
            return _date.fromisoformat(shot_date)
        except ValueError:
            pass
    return user_now(user).date()
