# Роут для просмотра логов (Log viewer route) — #303/#119 (07.09.2026): только для вошедшего
# пользователя; путь — каталог логов приложения (LOGS_DIR), имена ротации совпадают с
# TimedRotatingFileHandler (`app.log`, `app.log.YYYY-MM-DD`); день — строго YYYY-MM-DD (без traversal).
# (Authenticated log viewer that matches the real rotation naming.)

import html as _html
import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

from src.api.deps import get_current_user
from src.config import settings
from src.models import User
from src.utils.logger import LOGS_DIR

router = APIRouter()

LOG_LINES_MAX = 5000
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _log_candidates(day: str | None) -> list:
    """Файлы на просмотр по приоритету: живой файл (сегодня) или ротированный за день."""
    base = LOGS_DIR / settings.log_file
    if day is None or day == date.today().isoformat():
        return [base, LOGS_DIR / f"{settings.log_file}.{date.today().isoformat()}"]
    return [LOGS_DIR / f"{settings.log_file}.{day}"]


def _available_days() -> list[str]:
    """Дни, за которые есть ротированные файлы (новые первыми)."""
    if not LOGS_DIR.exists():
        return []
    prefix = f"{settings.log_file}."
    days = [p.name[len(prefix):] for p in LOGS_DIR.iterdir()
            if p.name.startswith(prefix) and _DAY_RE.match(p.name[len(prefix):])]
    return sorted(days, reverse=True)


@router.get('/logs')
async def view_logs(lines: int = 100, day: str | None = None,
                    current_user: User = Depends(get_current_user)):
    if day is not None and not _DAY_RE.match(day):
        raise HTTPException(status_code=400, detail="day must be YYYY-MM-DD")
    lines = max(1, min(int(lines), LOG_LINES_MAX))
    chosen = next((p for p in _log_candidates(day) if p.exists()), None)
    days = _available_days()
    nav = " ".join(f"<a href='/logs?day={d}&lines={lines}'>{d}</a>" for d in days[:10])
    if chosen is None:
        return HTMLResponse("<html><head><meta charset='utf-8'></head><body><h2>Лог пуст</h2>"
                            f"<p>{nav}</p></body></html>")
    with open(chosen, "r", encoding="utf-8", errors="replace") as f:
        tail = f.readlines()[-lines:]
    out = ["<html><head><meta charset='utf-8'><title>Лог операций</title>",
           "<style>body{font-family:monospace;font-size:13px;background:#1e1e1e;color:#d4d4d4;padding:20px}",
           ".INFO{color:#4ec9b0}.WARNING{color:#ce9178}.ERROR{color:#f44747}.DEBUG{color:#808080}",
           "a{color:#569cd6;text-decoration:none;margin-right:10px}</style></head><body>",
           f"<h2>📋 Лог операций ({_html.escape(chosen.name)})</h2>",
           f"<p>Последние {len(tail)} строк (<a href='/logs?lines=50'>50</a> "
           f"<a href='/logs?lines=200'>200</a> <a href='/logs?lines={LOG_LINES_MAX}'>все</a>)</p>",
           f"<p>Дни: {nav}</p>" if nav else "", "<pre>"]
    for line in tail:
        level = ("INFO" if "INFO" in line else "WARNING" if "WARNING" in line
                 else "ERROR" if "ERROR" in line else "DEBUG")
        out.append(f"<span class='{level}'>{_html.escape(line.rstrip())}</span>\n")
    out.append("</pre></body></html>")
    return HTMLResponse("".join(out))
