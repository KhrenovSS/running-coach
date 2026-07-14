# Общие зависимости для приложения (Shared application dependencies)
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi.templating import Jinja2Templates

from src.config import settings

templates = Jinja2Templates(directory="src/web/templates")


def local_dt(dt: datetime | None, user: Any, session: Any = None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    tz_name = user.timezone or (session.timezone if session else None) or settings.timezone
    tz = ZoneInfo(tz_name)
    return dt.astimezone(tz)
