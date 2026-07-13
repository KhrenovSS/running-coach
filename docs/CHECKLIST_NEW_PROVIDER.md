# Чеклист: новый бренд часов (New Provider Checklist)

Пошаговая инструкция для добавления нового бренда часов (Polar, Garmin, Suunto и др.).

---

## 0. Перед началом

- [ ] Найти неофициальное API бренда (аналог Coros Training Hub)
- [ ] Определить эндпоинты: авторизация, список тренировок, скачивание FIT/TCX, метрики здоровья, дашборд, аналитика
- [ ] Убедиться, что API поддерживает email/password авторизацию (или определить альтернативу)

---

## 1. Клиент (`src/watch/<brand>.py`)

Создать файл, наследовать `BaseWatchClient`:

```python
# src/watch/polar.py (пример)
from src.watch.base import BaseWatchClient
from src.utils.logger import get_logger

logger = get_logger("watch.<brand>")

class PolarWatchClient(BaseWatchClient):
    """Polar Flow API client"""

    def __init__(self, email: str = "", password: str = "", **kwargs):
        self.email = email
        self.password = password
        # ... инициализация httpx.AsyncClient

    async def authenticate(self) -> bool:
        """Логин, получить access_token"""
        ...

    async def list_activities(self, since=None) -> list[dict]:
        """Список тренировок (формат — как у Coros: id, sportType, startTime, distance, ...])"""
        ...

    async def download_activity(self, activity_id: str, sport_type: int) -> bytes | None:
        """Скачать FIT/TCX файл тренировки"""
        ...

    async def get_daily_metrics(self, start_day: str, end_day: str) -> list[dict]:
        """Метрики здоровья за период (HRV, RHR, tiredness, ...)"""
        ...

    async def get_dashboard(self) -> dict:
        """Дашборд восстановления (recovery, training load, ...)"""
        ...

    async def get_analytics(self) -> list[dict]:
        """Аналитика за 12 недель (VO2max, LTHR, stamina, ...)"""
        ...
```

**Требования к формату данных** (см. `CorosWatchClient` как референс):

| Метод | Формат возврата |
|-------|----------------|
| `list_activities` | `[{"id": str, "sportType": int, "startTime": str (ISO), "distance": float, "duration": int, ...}]` |
| `download_activity` | `bytes` (FIT или TCX) |
| `get_daily_metrics` | `[{"entryDate": str (YYYY-MM-DD), "avgSleepHrv": float, "rhr": int, ...}]` |
| `get_dashboard` | `{"recoveryLevel": float, "trainingLoad": float, ...}` |
| `get_analytics` | `[{"date": str, "vo2max": float, "lthr": int, ...}]` |

---

## 2. Регистрация (`src/watch/__init__.py`)

Добавить импорт и `register()`:

```python
from src.watch.coros import CorosWatchClient
from src.watch.polar import PolarWatchClient  # ← новый
from src.watch.factory import register

register("coros", CorosWatchClient)
register("polar", PolarWatchClient)  # ← новый
```

**Важно:** регистрация через реестр (`register()`), НЕ через `if/else` в коде.

---

## 3. Конфигурация

Если нужны переменные окружения (API ключи, base URL):

1. Добавить в `src/config/settings.py` (поле `Settings(BaseSettings)`)
2. Добавить в `.env.example` с комментарием
3. Использовать `settings.<field>` в клиенте

---

## 4. Исключения

Использовать общие `WatchAPIError` и `WatchAuthError` из `src/exceptions.py`:

```python
from src.exceptions import WatchAPIError, WatchAuthError

raise WatchAPIError(message="...", brand="polar", status=401)
raise WatchAuthError(message="...", brand="polar")
```

Не создавать локальные `PolarAPIError` / `PolarAuthError`.

---

## 5. Smoke-тест

```bash
# Проверка импорта и фабрики
python -c "from src.watch.factory import get_watch_client; c = get_watch_client('polar'); print(type(c).__name__)"
# Ожидаемый вывод: PolarWatchClient

# Проверка списка брендов
python -c "from src.watch.factory import list_brands; print(list_brands())"
# Ожидаемый вывод: ['coros', 'polar']
```

---

## 6. Интеграция

- `sync_service.py` уже бренд-независим — вызывает `get_watch_client(brand, ...)`
- Telegram-бот: `sync_runner.py` — TODO: миграция на `run_sync_for_user_all_brands()`
- Веб: `web/routes/sync.py` — передаёт `brand` из URL
- Scheduler: `scheduler.py` — бренд-независим, перебирает `WatchCredential`

Ничего менять не нужно — синхронизация работает автоматически для нового бренда.

---

## 7. Docker

Не требует изменений `Dockerfile` или `docker-compose.yml`.

Если бренд требует новые pip-зависимости:
1. Добавить в `pyproject.toml`
2. Пересобрать: `./bin/docker.sh build app && ./bin/docker.sh build bot`

---

*Создан: 13.07.2026 (Фаза D)*
