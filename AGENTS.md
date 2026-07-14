# Контекст проекта Running Coach

## Суть
Персональный AI-тренер для бега. Парсит TCX-файлы (любые часы: Garmin, Coros, Polar, Suunto), анализирует тренировки, определяет тип (интервальная/темповая/long/recovery), разбивает на сегменты, считает пульсовые зоны, очищает GPS-ошибки.

## Стек
Python + FastAPI + PostgreSQL 16 (Docker Compose), написано через ИИ (open code style).
Сервер: Docker Compose — 3 контейнера (`db`, `app`, `bot`).
Локальная разработка: `docker compose up db -d && DATABASE_URL=postgresql://running_coach:<PASSWORD>@localhost:5432/running_coach uvicorn main:app --host 0.0.0.0 --port 8000`.

## Дисциплина работы ИИ-агента (AI Agent Discipline)

1. **Потолок ~400 строк/файл.** Модель склонна дописывать в существующий файл; потолок этому противодействит. Если файл приближается к 400 строкам — выноси логику в новый модуль.

2. **Backlog-дисциплина.** Заметил мелочь (баг, TODO, улучшение) → строка в `BACKLOG.md`, обратно к текущей задаче. Не чини «заодно» — это увеличивает diff и затрудняет review.

3. **Секреты.** Нет ключа/токена/пароля → остановись и спроси пользователя. Не выдумывай плейсхолдеры (`sk-xxx`, `YOUR_TOKEN_HERE`) в коде или `.env`.

4. **Проверка спринта — behavioral test.** Не `py_compile` (проверяет только синтаксис). Проверяй поведение:
   ```bash
   python -c "from src.telegram.main import run_bot; print('OK')"  # импорт
   grep -rn "from src.database" src/ | wc -l                       # → 0
   ```
   Если бот — smoke-тест: запуск, `/start` отвечает.

5. **Таблица Docker rebuild.** Какую часть пересобрать при изменении модуля:

   | Изменённый модуль | Пересобрать |
   |-------------------|-------------|
   | `src/web/`, `src/api/`, `src/parsers/`, `src/services/`, `src/models.py`, `src/config/` | `app` |
   | `src/telegram/` | `bot` |
   | `src/watch/` | `app` + `bot` |
   | `pyproject.toml`, `Dockerfile` | `app` + `bot` |
   | `alembic/` | `app` (миграции при старте) |

6. **Протокол конца сессии.** commit → обновить чекбоксы в `AGENTS.md` → **удалить выполненные пункты из «Следующие шаги»** → обновить `CHANGELOG.md` → push → отчёт пользователю.

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
| Новый бренд часов | [`docs/CHECKLIST_NEW_PROVIDER.md`](docs/CHECKLIST_NEW_PROVIDER.md) |

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
- `src/models.py` — shim: реэкспорт из `src/domain/models/` + хелперы (get_settings, get_user, etc.)
- `src/domain/` — доменный слой:
  - `models/base.py` — Base, utcnow, get_engine, SessionLocal, get_db, init_db
  - `models/user.py` — User
  - `models/training.py` — TrainingSession, TrainingFeedback, DeletedTraining
  - `models/watch.py` — WatchCredential
  - `models/health.py` — DailyMetrics, WeightMeasurement
  - `models/auth.py` — AuthToken
  - `models/audit.py` — AuditEvent
- `src/config/settings.py` — `Settings(BaseSettings)` из pydantic-settings
- `src/config/constants.py` — плоские module-level константы
- `src/exceptions.py` — типизированные исключения приложения (`WatchAPIError`, `WatchAuthError`, `NotFoundError`, etc.)
- `src/deps.py` — общие зависимости (Jinja2Templates и др.)
- `src/utils/logger.py` — структурированное логирование с ротацией
- `src/watch/` — мульти-брендовая абстракция часовых клиентов (`base.py`, `coros.py`, `factory.py`)
- `src/services/audit.py` — сервис аудита (БД + файл)
- `src/services/auth.py` — генерация и проверка токенов Telegram-авторизации, bcrypt
- `src/services/sync/` — пакет синхронизации:
  - `utils.py` — SYNC_TICK_INTERVAL, _auto_sync_status, _make_client, интервалы
  - `health.py` — sync_health_for_user, save_dashboard_data
  - `activities.py` — sync_activities_for_user
  - `orchestrator.py` — run_sync_for_user, auto_sync_health, auto_sync_activities
- `src/services/sync_service.py` — shim для обратной совместимости (DeprecationWarning)
- `src/services/async_utils.py` — `run_async_in_thread(coro)` (единый helper для async-from-thread)
- `src/services/watch_credentials.py` — `upsert_watch_credential()` (шифрование + upsert)
- `src/services/training_service.py` — `delete_training()`, `upsert_feedback()`
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
- `src/web/routes/pages/` — пакет: `auth.py` (48), `index.py` (184), `session.py` (177), `settings.py` (118)
- `src/web/routes/uploads.py` — POST /upload, /upload/confirm
- `src/web/routes/sync.py` — POST /sync/{brand}/run, /sync/{brand}/health (93 строки)
- `src/web/routes/logs.py` — GET /logs
- `src/web/templates/` — 6 Jinja2-шаблонов
- `src/analysis/` — пакет анализа тренировок (6 файлов):
  - `__init__.py` — оркестратор `process_trackpoints()` (GPS → HR зоны → сегментация → классификация → осцилляции → погода)
  - `oscillation.py` — детекция осцилляций темпа + HR-lag корреляция
  - `classify.py` — классификация тренировок (interval/tempo/long/recovery)
  - `segment.py` — сегментация по темпу + fallback на осцилляции
  - `hr_zones.py` — пульсовые зоны
  - `utils.py` — форматирование, GPS-хелперы
