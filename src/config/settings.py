# Настройки приложения из переменных окружения (Application settings from env vars)
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Настройки аутентификации (Auth settings)
    password_min_length: int = 6
    token_ttl_minutes: int = 30
    session_ttl_days: int = 7

    # Пульсовые зоны (Heart rate zones)
    default_max_hr: int = 177

    # URL веб-приложения для CSRF и ссылок (Web app URL for CSRF and links)
    web_app_url: str = ""

    # Пути (Paths)
    log_file: str = "app.log"
    raw_files_dir: str = "uploads/raw"  # хранилище исходных FIT/TCX (raw FIT/TCX storage, BACKLOG #229)

    # Тайминги (Timing)
    http_timeout: int = 15
    slow_request_ms: int = 1000

    # Часовой пояс по умолчанию (Default timezone)
    timezone: str = "UTC"

    # Коуч (Hybrid coach — DEV_PLAN); рубильник свободного чата и проактивности
    coach_enabled: bool = True
    # LLM: пустой ключ = детерминированный режим (empty key = deterministic mode)
    anthropic_api_key: str = ""
    coach_llm_model: str = "claude-opus-5"
    coach_llm_effort: str = "low"          # low для чата; medium для плана (C7+)

    model_config = {"env_prefix": ""}
