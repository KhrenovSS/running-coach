# Контекст проекта Running Coach

## Суть
Персональный AI-тренер для бега. Парсит TCX-файлы (любые часы: Garmin, Coros, Polar, Suunto), анализирует тренировки, определяет тип (интервальная/темповая/long/recovery), разбивает на сегменты, считает пульсовые зоны, очищает GPS-ошибки.

## Стек
Python + FastAPI + PostgreSQL 16 (Docker Compose), написано через ИИ (open code style).
Сервер: Docker Compose — 3 контейнера (`db`, `app`, `bot`).
Локальная разработка: `docker compose up db -d && DATABASE_URL=postgresql://running_coach:<PASSWORD>@localhost:5432/running_coach uvicorn main:app --host 0.0.0.0 --port 8000`.

## Документация для разработки
**Перед написанием кода прочитай соответствующий раздел:**
| Задача | Документация |
|--------|--------------|
| Общие правила написания кода | [`docs/CODE_GUIDELINES.md`](docs/CODE_GUIDELINES.md) |
| Архитектура и структура проекта | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| Как писать API endpoints | [`docs/API_ROUTES_GUIDE.md`](docs/API_ROUTES_GUIDE.md) |
| Обработка ошибок | [`docs/ERROR_HANDLING.md`](docs/ERROR_HANDLING.md) |
| Соглашения об именовании | [`docs/NAMING_CONVENTIONS.md`](docs/NAMING_CONVENTIONS.md) |
| Как писать тесты | [`docs/TESTING.md`](docs/TESTING.md) |
| Логирование и аудит | [`docs/LOGGING.md`](docs/LOGGING.md) |
| Code review / самопроверка | [`docs/CHECKLIST_FEATURE.md`](docs/CHECKLIST_FEATURE.md) |
| Миграции БД | [`docs/CHECKLIST_MIGRATION.md`](docs/CHECKLIST_MIGRATION.md) |

## Золотые правила (кратко)
1. **Константы** — используй `from src.config import CONFIG`. Никаких magic numbers.
2. **Ошибки** — используй `src/exceptions.py`. Запрещён `except: pass`.
3. **API** — тонкие роуты: валидация → сервис → ответ.
4. **Бизнес-логика** — в `src/services/<domain>/`, не в роуте.
5. **База данных** — миграции только через Alembic; параметризованные запросы.
6. **Логирование** — `logger` из `src.utils.logger`, не `print()`.
7. **Комментарии** — bilingual (RU/EN), сразу.
8. **Тесты** — unit для логики, integration для endpoint.
9. **CHANGELOG** — обновляй в том же коммите.
10. **Мульти-брендовость закладывать сразу** — не хардкодить «coros».

## Структура файлов
- `main.py` — 7 строк: `create_app()` + `uvicorn.run()`
- `run_telegram_bot.py` — импорт `run_bot` из `src.telegram`
- `src/startup.py` — фабрика FastAPI, startup-событие, подключение роутов
- `src/scheduler.py` — `AutoSyncScheduler` (бренд-независимый)
- `src/models.py` — все ORM модели (планируется разбивка Sprint 11)
- `src/config/settings.py` — `Settings(BaseSettings)` из pydantic-settings
- `src/config/constants.py` — плоские module-level константы
- `src/exceptions.py` — типизированные исключения приложения (`WatchAPIError`, `WatchAuthError`, `NotFoundError`, etc.)
- `src/deps.py` — общие зависимости (Jinja2Templates и др.)
- `src/utils/logger.py` — структурированное логирование с ротацией
- `src/watch/` — мульти-брендовая абстракция часовых клиентов (`base.py`, `coros.py`, `factory.py`)
- `src/services/audit.py` — сервис аудита (БД + файл)
- `src/services/auth.py` — генерация и проверка токенов Telegram-авторизации, bcrypt
- `src/services/sync_service.py` — бренд-независимая логика синхронизации
- `src/services/async_utils.py` — `run_async_in_thread(coro)` (единый helper для async-from-thread)
- `src/services/stats.py` — calc_stats, fmt_duration, build_nav_html, пульсовые зоны
- `src/services/recovery_view.py` — hrv_status, tired_label, readiness_label, load_label
- `src/services/telegram_notify.py` — отправка уведомлений в Telegram
- `src/telegram/` — пакет Telegram-бота (12 файлов, разделён):
  - `main.py` — `run_bot`, Application сборка
  - `config.py` — константы состояний
  - `state.py` — `_awaiting_weight`
  - `utils.py` — `get_user`, `_get_web_app_url`
  - `sync_runner.py` — `run_sync_in_thread`
  - `handlers/start.py`, `sync.py`, `stats.py`, `trainings.py`, `weight.py`, `account.py`, `feedback.py`
  - `jobs/weight.py`, `recovery.py`
