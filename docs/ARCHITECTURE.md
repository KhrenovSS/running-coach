# Архитектура проекта (Project Architecture)

> Где размещать код? Как организован проект? Читай перед созданием новых файлов.

## Текущий стек (Current stack)

- **Backend:** Python 3.12+ (прод — `python:3.13-slim`), FastAPI
- **База данных:** PostgreSQL 16 + SQLAlchemy ORM
- **Миграции:** Alembic (автоматически при старте контейнера `app`)
- **Тесты:** pytest (SQLite in-memory по умолчанию; opt-in PG через TEST_PG_URL)
- **Логирование:** структурированное, ежедневная ротация (`TimedRotatingFileHandler`), JSON/text
- **Frontend:** Jinja2 templates + Chart.js (vanilla JS)
- **Docker:** Docker Compose — 3 контейнера (`db`, `app`, `bot`); на хосте — systemd-юнит
  `running-coach-llm-bridge.service` (LLM-мост коуча, :8765)
- **Аутентификация:** bcrypt + session-cookie (`SessionMiddleware`)
- **Шифрование:** Fernet (пароли часов, email)

## Структура проекта (Project structure)

```
running-coach/
├── alembic/                    # Миграции Alembic
│   ├── versions/               # Файлы миграций
│   └── env.py                  # Конфигурация Alembic
├── bin/                        # Ops-скрипты и рантайм-компоненты хоста
│   ├── docker.sh               # Защищённая обёртка docker compose (700, вне git — создать вручную)
│   ├── backup_db.sh            # Бэкап БД (обязателен перед деплоем)
│   ├── backfill_*.py           # Разовые backfill-скрипты (external_ids, raw_fits, avg_pace; --dry-run по умолчанию)
│   ├── distill_books.py        # Дистилляция книг → guides (E1; читает books/, пишет books/_distilled)
│   ├── coach_llm_bridge.py     # НЕ backfill — рантайм прода: LLM-мост коуча (systemd :8765, /complete + /vision)
│   └── sudoers-bridge-restart + install_bridge_sudoers.sh  # рестарт моста агентом без пароля (ставится под root один раз)
├── docs/                       # Документация — индекс: таблица в CLAUDE.md;
│   ├── coach/                  #   DEV_PLAN (норматив), ARCHITECTURE (ADR), METRICS_GUIDE, TASK_*, DESIGN_*
│   └── archive/                #   исторические документы, не ведутся (см. archive/README.md)
├── main.py                     # 7 строк: create_app() + uvicorn.run()
├── run_telegram_bot.py         # Запуск Telegram-бота (pip install -e .)
├── src/                        # Исходный код
│   ├── startup.py              # create_app() фабрика, startup-событие, роуты
│   ├── scheduler.py            # AutoSyncScheduler (threading.Event)
│   ├── models.py               # Shim: реэкспорт из src/domain/models/ + хелперы
│   ├── deps.py                 # Jinja2Templates, local_dt helper
│   ├── exceptions.py           # WatchAPIError, NotFoundError…; CoachError → LLMUnavailableError/ToolExecutionError
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
│   │       ├── training.py     #   TrainingSession, TrainingFeedback, DeletedTraining; + gps_quality/laps_json/device_summary (JSON, аддитивные)
│   │       ├── watch.py        #   WatchCredential
│   │       ├── health.py       #   DailyMetrics, WeightMeasurement, WellnessReport
│   │       ├── coach.py        #   Recommendation, PredictionLog, UserModel, Lesson, CoachMessage, WorkoutInsight
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
│   │       ├── pages/          # Пакет: auth (48), index (242), session (213), settings (149)
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
│   │   ├── repositories_coach.py # CoachRepository: выборки для скиллов/state, честный ACWR, coach_messages
│   │   ├── hr_max.py           # Адаптивный max_hr (авто-повышение по пикам, предложение снижения)
│   │   ├── user_service.py     # get_user_settings(db, ...) — сессию владеет вызывающий код
│   │   ├── workout_insights.py # Разбор тренировки: computed_json (insights v7) из session_metrics/effort/gap/…
│   │   ├── insights_baseline.py# Базовая линия HR↔GAP-темп и ожидаемый темп на пульсе (окно 120 дн)
│   │   ├── repositories_insights.py # InsightRepository: очередь разборов (claim/finish), флаги для safety
│   │   ├── prediction_log.py   # Продюсер residuals прогноз↔факт (идемпотентно по session_id; #246)
│   │   └── sleep_ingest.py     # Сон из скриншота: vision → DailyMetrics.sleep_*
│   ├── coach/                  # Гибридный ИИ-коуч (в проде). Карта модулей и ADR — docs/coach/ARCHITECTURE.md;
│   │                           #   config.py — единственный исполняемый источник порогов; knowledge/guides/*.md —
│   │                           #   runtime-данные (loader + тесты), не документация
│   ├── telegram/               # Пакет Telegram-бота
│   │   ├── __init__.py         #   экспорт run_bot
│   │   ├── main.py             #   run_bot, Application сборка
│   │   ├── config.py           #   Константы состояний (EMAIL, PASSWORD, NEW_PASSWORD)
│   │   ├── state.py            #   _awaiting_weight
│   │   ├── utils.py            #   get_user, _get_web_app_url
│   │   ├── sync_runner.py      #   run_sync_in_thread
│   │   ├── handlers/           #   start, sync, stats, trainings, weight, account, feedback,
│   │   │                       #   coach (/verdict, /coach_settings, роутер текста), pain, hr_max, sleep_photo
│   │   └── jobs/               #   weight, recovery, hr_max, coach_morning (09:30), coach_evening (21:00),
│   │                           #   coach_weekly (вс 19:00), coach_review (pending-разборы), sleep_reminder (10:00)
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
│   ├── analysis/               # Пакет анализа тренировок (15 модулей)
│   │   ├── __init__.py         #   process_trackpoints() — оркестратор
│   │   ├── oscillation.py      #   detect_pace_oscillations, compute_hr_lag_correlation
│   │   ├── classify.py         #   classify_training (interval/tempo/long/recovery/easy)
│   │   ├── segment.py          #   segment_by_pace, build_time_in_zones
│   │   ├── segment_km.py       #   km_segment_fallback, compute_km_variability
│   │   ├── hr_zones.py         #   get_zone/get_band/zone_bounds/zone_ceiling_hr (lthr → лестница ПАНО)
│   │   ├── gap.py              #   GAP/Minetti + downhill_block
│   │   ├── effort.py           #   кардиодрейф / HR-стабильность
│   │   ├── hr_baseline.py      #   базовая линия HR↔темп
│   │   ├── session_metrics.py  #   метрики M1 разбора
│   │   ├── gps_quality.py      #   квалиметрия GPS + оценка дистанции по шагам
│   │   ├── data_checks.py      #   кросс-чеки с часами (device_mismatch, lap_check)
│   │   ├── intervals.py        #   HRR-разбор интервалов
│   │   ├── week_structure.py   #   структура недели / детренированность
│   │   └── utils.py            #   format_pace, calc_elevation, find_timezone, rolling pace
│   └── utils/
│       ├── logger.py           # Структурированное логирование с ротацией
│       ├── timeutils.py        # Хелперы времени/таймзон
│       └── rate_limit.py       # In-memory rate limiter (Sprint 13)
├── tests/                      # Pytest-тесты (без сети; зелёные без ANTHROPIC_API_KEY)
│   ├── coach/                  #   тесты коуча: safety/clamp, tools, agent, мост, промпт-стабильность
│   ├── skills/                 #   фикстуры + scaffold-гейт
│   └── ...                     #   остальные (web, sync, parsers, session-гвард и т.д.)
├── uploads/                    # Загруженные файлы (.tcx, .fit); volume смонтирован в app И bot
│   ├── pending/                # Временные файлы до подтверждения
│   └── raw/<user_id>/          # Исходные FIT/TCX: <sha256>.<ext> (content-addressed, для reanalyze)
├── screenshots/                # Скриншоты для README
├── logs/                       # Ротируемые лог-файлы
├── Dockerfile                  # Python 3.13-slim, USER appuser
├── docker-compose.yml          # 3 сервиса: db, app, bot (+extra_hosts для LLM-моста)
├── running-coach-*.service     # systemd-юниты: bot, web, llm-bridge (LLM-мост коуча)
├── pyproject.toml              # Зависимости (version 2.0.0)
├── alembic.ini
├── pytest.ini
├── CHANGELOG.md
├── AGENTS.md                   # Заглушка → CLAUDE.md (конвенция инструментов)
├── BACKLOG.md                  # Открытые TODO/идеи (закрытые — docs/archive/BACKLOG_closed.md)
├── .env.example                # Шаблон переменных окружения
└── README.md                   # Описание проекта
```

