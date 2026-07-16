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
    upload_dir: str = "uploads"

    # Тайминги (Timing)
    http_timeout: int = 15
    slow_request_ms: int = 1000

    # Часовой пояс по умолчанию (Default timezone)
    timezone: str = "UTC"

    model_config = {"env_prefix": ""}
