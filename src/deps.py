# Общие зависимости для приложения (Shared application dependencies)
from fastapi.templating import Jinja2Templates

from src.utils.timeutils import local_dt  # noqa: F401 — re-export для веб-слоя (re-export for web layer)

templates = Jinja2Templates(directory="src/web/templates")
