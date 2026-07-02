# Роут для просмотра логов (Log viewer route)

import os
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get('/logs')
async def view_logs(lines: int = 100):
    from datetime import date
    from src.config import CONFIG

    log_filename = f"app_{date.today().isoformat()}.log"
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), CONFIG.LOG_FILE)
    rotated_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", log_filename)

    chosen_path = None
    for path in [rotated_path, log_path]:
        if os.path.exists(path):
            chosen_path = path
            break

    if not chosen_path:
        return HTMLResponse("<html><body><h2>Лог пуст</h2></body></html>")

    with open(chosen_path, "r", encoding="utf-8") as f:
        all_lines = f.readlines()
    tail = all_lines[-lines:]
    html = "<html><head><meta charset='utf-8'><title>Лог операций</title>"
    html += "<style>body{font-family:monospace;font-size:13px;background:#1e1e1e;color:#d4d4d4;padding:20px}"
    html += ".INFO{color:#4ec9b0}.WARNING{color:#ce9178}.ERROR{color:#f44747}.DEBUG{color:#808080}"
    html += "a{color:#569cd6;text-decoration:none;margin-right:10px}</style></head><body>"
    html += f"<h2>📋 Лог операций ({os.path.basename(chosen_path)})</h2>"
    html += f"<p>Последние {len(tail)} строк (<a href='/logs?lines=50'>50</a> "
    html += f"<a href='/logs?lines=200'>200</a> <a href='/logs?lines=1000'>все</a>)</p>"
    html += "<pre>"
    for line in tail:
        level = "INFO" if "INFO" in line else ("WARNING" if "WARNING" in line else
                ("ERROR" if "ERROR" in line else "DEBUG"))
        html += f"<span class='{level}'>{line.strip()}</span>\n"
    html += "</pre></body></html>"
    return HTMLResponse(html)