## Правила размещения кода

### Где писать новый код?

| Что делаешь | Куда класть | Пример |
|-------------|-------------|--------|
| Новый API endpoint | `src/api/routes/<domain>.py` | `src/api/routes/auth.py` |
| Бизнес-логика | `src/services/<module>.py` (плоские модули; пакет — только `sync/`) | `src/services/training_service.py` |
| SQLAlchemy модель | `src/domain/models/<domain>.py` | `src/domain/models/user.py` |
| Новая константа | `src/config/constants.py` | `DEFAULT_PACE_THRESHOLD` |
| Настройка из env | `src/config/settings.py` | `class Settings(BaseSettings)` |
| Новое исключение | `src/exceptions.py` | `class WatchAPIError` |
| Утилита общего назначения | `src/utils/` | `src/utils/logger.py` |
| Тест | `tests/` | `tests/test_analysis.py` |
| Миграция БД | `alembic/versions/` | `f7g8h9i0j1k2_data_integrity.py` |
| Документация | `docs/` | `docs/CHECKLIST_NEW_PROVIDER.md` |

### Принцип тонких роутов

Роут: валидация → вызов сервиса → ответ. Приложение — Jinja2-формы (`Form(...)`), не JSON-REST:
Pydantic-моделей в роутах нет, `response_model`/`@router.delete` не используются (удаление —
`POST /session/{id}/delete`). Пример реального роута — `src/web/routes/pages/session.py`
(`session_delete` → `training_service.delete_training(db, user_id, session_id) -> bool`).
Сервисы — функции модульного уровня (например, `src/services/auth.py::authenticate_user`);
единственный класс-сервис — `AuditService`.