- `src/api/middleware.py` — централизованная обработка ошибок, логирование запросов и session middleware
- `src/api/deps.py` — `get_current_user` dependency (session-cookie)
- `src/api/routes/health.py` — health check endpoint
- `src/api/routes/auth.py` — маршруты аутентификации
- `src/web/state.py` — глобальное состояние (`_pending`, `_sync_tasks`)
- `src/web/routes/pages.py` — GET /, /login, /register, /session/{id}, /settings
- `src/web/routes/uploads.py` — POST /upload, /upload/confirm
- `src/web/routes/sync.py` — POST /sync/{brand}/run, /sync/{brand}/health
- `src/web/routes/logs.py` — GET /logs
- `src/web/templates/` — 6 Jinja2-шаблонов
- `src/parsers/` — 10 файлов (common.py + gps.py, weather.py, hr_zones.py, classification.py, segmentation.py, utils.py, tcx_parser.py, fit_parser.py)

## Реализованная логика (сегментация, классификация, пульсовые зоны)
См. `docs/ARCHITECTURE.md` и `src/parsers/`.

## GitHub
Репозиторий: https://github.com/KhrenovSS/running-coach
Ветка: `main`
Правила работы: коммитить каждую логически законченную задачу. В конце сессии — commit + push.

## Текущее состояние (Session — 13.07.2026 — Фаза A+B+C завершены)

**Фаза A ✅:** Починены сломанные импорты в `src/telegram/` (AUDIT-015), удалены `COROS_SYNC_*` константы (AUDIT-011).
**Фаза B ✅:** Тонкие роуты (sync.py 444→93), мульти-бренд settings, единый `run_sync_for_user`, пакет `pages/`.
**Фаза C ✅:** Cleanup: `requests`→`httpx` в weather.py, удалены `APScheduler`/`requests` из deps, удалены мёртвые HR-zone функции из constants.py, `CorosAPIError`→`WatchAPIError`, `CorosAuthError`→`WatchAuthError` (brand-agnostic), удалено `db_path` из settings.py, унифицирован `run_async_in_thread` helper (AUDIT-008).

### Что сделано в этой сессии (13.07.2026 — Фаза A+B+C):
1. **Фаза A**: Импорты `from src.database` → `from src.models` (11 файлов). `sync_runner.py` переписан (SyncService/SyncLog/full_sync → реальные sync-функции). `TrainingSession.start_time` → `begin_ts` (7 ссылок). Удалены `COROS_SYNC_*` из audit.py.
2. **Фаза B**: `pages.py` → пакет `pages/` (auth 48, index 184, session 177, settings 118). `sync.py` 444→93. Единый `run_sync_for_user()`. Бизнес-логика из роутов в сервисы (`watch_credentials.py`, `training_service.py`).
3. **Фаза C**: `weather.py`: `requests` → `httpx`. `pyproject.toml`: удалены `APScheduler`, `requests`. `constants.py`: удалены `calculate_hr_zones`, `get_hr_zone`, 10 констант `Z*_PCT`. `exceptions.py`: `CorosAPIError`→`WatchAPIError`, добавлен `WatchAuthError`. `coros.py`: локальные исключения удалены, импорт из `exceptions.py`, все `raise` обновлены с `brand="coros"`. `settings.py`: удалено `db_path`. `async_utils.py`: единый `run_async_in_thread`. `sync_service.py` и `sync_runner.py`: `_run_async` и `asyncio.run` → `run_async_in_thread`.

### Коммиты:
- `cda4a0a` Sprint 8+9: разбивка parsers/common.py и telegram_bot.py на пакеты
- `3b4dd34` fix segmentation and tcx_parser import
- *(Фаза A+B+C: коммит будет выполнен после проверки)*

### Следующие шаги:
- **Docker**: пересобрать `app` и `bot` (изменены weather.py, exceptions.py, coros.py, sync_service.py, sync_runner.py, pyproject.toml)
- **Коммит**: Фаза A+B+C → push
- **Sprint 10**: Тесты (минимум 20) с реальными TCX/FIT-файлами.
- **Sprint 11**: Разбивка models.py + sync_service.py на пакеты.
- **Sprint 12**: Чистка роутов (sync.py, pages.py).
- **Sprint 13-15**: Фазы 3-5 (новая функциональность).

### Команды управления:
```bash
./bin/docker.sh up -d        # запуск
./bin/docker.sh down          # остановка
./bin/docker.sh build app     # пересборка app
./bin/docker.sh build bot     # пересборка bot
python3 -m alembic upgrade head  # миграции
```
