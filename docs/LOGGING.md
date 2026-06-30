# Логирование и аудит (Logging and Audit)

## Уровни наблюдаемости (Observability levels)

Проект реализует **Level 2 Standard observability**:

- Структурированные логи приложения (`logs/app_YYYY-MM-DD.log`)
- Логи API-запросов (`logs/requests_YYYY-MM-DD.log`)
- Аудит-события в БД (`audit_events`) и в файле (`logs/audit_YYYY-MM-DD.log`)
- Порог медленного запроса: **1000 мс**

## Переменные окружения (Environment variables)

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `LOG_LEVEL` | `info` | Уровень логирования: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `LOG_FORMAT` | `text` | Формат: `text` (читаемый) или `json` (для анализа) |
| `LOGS_DIR` | `logs` | Директория для лог-файлов |
| `SLOW_REQUEST_MS` | `1000` | Порог медленного запроса в мс |

Пример `.env` см. в `.env.example`.

## Файлы логов (Log files)

Все файлы ротируются ежедневно в полночь UTC. Хранятся 30 дней.

```
logs/
├── app_YYYY-MM-DD.log          # Логи приложения
├── requests_YYYY-MM-DD.log     # Логи HTTP-запросов
└── audit_YYYY-MM-DD.log        # Аудит-события (дублирование БД)
```

## Как получить логгер (How to get a logger)

```python
from src.utils.logger import get_logger

logger = get_logger("app")
logger.info("Sync completed", extra={"count": 5})
```

## Аудит-события (Audit events)

Аудит пишется в таблицу `audit_events` и параллельно в `logs/audit_*.log`.

### Типы событий (Event types)

| Тип | Описание | Источники |
|-----|----------|-----------|
| `app.startup` | Приложение запущено | `main.py` |
| `training.uploaded` | Тренировка загружена | `/upload`, `/upload/confirm`, `/upload/confirm_deleted`, Coros sync |
| `training.deleted` | Тренировка удалена | `/session/{id}/delete` |
| `settings.changed` | Изменены настройки пользователя | `/settings`, Telegram `/start`, Telegram `/delete_me` |
| `coros.sync.started` | Начата синхронизация Coros | Telegram `/sync`, `/coros/sync` |
| `coros.sync.completed` | Синхронизация Coros завершена | Telegram `/sync`, `/coros/sync` |
| `coros.sync.failed` | Ошибка синхронизации Coros | Telegram `/sync`, `/coros/sync` |
| `telegram.sent` | Telegram-уведомление отправлено | Telegram bot |
| `telegram.failed` | Ошибка отправки Telegram | Telegram bot |
| `auth.login` | Пользователь вошёл через Telegram | `/auth/telegram` |
| `auth.login_failed` | Неудачная попытка входа | `/auth/telegram` |
| `auth.logout` | Пользователь вышел | `/auth/logout` |

### Использование AuditService

```python
from src.services.audit import AuditService

audit = AuditService(db)
audit.log_training_uploaded(user_id=1, training_id=42, filename="run.tcx")
audit.log_settings_changed(user_id=1, changes={"max_hr": {"old": 170, "new": 175}})
```

## Чтение логов через веб-интерфейс (View logs via web UI)

```
GET /logs?lines=200
```

Показывает последние N строк из текущего лог-файла приложения.

## Рекомендации (Best practices)

- Не логируй пароли, токены, персональные данные.
- Используй `extra={...}` для структурированных полей.
- Лови конкретные исключения, не `except: pass`.
- Для ошибок сервисов используй `src/exceptions.py`.