- `src/parsers/` — парсеры TCX/FIT (`tcx_parser.py`, `fit_parser.py`), GPS (`gps.py`), погода (`weather.py`)
- `src/services/reanalyze.py` — сервис пересчёта тренировок с override типа

## Реализованная логика (сегментация, классификация, пульсовые зоны, осцилляции)
См. `docs/ARCHITECTURE.md` и `src/analysis/`.

## GitHub
Репозиторий: https://github.com/KhrenovSS/running-coach
Ветка: `main`
Правила работы: коммитить каждую логически законченную задачу. В конце сессии — commit + push.

### Push (токен из .env)
GITHUB_TOKEN лежит в `.env` в корне проекта. Для push:
```bash
source .env && git remote set-url origin https://${GITHUB_TOKEN}@github.com/KhrenovSS/running-coach.git && git push
git remote set-url origin https://github.com/KhrenovSS/running-coach.git  # восстановить
```
Пароль/токен отдельно не спрашивать — брать из `.env`.

## Текущее состояние (Session — 14.07.2026 — Sprint 11: Разбивка models.py + sync_service.py)

**Фаза A ✅:** Починены сломанные импорты в `src/telegram/` (AUDIT-015), удалены `COROS_SYNC_*` константы (AUDIT-011).
**Фаза B ✅:** Тонкие роуты (sync.py 444→93), мульти-бренд settings, единый `run_sync_for_user`, пакет `pages/`.
**Фаза C ✅:** Cleanup: `requests`→`httpx`, удалены мёртвые зависимости, `CorosAPIError`→`WatchAPIError` (brand-agnostic).
**Фаза D ✅:** Документация: `BACKLOG.md`, `docs/CHECKLIST_NEW_PROVIDER.md`, усилен `AGENTS.md`.
**Модуль анализа ✅:** Новый пакет `src/analysis/` (классификация, сегментация, пульсовые зоны, утилиты).
**Алгоритм интервалов ✅:** `src/analysis/oscillation.py` — детекция по базовому темпу (easy pace) + HR-lag корреляция.
**Отладка анализа ✅:** Исправлены баги: base_pace self-defeating, HR-lag инверсия, time units, NameError. Добавлен умный fallback: км-блоки если сегменты похожи или число отлично от км. 40 тестов, 29 тренировок пересчитаны (27/29 ✓).
**Сегментация ✅:** Distance-based change points + адаптивный порог + защита oscillation-сегментов + km fallback для монотонных.
**Sprint 11 ✅:** Разбивка models.py на `src/domain/models/` (9 моделей, 7 файлов) + разбивка sync_service.py на `src/services/sync/` (4 модуля: utils, health, activities, orchestrator).

### Что сделано в этой сессии (13.07.2026):
1. `segment.py`: distance-based change points (`CHANGE_POINT_WINDOW_M=200` вместо 10 точек)
2. `segment.py`: адаптивный порог `_adaptive_min_diff(max(0.3, 0.25*range))`
3. `segment.py`: убран хардкод `3.0 < pace < 12.0` → `max_credible_pace < pace < 15.0`
4. `segment.py`: защита oscillation-сегментов от km fallback (только если Z4+ и разброс ≥ 0.5)
5. `segment.py`: km fallback для монотонных (≤2 сегментов и нет осцилляций → км-блоки)
6. `segment.py`: count_off проверка внутри oscillation-ветки + защита реальных интервалов
7. `oscillation.py`: `_estimate_base_pace()` через 60-й процентиль вместо mean
8. `oscillation.py`: `_adaptive_pace_gap()` — data-driven gap, capped by user setting
9. `oscillation.py`: `<= threshold` вместо `<` + merge смежных однотипных фаз
10. `analysis/__init__.py`: `_is_km_segmentation()` — сброс сигналов интервалов при км-блоках
11. Проверка на реальных тренировках: #73 (6.2км монотонная → км-блоки), #102 (темп), #101 (интервалы 12 сегментов)
12. +16 тестов (56 всего), Docker rebuild app

### Коммиты:
- `cda4a0a` Sprint 8+9: разбивка parsers/common.py и telegram_bot.py на пакеты
- `3b4dd34` fix segmentation and tcx_parser import
- `f1a60fa` feat: модуль анализа + новый алгоритм детекции интервалов
- `99be684` fix: отладка и улучшение алгоритма анализа (40 тестов, 29 тренировок пересчитаны)
- *(Фаза A+B+C+D: коммит будет выполнен после проверки)*

### Следующие шаги:
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
