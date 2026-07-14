# Общие зависимости для приложения (Shared application dependencies)
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi.templating import Jinja2Templates

from src.config import settings

templates = Jinja2Templates(directory="src/web/templates")


def local_dt(dt: datetime, user, session=None) -> datetime:
    """Convert UTC datetime to local datetime using user's timezone"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    tz_name = user.timezone or (session.timezone if session else None) or settings.timezone
    tz = ZoneInfo(tz_name)
    return dt.astimezone(tz)

