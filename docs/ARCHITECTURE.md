# Архитектура проекта (Project Architecture)

> Где размещать код? Как организован проект? Читай перед созданием новых файлов.

## Текущий стек (Current stack)

- **Backend:** Python 3.13+, FastAPI
- **База данных:** PostgreSQL 16 + SQLAlchemy ORM
- **Миграции:** Alembic (автоматически при старте контейнера `app`)
- **Тесты:** pytest, freezegun
- **Логирование:** структурированное, ежедневная ротация (`TimedRotatingFileHandler`), JSON/text
- **Frontend:** Jinja2 templates + Chart.js (vanilla JS)
- **Docker:** Docker Compose — 3 контейнера (`db`, `app`, `bot`)
- **Аутентификация:** bcrypt + session-cookie (`SessionMiddleware`)
- **Шифрование:** Fernet (пароли часов, email)

## Структура проекта (Project structure)

```
running-coach/
├── alembic/                    # Миграции Alembic
│   ├── versions/               # Файлы миграций
│   └── env.py                  # Конфигурация Alembic
├── bin/
│   └── docker.sh               # Защищённая обёртка docker compose (создаётся локально, .gitignore)
├── docs/                       # Документация
│   ├── ARCHITECTURE.md
│   ├── CODE_GUIDELINES.md
│   ├── API_ROUTES_GUIDE.md
│   ├── ERROR_HANDLING.md
│   ├── NAMING_CONVENTIONS.md
│   ├── TESTING.md
│   ├── LOGGING.md
│   ├── CHECKLIST_API.md
│   ├── CHECKLIST_FEATURE.md
│   ├── CHECKLIST_MIGRATION.md
│   ├── CHECKLIST_NEW_PROVIDER.md
│   ├── DEVELOPMENT_GUIDELINES.md
│   └── coros_health_metrics.md
├── main.py                     # 7 строк: create_app() + uvicorn.run()
├── run_telegram_bot.py         # Запуск Telegram-бота (pip install -e .)
├── src/                        # Исходный код
│   ├── startup.py              # create_app() фабрика, startup-событие, роуты
│   ├── scheduler.py            # AutoSyncScheduler (threading.Event)
│   ├── models.py               # Shim: реэкспорт из src/domain/models/ + хелперы
│   ├── deps.py                 # Jinja2Templates, local_dt helper
│   ├── exceptions.py           # WatchAPIError, WatchAuthError, NotFoundError и др.
│   ├── crypto.py               # Fernet encrypt/decrypt (пароли часов, email)
│   ├── config/                 # Конфигурация
│   │   ├── __init__.py         #   Экспорт settings + constants
│   │   ├── settings.py         #   pydantic-settings BaseSettings (env vars)
│   │   └── constants.py        #   Плоские module-level константы (Final)
│   ├── domain/                 # Доменный слой
│   │   └── models/             # SQLAlchemy модели по доменам
│   │       ├── __init__.py     #   Реэкспорт всех моделей
│   │       ├── base.py         #   Base, utcnow, get_engine, SessionLocal, get_db
│   │       ├── user.py         #   User
│   │       ├── training.py     #   TrainingSession, TrainingFeedback, DeletedTraining
│   │       ├── watch.py        #   WatchCredential
│   │       ├── health.py       #   DailyMetrics, WeightMeasurement
│   │       ├── auth.py         #   AuthToken
│   │       └── audit.py        #   AuditEvent
│   ├── api/                    # FastAPI роуты и middleware
│   │   ├── __init__.py
│   │   ├── deps.py             # get_current_user dependency (session-cookie)
│   │   ├── middleware.py       # SessionMiddleware, error handlers, request logging
│   │   └── routes/
│   │       ├── auth.py         # /auth/telegram, /auth/login, /auth/register, /auth/logout
│   │       └── health.py       # /health/ endpoint
│   ├── web/                    # Web UI (Jinja2)
│   │   ├── state.py            # Глобальное состояние (_pending, _sync_tasks)
│   │   ├── templates/          # 6 Jinja2-шаблонов
│   │   └── routes/
│   │       ├── __init__.py     # web_router = pages + uploads + sync + logs
│   │       ├── pages/          # Пакет: auth (48), index (240), session (191), settings (149)
│   │       ├── uploads.py      # POST /upload, /upload/confirm, /upload/confirm_deleted
│   │       ├── sync.py         # POST /sync/{brand}/run, /sync/{brand}/health
│   │       └── logs.py         # GET /logs
│   ├── services/               # Бизнес-логика по доменам
│   │   ├── audit.py            # AuditService (БД + файл)
│   │   ├── auth.py             # bcrypt hash/verify, одноразовые токены
│   │   ├── async_utils.py      # run_async_in_thread(coro)
│   │   ├── sync/               # Пакет синхронизации
│   │   │   ├── __init__.py     #   реэкспорт (run_sync_for_user и др.)
│   │   │   ├── utils.py        #   _make_client (+кэш токена), интервалы, backoff, ensure_aware_utc
│   │   │   ├── health.py       #   sync_health_for_user (db от вызывающего; -1 = ошибка)
│   │   │   ├── activities.py   #   sync_activities_for_user (db от вызывающего; -1 = ошибка)
│   │   │   ├── dedup.py        #   дедуп: external_activity_id first, окно ±120с — legacy fallback
│   │   │   └── orchestrator.py #   run_sync_for_user, _auto_sync, счётчики сбоев + notify
│   │   ├── sync_service.py     # Shim: DeprecationWarning (обратная совместимость)
│   │   ├── watch_credentials.py# upsert_watch_credential (шифрование + upsert)
│   │   ├── training_service.py # delete_training (переносит external_activity_id), upsert_feedback
│   │   ├── reanalyze.py        # Пересчёт: сначала сырой FIT/TCX (raw_file_path), fallback trackpoints_json
│   │   ├── raw_files.py        # Хранилище исходных FIT/TCX: uploads/raw/<user_id>/<sha256>.<ext>
│   │   ├── weight_service.py   # save_weight (одна транзакция), current_weight (последнее измерение)
│   │   ├── stats.py            # calc_stats, fmt_duration, zone_ranges, get_zone_bars_data
│   │   ├── recovery_view.py    # hrv_status, readiness_label и structured-версии; пороги — из coach/config
│   │   ├── telegram_notify.py  # Отправка уведомлений в Telegram
│   │   ├── repositories.py     # TrainingRepository/HealthRepository/FeedbackRepository (db — обязательный kwarg)
│   │   ├── analytics_helpers.py# compute_slope, compute_ewma, compute_moving_average
│   │   └── user_service.py     # get_user_settings(db, ...) — сессию владеет вызывающий код
│   ├── coach/                  # Модуль аналитики и коучинга (Этап 0 — каркас, логика в заглушках)
│   │   ├── config.py           # ЕДИНСТВЕННЫЙ исполняемый источник порогов (зеркалит docs/coros_health_metrics.md)
│   │   ├── contracts.py        # SkillResult, AthleteState, Prescription, ReasoningStep
│   │   ├── state.py/engine.py/prescriber.py/orchestrator.py  # заглушки (NotImplementedError)
│   │   └── skills/, rules/, personalization/, knowledge/, llm/  # заглушки Этапа 0
│   ├── telegram/               # Пакет Telegram-бота (17 файлов)
│   │   ├── __init__.py         #   экспорт run_bot
│   │   ├── main.py             #   run_bot, Application сборка
│   │   ├── config.py           #   Константы состояний (EMAIL, PASSWORD, NEW_PASSWORD)
│   │   ├── state.py            #   _awaiting_weight
│   │   ├── utils.py            #   get_user, _get_web_app_url
│   │   ├── sync_runner.py      #   run_sync_in_thread
│   │   ├── handlers/           #   start, sync, stats, trainings, weight, account, feedback
│   │   └── jobs/               #   weight, recovery
│   ├── watch/                  # Мульти-брендовая абстракция часов
│   │   ├── __init__.py         #   register("coros", CorosWatchClient)
│   │   ├── base.py             #   BaseWatchClient(ABC)
│   │   ├── coros.py            #   CorosWatchClient (httpx.AsyncClient)
│   │   └── factory.py          #   register, get_watch_client, list_brands
│   ├── parsers/                # Парсеры файлов
│   │   ├── __init__.py
│   │   ├── gps.py              # clean_trackpoints, haversine_m
│   │   ├── weather.py          # fetch_weather (Open-Meteo, httpx)
│   │   ├── tcx_parser.py       # Парсинг TCX (XML)
│   │   └── fit_parser.py       # Парсинг FIT (бинарный, check_crc)
│   ├── analysis/               # Пакет анализа тренировок
│   │   ├── __init__.py         #   process_trackpoints() — оркестратор
│   │   ├── oscillation.py      #   detect_pace_oscillations, compute_hr_lag_correlation
│   │   ├── classify.py         #   classify_training (interval/tempo/long/recovery/easy)
│   │   ├── segment.py          #   segment_by_pace, build_time_in_zones
│   │   ├── segment_km.py       #   km_segment_fallback, compute_km_variability
│   │   ├── hr_zones.py         #   get_zone, get_band
│   │   └── utils.py            #   format_pace, calc_elevation, find_timezone, rolling pace
│   └── utils/
│       ├── logger.py           # Структурированное логирование с ротацией
│       └── rate_limit.py       # In-memory rate limiter (Sprint 13)
├── tests/                      # Pytest-тесты
│   └── ...
├── uploads/                    # Загруженные файлы (.tcx, .fit); volume смонтирован в app И bot
│   ├── pending/                # Временные файлы до подтверждения
│   └── raw/<user_id>/          # Исходные FIT/TCX: <sha256>.<ext> (content-addressed, для reanalyze)
├── screenshots/                # Скриншоты для README
├── logs/                       # Ротируемые лог-файлы
├── Dockerfile                  # Python 3.13-slim, USER appuser
├── docker-compose.yml          # 3 сервиса: db (postgres:16-alpine), app, bot
├── pyproject.toml              # Зависимости (version 2.0.0)
├── alembic.ini
├── pytest.ini
├── CHANGELOG.md
├── AGENTS.md                   # Контекст для ИИ-агента
├── BACKLOG.md                  # Парковка TODO/идей
├── PROJECT_AUDIT.md            # Аудит и план рефакторинга
├── decision_module_design.md   # Архитектура модуля аналитики
├── .env.example                # Шаблон переменных окружения
└── README.md                   # Описание проекта
```

