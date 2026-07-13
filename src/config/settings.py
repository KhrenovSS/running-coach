# Настройки приложения из переменных окружения (Application settings from env vars)
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Настройки аутентификации (Auth settings)
    password_min_length: int = 6
    token_ttl_minutes: int = 30
    session_ttl_days: int = 7

    # Пульсовые зоны (Heart rate zones)
    default_max_hr: int = 177

    # Пути (Paths)
    log_file: str = "app.log"
    upload_dir: str = "uploads"

    # Тайминги (Timing)
    http_timeout: int = 15

    model_config = {"env_prefix": ""}
