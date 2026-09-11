# Логирование и аудит (Logging and Audit)

## Уровни наблюдаемости (Observability levels)

Проект реализует **Level 2 Standard observability**:

- Структурированные логи приложения (`logs/app.log.YYYY-MM-DD`)
- Логи API-запросов (`logs/requests.log.YYYY-MM-DD`)
- Аудит-события в БД (`audit_events`) и в файле (`logs/audit.log.YYYY-MM-DD`)
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
├── app.log.YYYY-MM-DD          # Логи приложения
├── requests.log.YYYY-MM-DD     # Логи HTTP-запросов
└── audit.log.YYYY-MM-DD        # Аудит-события (дублирование БД)
```

## Как получить логгер (How to get a logger)

```python
from src.utils.logger import get_logger

logger = get_logger("app")
logger.info("Sync completed", extra={"count": 5})
```

### Конвенция имён логгеров

Имя — иерархическое, по модулю: `get_logger("coach.orchestrator")`, `get_logger("telegram.handlers.coach")`.
Используемые пространства: `app` (общий), `coach.*` (agent, llm, orchestrator — его же намеренно
использует `chat_flow.py`, planning — включая `planning_rows`/`planning_availability`, prescriber, review_flow,
vision, tools, week_report, weekly_plan), `telegram.handlers.*`, `telegram.jobs.*`, `telegram.main`,
`telegram.utils`, `telegram.sync_runner`, `analysis` / `analysis.*` (segment, gps_quality,
data_checks), `analysis.reanalyze` (`services/reanalyze.py`), `parsers.*` (gps, weather), `services.*`
(workout_insights — его же намеренно использует `workout_insights_context.py`, insights_baseline,
prediction_log, sleep_ingest, type_resolution_backfill), `api.deps`, `auth`, `crypto`,
`rate_limit`, `raw_files`, `training_service`, `watch.coros`, `watch_credentials`.
Новый модуль получает логгер по своему пути — не переиспользуй `"app"`.

## Аудит-события (Audit events)

Аудит пишется в таблицу `audit_events` и параллельно в `logs/audit.log` (ротация — `audit.log.YYYY-MM-DD`).

### Типы событий (Event types)

| Тип | Описание | Источники |
|-----|----------|-----------|
| `app.startup` | Приложение запущено | `src/startup.py` |
| `app.error` | Ошибка, зафиксированная `AuditService.log_error` | сервисы, middleware |
| `training.uploaded` | Тренировка загружена | `/upload`, `/upload/confirm`, `/upload/confirm_deleted`, Coros sync |
| `training.deleted` | Тренировка удалена | `/session/{id}/delete` |
| `training.delete_failed` | Ошибка удаления тренировки | `/session/{id}/delete` |
| `training.upload_summary` | Сводка по загруженным тренировкам | `/upload` |
| `training.confirm_upload` | Подтверждение загрузки (сommon) | `/upload/confirm` |
| `training.confirm_deleted` | Подтверждение повторной загрузки удалённой тренировки | `/upload/confirm_deleted` |
| `feedback.created` | Оценка тренировки создана | `/session/{id}/feedback`, Telegram feedback |
| `feedback.updated` | Оценка тренировки обновлена | `/session/{id}/feedback`, Telegram feedback |
| `settings.changed` | Изменены настройки пользователя | `/settings`, Telegram `/start`, `/delete_me`, `/reset_password`, кнопка max_hr в Telegram, авто-повышение max_hr (`services/hr_max.py`) |
| `settings.max_hr_suggest` | Предложение снизить max_hr (по нему — кулдаун 30 дней) | `services/hr_max.py` (джоб понедельника) |
| `sync.{brand}.started` | Начата синхронизация часов | Telegram `/sync`, `/sync/{brand}/run` |
| `sync.{brand}.completed` | Синхронизация часов завершена | Telegram `/sync`, `/sync/{brand}/run` |
| `sync.{brand}.failed` | Ошибка синхронизации часов | Telegram `/sync`, `/sync/{brand}/run` |
| `telegram.notification.sent` | Telegram-уведомление отправлено | Telegram bot |
| `telegram.notification.failed` | Ошибка отправки Telegram | Telegram bot |
| `telegram.received` | Команда получена от пользователя | Telegram bot |
| `user.registered` | Пользователь зарегистрирован | Telegram `/start` |
| `auth.register` | Регистрация через веб | `/auth/register` |
| `auth.register_failed` | Ошибка регистрации | `/auth/register` |
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
GET /logs?lines=100
GET /logs?lines=100&day=YYYY-MM-DD
```

Показывает последние N строк из текущего лог-файла приложения (уровень строки — по полю формата `| LEVEL |`,
не по подстроке в тексте; CRITICAL подсвечивается как ERROR, #120); `day` — ротированный файл за указанный день (`<log_file>.YYYY-MM-DD`, формат проверяется, иначе 400).

## Рекомендации (Best practices)

- Не логируй пароли, токены, персональные данные.
- Используй `extra={...}` для структурированных полей.
- Лови конкретные исключения, не `except: pass`.
- Для ошибок сервисов используй `src/exceptions.py`.
