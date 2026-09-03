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


def session_local_dt(dt: datetime | None, session: Any = None,
                     user: Any = None) -> datetime | None:
    """UTC → пояс тренировки: session.timezone → user.timezone → settings.timezone.

    Обратный приоритет к local_dt: тренировка в поездке показывается в её поясе.
    (Workout-first zone priority: a workout done while travelling keeps its own zone.)
    """
    if session is not None and getattr(session, "timezone", None):
        return local_dt(dt, None, session=session)
    return local_dt(dt, user)


def user_now(user: Any) -> datetime:
    """Текущее время в поясе пользователя (current time in the user's timezone)."""
    return local_dt(datetime.now(timezone.utc), user)


# Русские названия дней недели — единый источник для промптов и карточек
# (Russian weekday names — single source for prompts and cards)
WEEKDAYS_RU = ("понедельник", "вторник", "среда", "четверг",
               "пятница", "суббота", "воскресенье")
# Короткие дни для строк списков (карточка недели, строка «Изменил план на …»);
# заголовки карточек дня — полные (решение владельца 03.09.2026). (Short weekday labels.)
WEEKDAYS_RU_SHORT = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


def fmt_local(dt: datetime) -> str:
    """'суббота, 2026-08-29 07:49 (Europe/Moscow)' — дата-время для LLM-контекста.

    День недели — готовым словом: LLM не должна вычислять его из ISO-даты.
    (Weekday spelled out — the LLM must not derive it from the ISO date.)
    """
    return f"{WEEKDAYS_RU[dt.weekday()]}, {dt:%Y-%m-%d %H:%M} ({dt.tzinfo.key})"
