# Общие зависимости для приложения (Shared application dependencies)
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="src/web/templates")


def local_dt(dt: datetime, user, session=None) -> datetime:
    """Convert naive UTC datetime to naive local datetime using user's timezone"""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt
    tz_name = user.timezone or (session.timezone if session else None) or "Europe/Moscow"
    tz = ZoneInfo(tz_name)
    return dt.replace(tzinfo=timezone.utc).astimezone(tz).replace(tzinfo=None)