## Правила размещения кода

### Где писать новый код?

| Что делаешь | Куда класть | Пример |
|-------------|-------------|--------|
| Новый API endpoint | `src/api/routes/<domain>.py` | `src/api/routes/auth.py` |
| Бизнес-логика | `src/services/<domain>/` | `src/services/sync/orchestrator.py` |
| SQLAlchemy модель | `src/domain/models/<domain>.py` | `src/domain/models/user.py` |
| Новая константа | `src/config/constants.py` | `DEFAULT_PACE_THRESHOLD` |
| Настройка из env | `src/config/settings.py` | `class Settings(BaseSettings)` |
| Новое исключение | `src/exceptions.py` | `class WatchAPIError` |
| Утилита общего назначения | `src/utils/` | `src/utils/logger.py` |
| Тест | `tests/` | `tests/test_analysis.py` |
| Миграция БД | `alembic/versions/` | `f7g8h9i0j1k2_data_integrity.py` |
| Документация | `docs/` | `docs/CHECKLIST_NEW_PROVIDER.md` |

### Принцип тонких роутов

**API endpoint должен быть коротким:**

```python
# src/api/routes/auth.py — ПРАВИЛЬНО
@router.post("/login")
async def login(data: LoginRequest, db: Session = Depends(get_db)):
    """Вход по email+пароль (Login with email+password)"""
    service = AuthService(db)
    token = await service.login(data.email, data.password)
    return {"token": token}
```

