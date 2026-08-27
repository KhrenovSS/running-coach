# Конвертация времени в локальный пояс пользователя (User-local time conversion)
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from src.config import settings


def local_dt(dt: datetime | None, user: Any, session: Any = None,
             session_tz: str | None = None) -> datetime | None:
    """UTC → локальный пояс: user.timezone → session.timezone → settings.timezone.

    Naive datetime трактуется как UTC (в БД begin_ts хранится в UTC).
    session_tz — имя зоны тренировки, когда ORM-объекта уже нет под рукой.
    (Naive datetimes are treated as UTC; session_tz is the workout's zone name
    for call sites that no longer hold the ORM object.)
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    tz_name = (user.timezone if user is not None else None) \
        or (session.timezone if session is not None else None) \
        or session_tz or settings.timezone
    tz = ZoneInfo(tz_name)
    return dt.astimezone(tz)