Подключение роутеров (`src/startup.py::create_app`): `health_router`, `auth_router`, `web_router`;
`web_router` собирается в `src/web/routes/__init__.py` из `pages`, `uploads`, `sync`, `logs`.
Полный список эндпоинтов — по `@router.` в `src/api/routes/` и `src/web/routes/`.

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

### Отклонённые архитектурные предложения (внешний аудит, 07.2026)

Из `docs/archive/PROJECT_AUDIT_2026-07.md` §3 — чтобы не пересматривать заново:

| Предложение | Решение | Почему |
|---|---|---|
| DDD / отдельный Domain Layer, Event System | ❌ отклонено | premature для проекта на одного пользователя; достаточно `domain/models` + сервисы-функции |
| Scheduler в отдельный процесс/контейнер | ❌ отклонено | тонкая обёртка; sync и так в двух процессах (app-scheduler + bot); открытый вопрос — BACKLOG #5/#15 |
| Изолировать COROS / парсеры | ✅ уже сделано | `BaseWatchClient` + `factory.py`; парсеры — функции над `common` |
| Батчинг уведомлений | ⏸ P2 | имеет смысл, не приоритет |
| Разбить God-object'ы (`models.py`, `sync_service.py`, `pages.py`) | ✅ сделано | `domain/models/*`, `services/sync/*`, `web/routes/pages/*` |

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
  (lthr пользователя (latest_lthr) прокидывается в process_trackpoints — зоны/классификация от ПАНО)
  ↓
src/analysis/__init__.py :: process_trackpoints()
  ├── gps.py: clean_trackpoints (очистка GPS-скачков)
  │     → квалиметрия GPS (gps_quality.raw_gps_stats → build_gps_quality;
  │       при unreliable дистанция = оценка по шагам estimate_distance_by_cadence)
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

FIT: `parse_fit` дополнительно сохраняет `laps_json` (лапы часов) и `device_summary`
(эталоны session-сообщения + паузы записи).

### Поток: разбор тренировки (insights v7)

```
sync/upload → review_flow (pending)
  ↓
services/workout_insights.compute_workout_metrics
  (session_metrics + gap/effort + hr_baseline + data_checks (device/lap check)
   + intervals (HRR) + week_structure/detraining/downhill/session_rpe)
  ↓
computed.flags → state.signals → rules/p1_safety (правила 11–14) → clamp
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
  ├── /plan → недельный план коуча; /sleep → скриншот сна (vision-мост)
  ├── jobs/ → daily_weight_job, daily_recovery_check_job, weekly_max_hr_check_job
  ├── jobs/ → morning_verdict_job (09:30, вердикт коуча), evening_wellness_job (21:00, вопрос о колене)
  ├── jobs/ → coach_weekly (вс 19:00), pending_reviews (разборы), sleep_reminder (10:00)
  └── коуч: /verdict, /coach_settings; любой свободный текст → orchestrator.handle_chat
      (LLM через get_llm: ключ → мост подписки → детерминированный fallback)
```

## Важные ограничения

- **Multi-user:** полноценная аутентификация (email+пароль, bcrypt, session-cookie)
- **PostgreSQL 16:** только TIMESTAMPTZ для datetime, миграции через Alembic
- **Telegram bot:** отдельный контейнер, не фоновый поток
- **Docker:** `USER appuser`, порт db не наружу, healthcheck
- **Мульти-бренд:** `BaseWatchClient` ABC + `factory.py` реестр (сейчас Coros, легко добавить Polar/Garmin)

---

**Последнее обновление:** 01.09.2026 (F-серия: квалиметрия GPS, FIT v2, insights v7, зоны от LTHR)