**Неправильно** — весь SQL, парсинг и бизнес-логика внутри роута.

### Принцип DRY

Перед созданием нового файла/функции спроси себя:

1. Существует ли похожая функция?
2. Можно ли параметризовать существующую?
3. Эта логика используется больше чем в одном месте?

Если ответ "да" хотя бы на один вопрос — не создавай дубликат.

### Размер файла

- **Максимум ~400 строк.** Если больше — разбивай на модули.
- **Роут — максимум ~80 строк.** Если больше — логика уходит в сервис.

### Владение БД-сессией (Session ownership — Этап 6 ремедиации, 05.08.2026)

- **`SessionLocal()` — только в композиционных корнях** (web `Depends(get_db)`, telegram-хендлеры/джобы,
  `startup.py`, sync-оркестратор, `telegram_notify`). Список зафиксирован тестом-гвардом
  `tests/test_session_ownership.py` — новый вызов вне списка валит CI.
- Сервисы (`user_service`, `repositories`, `weight_service`, sync-функции) **получают `db` параметром**
  и не открывают/не закрывают свои сессии.
- Канонический `get_db` — один: `src/domain/models/base.py` (в `api/deps.py` — re-export).
- ⚠️ Объекты из `telegram/utils.get_user()` — **detached**: читать можно, мутировать НЕЛЬЗЯ
  (изменения не персистятся — этот класс багов уже стрелял дважды, см. BACKLOG #236).

### Контракты синхронизации (Sync contracts — Этап 2 ремедиации)

- Возврат sync-функций: `>= 0` — успех (оркестратор двигает `last_*_sync_at`),
  **`-1` — ошибка (таймстемп НЕ двигается — иначе пропущенные данные теряются навсегда)**.
- Подряд идущие сбои копятся в `watch_credentials.{activity,health}_sync_failures` (в БД —
  синкают два процесса); на 3-м — telegram-уведомление; интервал растёт экспоненциально (backoff).
- Дедуп активностей: primary — `external_activity_id` (частичный UNIQUE в БД),
  окно ±120с — только fallback для legacy-строк без ID (`src/services/sync/dedup.py`).
- Пороги коуча/readiness — **только** из `src/coach/config.py` (анти-дрейф-тесты сверяют).

### Legacy-код

Все legacy-файлы (`src/logger.py`, `src/telegram_bot.py`, `src/database.py`) удалены.
Старые shim-файлы (`src/models.py`, `src/services/sync_service.py`) поддерживаются для обратной совместимости, новый код в них не добавлять.

## Потоки данных (Data flow)

### Загрузка тренировки через веб

```
POST /upload (TCX/FIT файл)
  ↓
src/web/routes/uploads.py (валидация размера, парсинг)
  ↓
tcx_parser.py / fit_parser.py → trackpoints
  ↓
src/analysis/__init__.py :: process_trackpoints()
  ├── gps.py: clean_trackpoints (очистка GPS-скачков)
  ├── segment.py: build_time_in_zones + segment_by_pace
  ├── oscillation.py: detect_pace_oscillations + HR-lag
  ├── classify.py: classify_training (interval/tempo/long/recovery/easy)
  ├── segment_km.py: km_segment_fallback, compute_km_variability
  └── weather.py: fetch_weather, get_temp_at_time
  ↓
ORM → PostgreSQL (training_sessions)
  ↓
Уведомление в Telegram (telegram_notify.py)
```

### Автосинхронизация с часами (Coros)

```
AutoSyncScheduler (threading.Event, per-user интервалы)
  ↓
src/services/sync/orchestrator.py :: run_sync_for_user()
  ├── factory.get_watch_client("coros", email, password)
  ├── authenticate()
  ├── list_activities(since=last_sync) → download FIT
  ├── fit_parser.py → process_trackpoints()
  └── save → PostgreSQL
  ↓
Уведомление в Telegram с inline-оценкой 0-10
```

### Telegram-бот

```
python-telegram-bot (отдельный Docker-контейнер `bot`)
  ↓
src/telegram/main.py :: run_bot()
  ├── /start → регистрация (email + пароль часов)
  ├── /sync → синхронизация (sync_runner.py → asyncio.run)
  ├── /stats → статистика
  ├── /trainings → последние 5 тренировок
  ├── /weight → ручной ввод веса
  └── jobs/ → daily_weight_job, daily_recovery_check_job
```

## Важные ограничения

- **Multi-user:** полноценная аутентификация (email+пароль, bcrypt, session-cookie)
- **PostgreSQL 16:** только TIMESTAMPTZ для datetime, миграции через Alembic
- **Telegram bot:** отдельный контейнер, не фоновый поток
- **Docker:** `USER appuser`, порт db не наружу, healthcheck
- **Мульти-бренд:** `BaseWatchClient` ABC + `factory.py` реестр (сейчас Coros, легко добавить Polar/Garmin)

---

**Последнее обновление:** 05.08.2026 (ремедиация фундамента: этапы 0–6, session ownership, дедуп, сырые файлы)
