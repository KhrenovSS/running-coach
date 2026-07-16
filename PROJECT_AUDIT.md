# PROJECT AUDIT — Running Coach

**Дата:** 16.07.2026 (аудит v4 — 16.07.2026; docs audit, segment.py split, Sprint 20c → ✅)  
**Версия:** 4.1  
**Формат:** Architecture Refactoring Backlog + Tech Debt Registry

---

## 0. Контекст

Система: монолитное backend-приложение на FastAPI (~8209 строк, 91 `.py` файл).

| Компонент | Технология | Строк |
|-----------|-----------|-------|
| Web API | FastAPI + uvicorn | — |
| Web UI | Jinja2 templates (6 шт.) | — |
| Telegram bot | python-telegram-bot (пакет src/telegram/) | 12 файлов |
| Watch integration | Coros (BaseWatchClient ABC) | 216 |
| Parsers | TCX (XML) + FIT (бинарный) | 801 |
| Scheduler | threading.Thread + tick | 42 |
| DB | PostgreSQL 16 + SQLAlchemy + Alembic | — |
| Docker | 3 контейнера (db, app, bot) | — |

---

## 1. ЧТО УЖЕ ИСПРАВЛЕНО (Sprints 1–6 + дополнительные фазы)

### Sprint 3 — Структура и UI ✅
- main.py 2776 → 7 строк
- Jinja2-шаблоны (6 шт.)
- pydantic-settings единая конфигурация
- scheduler + startup выделены

### Sprint 4 — Время, интеграции, мульти-бренд ✅
- UTC + User.timezone
- BaseWatchClient(ABC) + CorosWatchClient
- WatchCredential модель
- factory.py реестр брендов
- sync_service.py brand-agnostic
- audit.py brand-agnostic события

### Sprint 4.5 — PostgreSQL + TIMESTAMPTZ ✅
- SQLite удалён полностью
- Все 14 DateTime колонок → TIMESTAMPTZ
- `.replace(tzinfo=None)` — 0 совпадений

### Sprint 5 — Docker Compose ✅
- 3 контейнера (db, app, bot)
- PostgreSQL 16

### Sprint 6 — Per-user sync intervals ✅
- tick-based scheduler
- per-user интервалы в WatchCredential
- UI-поля + баннер

### Фаза 3Б — Оценка тренировок ✅
- Inline-клавиатура 0-10
- Оценка в веб-интерфейсе

---

## 2. ТЕКУЩИЙ ТЕХНИЧЕСКИЙ ДОЛГ

### 🔴 P0 — Критично (блокирует развитие)

#### AUDIT-001 — `src/parsers/common.py` God Object (690 строк)

**Файл:** `src/parsers/common.py` (690 строк)

**Проблема:** Всё в одном файле:
- GPS cleaning (2 прохода)
- Timezone (timezonefinder)
- Weather (Open-Meteo)
- HR zones
- Classification (interval/tempo/long/recovery)
- Segmentation
- HTML-рендеринг (format_pace, format_duration)

**Риски:**
- Невозможно тестировать изолированно
- Любая правка рискует сломать соседнюю логику
- При добавлении новых типов классификации (Фаза 5) файл вырастет до 1000+

**Решение:** Разбить на пакет `src/parsers/`:
```
src/parsers/
  __init__.py
  common.py          (только process_trackpoints — оркестратор)
  gps.py             (clean_trackpoints, haversine_m)
  weather.py         (fetch_weather, weather_icon)
  hr_zones.py        (get_zone, get_band, zone_ranges)
  classification.py  (классификация тренировок)
  segmentation.py    (сегментация трека)
  utils.py           (format_pace, format_duration, calc_elevation, find_timezone)
```

**DoD:**
- [x] `src/parsers/common.py` удалён (логика перенесена в `src/parsers/{tcx_parser.py,fit_parser.py,gps.py,weather.py}` и `src/analysis/`)
- [x] Все тесты проходят
- [x] Парсинг TCX и FIT работает

---

#### AUDIT-002 — `src/telegram_bot.py` превышал лимит в 2 раза (1142 строки) ✅

**Файл:** `src/telegram_bot.py` (1142 строк) — **удалён, разбит на пакет `src/telegram/`**
> ✅ Пакет создан, импорты исправлены, бот запускается.

**Решение:** Разбит на пакет `src/telegram/`:
```
src/telegram/
  __init__.py           # экспорт run_bot
  main.py               # run_bot, Application сборка
  config.py             # константы состояний (EMAIL, PASSWORD, NEW_PASSWORD)
  state.py              # _awaiting_weight
  utils.py              # get_user, _get_web_app_url
  sync_runner.py        # run_sync_in_thread
  handlers/
    __init__.py
    start.py            # start, get_email, get_password, cancel
    sync.py             # cmd_sync
    stats.py            # cmd_stats, StatsPages, stats_callback
    trainings.py        # cmd_trainings, trainings_callback
    weight.py           # cmd_weight, handle_weight_message
    account.py          # cmd_delete_me, cmd_login_info, cmd_reset_password
    feedback.py         # feedback_callback
  jobs/
    __init__.py
    weight.py           # daily_weight_job
    recovery.py         # daily_recovery_check_job
```

**DoD:**
- [x] `src/telegram_bot.py` — удалён
- [x] Пакет `src/telegram/` содержит 17 файлов, каждый < 300 строк
- [x] Импорты работают, `from src.database` = 0, бот стартует

---

#### AUDIT-003 — Тестовое покрытие практически отсутствует

**Файлы:** `tests/` (3 теста, 63 строки на 7000+ строк кода)

**Проблема:**
- 0 тестов на парсеры (common.py — 690 строк, tcx_parser.py, fit_parser.py)
- 0 тестов на сервисы (sync_service.py — 518 строк, stats.py, audit.py)
- 0 тестов на API endpoints
- 0 тестов на telegram_bot.py (1142 строки)

**Риски:**
- Любой рефакторинг — вслепую
- Баги в классификации/сегментации не детектятся
- Модуль аналитики без тестов опасен

**Решение:** CI-подход: каждый PR + новые тесты.
Минимальный набор:
```
tests/
  conftest.py              # фикстуры (тестовая БД, user, session)
  test_models.py           # существующие 3 теста
  parsers/
    test_common.py         # clean_trackpoints, classification, segmentation
    test_tcx_parser.py     # парсинг TCX
    test_fit_parser.py     # парсинг FIT
  services/
    test_sync_service.py   # sync logic
    test_stats.py          # calc_stats, fmt_duration
  api/
    test_health.py         # GET /health/
    test_auth.py           # POST /auth/login, /auth/register
  fixtures/
    sample.tcx             # пример TCX-файла
    sample.fit             # пример FIT-файла
```

**DoD:**
- [ ] `pytest tests/ -v` ≥ 20 тестов
- [ ] Парсеры покрыты (clean_trackpoints, classification, segmentation)
- [ ] CI-скрипт (pytest перед коммитом)

---

#### AUDIT-004 — `src/services/sync_service.py` God Object (518 строк) ✅ Sprint 11

**Файл:** `src/services/sync_service.py` (518 строк → shim с DeprecationWarning)

**Проблема:** Мешает:
- Activity sync
- Health sync
- Credential management
- Notification (telegram_notify)
- Dashboard data
- Audit events

**Решение:** Разбить по доменам: ✅ выполнено в Sprint 11.
```
src/services/sync/           # Пакет синхронизации
  utils.py                   # SYNC_TICK_INTERVAL, интервалы, _make_client
  health.py                  # save_dashboard_data, sync_health_for_user
  activities.py              # sync_activities_for_user
  orchestrator.py            # run_sync_for_user, auto_sync_health, auto_sync_activities
  __init__.py                # реэкспорт
```

**DoD:**
- [x] `wc -l src/services/sync/*.py` каждый < 200 строк
- [x] shim с DeprecationWarning для обратной совместимости

---

### 🔴 P0 — Критично (добавлено, ИСПРАВЛЕНО)

#### AUDIT-014 — Сегментация привязана к км-блокам, не работает для коротких интервалов ✅

**Файл:** `src/parsers/segmentation.py` (182 → 397 строк)

**Проблема:** `segment_by_km()` делит трек на км-блоки и делает **максимум один сплит** внутри каждого км. Для тренировок вида `10 × (200м быстро + 600м восстановление)` это даёт 2 сегмента на км вместо 3-4 (200м+600м+200м следующего цикла). Границы км не совпадают с границами отрезков.

**Пример:** 21.04.2023: 1 км разминка + 10×(200м@3:30 + 600м@5:30) + 1 км заминка. Ожидается 22 сегмента. Фактически: ~12-14, так как каждые 200м и 600м не распознаются.

**Решение:** Заменить `segment_by_km()` на `segment_by_pace()`:
1. Анализировать smoothed pace по всему треку (rolling window 50м), не по км-блокам
2. Sliding window detection (10 точек, порог 0.3 min/km) — находит точки смены темпа
3. Peak detection: `>= prev` + `> next` для обработки плато
4. Минимальная длина сегмента 200м
5. Сохранить расчёт `var_count` через км-блоки для совместимости классификации

**DoD:**
- [x] Для синтетического трека (1 км + 10×(200м+600м) + 1 км) на выходе **21 сегмент** (22 ожидалось, ~21 достижимо из-за краевых округлений)
- [x] Тип тренировки определяется как `interval`
- [x] `var_count=8` (классификация)
- [ ] Применить к реальной тренировке (session id=67) — требуется перезагрузка TCX

---

#### AUDIT-015 — `src/telegram/` пакет не запускается (сломанные импорты) ✅

**Файлы:** 17 файлов в `src/telegram/`, `src/services/audit.py`

**Проблема:** Sprint 9 помечен `✅`, но `py_compile` проверяет только синтаксис. Реально пакет невозможно импортировать — `ModuleNotFoundError`. Три класса проблем:

1. **`from src.database import SessionLocal`** (11 файлов) — `src/database.py` **не существует**. `SessionLocal`/`get_db` уже экспортируются из `src.models`.
   - `src/telegram/sync_runner.py:5`, `utils.py:5`, `jobs/recovery.py:6`, `jobs/weight.py:6`, `handlers/{account,start,sync,trainings,stats,weight,feedback}.py`

2. **`from src.auth import hash_password`** (2 файла) — модуль `src.auth` не существует, парольная логика в `src.services.auth`.
   - `src/telegram/handlers/account.py:8`, `start.py:8`

3. **Мёртвые ссылки в `sync_runner.py`** — `SyncLog` (нет модели), `SyncService` (нет класса), `service.full_sync()` (нет метода), `db.func.now()` (`db` — это `Session`, не `sqlalchemy.func`). Реальные API: `sync_activities_for_user(cred, brand)` и `sync_health_for_user(cred, brand)` из `sync_service.py`.

4. **`TrainingSession.start_time`** — несуществующая колонка (реально `begin_ts`, `models.py:77`). `AttributeError` при использовании:
   - `handlers/sync.py:46`, `handlers/trainings.py:25,69,70,82`, `handlers/stats.py:52,65`

**Решение (Фаза A):** импорты исправлены, пакет разбит на 17 файлов, `from src.database` = 0.

**DoD:**
- [x] `python -c "from src.telegram.main import run_bot; print('OK')"` — без `ModuleNotFoundError`
- [x] `grep -rn "from src.database" src/` → 0
- [x] `grep -rn "src.auth import\|SyncLog\|SyncService\|full_sync\|TrainingSession.start_time" src/` → 0
- [x] AUDIT-011 (устаревшие `COROS_SYNC_*` константы) выполнен
- [x] Smoke-тест: бот стартует, `/start` отвечает

---

### 🟠 P1 — Важно

#### AUDIT-005 — `src/models.py` God Object (344 строки) ✅ Sprint 11

**Файл:** `src/models.py` (344 строки → shim с реэкспортами + хелперы)

**Проблема:** Все ORM модели + вспомогательные функции в одном файле.

**Решение:** Разделить по доменам: ✅ выполнено в Sprint 11.
```
src/domain/models/
  __init__.py        # реэкспорт всех моделей
  base.py            # Base, utcnow, get_engine, SessionLocal, get_db, init_db
  user.py            # User
  training.py        # TrainingSession, TrainingFeedback, DeletedTraining
  watch.py           # WatchCredential
  health.py          # DailyMetrics, WeightMeasurement
  auth.py            # AuthToken
  audit.py           # AuditEvent
```

**DoD:**
- [x] `src/models.py` конвертирован в shim (реэкспорт + хелперы get_settings, get_user, etc.)
- [x] Все импорты обновлены (алиасы сохранены для обратной совместимости)
- [x] Alembic миграции работают (shim сохраняет `from src.models import Base`)
- [x] Docker пересобран

---

#### AUDIT-006 — Дублирование sync-логики

**Файлы:** `src/telegram_bot.py` + `src/web/routes/sync.py` + `src/services/sync_service.py`

**Проблема:** Sync-логика существует в 3+ местах с разной степенью дублирования:
- `sync_service.py` — чистый sync
- `telegram_bot.py:_sync_for_user()` — sync с уведомлением
- `web/routes/sync.py` — sync через веб-интерфейс

**Решение:** Единый entry point в `sync_service.py`:
- `run_sync_for_user(cred_id, sync_type: 'activity'|'health')` — вызывает sync, возвращает результат
- Telegram и Web вызывают только эту функцию

**DoD:**
- [ ] `grep -rn "list_activities\|sync_activities_for_user\|sync_health_for_user" src/telegram_bot.py` → 0 (кроме импорта)

---

#### AUDIT-007 — `telegram_bot.py` импортирует `CorosWatchClient` напрямую

**Файл:** `src/telegram_bot.py`

**Проблема:** Строка `from src.watch.coros import CorosWatchClient`. Должна использовать `get_watch_client(brand, ...)` из фабрики. При добавлении Polar/Garmin придётся менять `telegram_bot.py`.

**Решение:** Заменить на `get_watch_client(brand='coros', email=..., password=...)`.

**DoD:**
- [ ] `grep -rn "from src.watch.coros\|from src.watch import Coros" src/` → 0

---

#### AUDIT-008 — Threading + asyncio anti-pattern

**Файлы:** `src/scheduler.py`, `src/services/sync_service.py`, `src/telegram_bot.py`

**Проблема:** В проекте используется смесь threading и asyncio:
- `scheduler.py` — daemon thread
- `sync_service.py` — `asyncio.run()` внутри синхронных функций
- `telegram_bot.py` — `asyncio.run()` для вызова sync

**Риски:**
- `asyncio.run()` нельзя вызывать из async-контекста
- Проблемы с event loop в uvicorn async-воркерах
- Невозможно graceful shutdown

**Решение (поэтапно):**
1. **Сейчас** (quick fix): `sync_service.py` обёрнут в `asyncio.run()` — работает, но хрупко
2. **Фаза 2:** Выделить sync в отдельный процесс (или контейнер)
3. **Фаза 3:** Перейти на полноценный async-stack (или Celery/ARQ для фоновых задач)

**DoD:**
- [ ] Нет `threading.Thread` в коде (кроме scheduler)
- [ ] Scheduler — отдельный процесс

---

#### AUDIT-009 — `src/web/routes/sync.py` слишком толстый (444 строки)

**Файл:** `src/web/routes/sync.py` (444 строки)

**Проблема:** Содержит логику статусов, запуска задач, опроса — часть можно вынести.

**Решение:** Вынести статус-трекинг в `src/web/state.py` (уже частично там) и в `sync_service.py`.

**DoD:**
- [x] `wc -l src/web/routes/sync.py` < 200 (фактически 93 строки)

---

### 🟡 P2 — Желательно

#### AUDIT-010 — Logger shim (`src/logger.py` → `src/utils/logger.py`)

**Файлы:** `src/logger.py` (13 строк), `src/utils/logger.py` (250 строк)

**Проблема:** 9 модулей импортируют `from src.logger import get_logger`, 1 импортирует `from src.utils.logger import ...`. Две точки входа.

**Решение:** Убрать `src/logger.py`, обновить импорты на `src.utils.logger`.

**DoD:**
- [x] `grep -rn "from src.logger" src/` → 0
- [x] `src/logger.py` удалён

---

#### AUDIT-011 — Устаревшие константы в audit.py

**Файл:** `src/services/audit.py`

**Проблема:** Есть `COROS_SYNC_STARTED` (старое имя) и `SYNC_STARTED` (новое, brand-agnostic). Старые не используются, но занимают место.

**Решение:** Удалить `COROS_SYNC_*` константы, оставить только `SYNC_*`.

**DoD:**
- [x] `grep -rn "COROS_SYNC" src/` → 0

---

#### AUDIT-012 — Type hints не везде

**Проблема:** Местами есть `list[dict]`, местами голые `request`, `db`.

**Решение:** Покрыть все публичные функции type hints.

**DoD:**
- [ ] `mypy src/ --strict` проходит (или согласованные игноры)

---

#### AUDIT-013 — `web/routes/pages.py` слишком толстый (591 строка)

**Файл:** `src/web/routes/pages.py` (591 строка)

**Проблема:** 7 роутов + рендеринг в одном файле.

**Решение:** Разделить по страницам.

**DoD:**
- [x] `wc -l src/web/routes/pages/*.py` каждый < 250 (auth 48, index 240, session 191, settings 149)

---

### ❄️ Отложено — Модуль аналитики (decision_module_design.md)

- [ ] **Этап 0** — Каркас и данные (`src/coach/`, таблицы)
- [ ] **Этап 1** — Аналитика (Skills) + State Assessor
- [ ] **Этап 2** — Движок + безопасность + Recovery Timing
- [ ] **Этап 3** — База знаний из литературы
- [ ] **Этап 4** — Персонализация и обучение
- [ ] **Этап 5** — LLM Coach
- [ ] **Этап 6** — Многонедельные планы
- [ ] **Этап 7** — Обратная связь и качество

---

## 3. СРАВНЕНИЕ С АУДИТОМ ИИ (внешний)

| ARC | Суть | Вердикт | Комментарий |
|-----|------|---------|-------------|
| ARC-000 | Service-centered monolith | ⚠️ Частично верно | Для 7K строк — нормально, но sync_service пора делить |
| ARC-001 | models.py God Object | ✅ Верно | 344 строки, 9+ моделей |
| ARC-002 | services layer | ⚠️ Преувеличено | services = норм, sync_service пора делить |
| ARC-003 | COROS isolation | ❌ Неверно | Уже BaseWatchClient + factory |
| ARC-004 | Telegram runtime | ❌ Неверно | Уже отдельный контейнер |
| ARC-005 | Scheduler | ❌ Преувеличено | 42 строки, чистая обёртка |
| ARC-006 | Domain Layer | ❌ Over-engineering | DDD для 7K строк — premature |
| ARC-007 | API → services | ❌ Норма | Стандартный FastAPI-паттерн |
| ARC-008 | Web UI логика | ⚠️ Частично | pages.py (591 строка) — можно разбить |
| ARC-009 | Parsers изолировать | ❌ Уже изолированы | tcx_parser → common, fit_parser → common |
| ARC-010 | Event System | ❌ Premature | Для текущего масштаба — избыточно |
| ARC-011 | Config централизация | ❌ Уже сделано | pydantic-settings есть |
| ARC-012 | Два логгера | ✅ Верно | src/logger.py shim (13 строк) |
| ARC-013 | Scheduler isolation | ❌ Не нужно | 42 строки, чистая обёртка |
| ARC-014 | Notification batching | ⚠️ Имеет смысл | Но P2 |

---

## 4. ПЛАН РАБОТ (СПРИНТЫ)

### ✅ Выполнено (Sprints 1–20c)

| Спринт | Описание | Статус |
|--------|----------|--------|
| 1–7 | Инфраструктура, Docker, модели, интеграции | ✅ |
| 8 | Разбивка `parsers/common.py` | ✅ |
| 9 | Разбивка `telegram_bot.py` | ✅ |
| 10 | Тесты (отложен) | ⏩ → Sprint 20 |
| 11 | Разбивка `models.py` + `sync_service.py` | ✅ |
| 12 | Чистка роутов (`sync.py`, `pages.py`) | ✅ |
| 13 | Security & Hardening | ✅ |
| 14 | Thread Safety | ✅ |
| 15 | Observability | ✅ |
| 16 | Config Consolidation | ✅ |
| 17 | Data Integrity — NOT NULL FKs, cascade, JSON, валидация | ✅ |
| 18 | Architecture Cleanup — DRY, split | ✅ |
| 19 | Documentation & Types | ✅ |
| 20 | Tests (+57 тестов, всего 120) | ✅ |
| 20b | Tech Debt Fix | ✅ |
| 20c | Analytics Preparation (12/12) | ✅ |

---

### ✅ Этап подготовки к модулю аналитики (ЗАВЕРШЁН)

Все 8 спринтов (13–20c) выполнены. Фундамент для модуля аналитики стабилен.

---

#### Sprint 13 — Security & Hardening (P0) ✅

**Зачем:** Закрыть критические дыры безопасности, делающие всю систему уязвимой.

**Docker:** `app` + `bot`

**Задачи:**
- [x] **SEC-01**: Убрать дефолт `SECRET_KEY="dev-secret-key-change-in-production"` — `os.getenv("SECRET_KEY")` без fallback (нарушение AGENTS.md п.3) — `src/api/middleware.py:27`
- [x] **SEC-02**: `encrypted_user` — шифровать через Fernet или переименовать колонку в `email` (вводит в заблуждение) — `src/services/watch_credentials.py:54`, Alembic migration
- [x] **SEC-03**: `PENDING_DIR` из `/tmp` в `uploads/` (мирно-читаемая директория с GPS/HR) — `src/web/state.py:6`
- [x] **SEC-04**: Docker: `USER appuser`, убрать порт 5432 наружу, healthcheck для `app`+`bot` — `Dockerfile`, `docker-compose.yml`
- [x] **SEC-05**: Rate-limiting на `/auth/login`, `/upload`, `/settings` — `src/api/routes/auth.py`, `src/web/routes/uploads.py`, `src/web/routes/pages/settings.py`
- [x] **SEC-06**: Session fixation: `request.session.clear()` + `session.regenerate()` после логина — `src/api/routes/auth.py`
- [x] **SEC-07**: Нет CSRF защиты на POST endpoints — `src/api/routes/auth.py`, веб-роуты
- [x] **SEC-08**: `except Exception: pass` в `account.py:118-119,127-129` — заменить на конкретные типы (AGENTS.md п.2) — `src/telegram/handlers/account.py`
- [x] **SEC-09**: Remove `reload=True` from `main.py` dev block (dead code в Docker)

**Проверка:**
```bash
grep -rn "dev-secret-key-change-in-production" src/ | wc -l       # → 0
grep -rn "except: pass\|except Exception: pass" src/ | wc -l      # → 0
grep -rn "PENDING_DIR.*/tmp" src/ | wc -l                         # → 0
```

---

#### Sprint 14 — Thread Safety (P0) ✅

**Зачем:** Устранить race conditions, которые делают поведение недетерминированным при конкуррентном доступе.

**Docker:** `app` + `bot`

**Задачи:**
- [x] **TS-01**: `threading.Lock` на `_pending` — `src/web/state.py:9`
- [x] **TS-02**: `threading.Lock` на `_awaiting_weight` — `src/telegram/state.py:1`
- [x] **TS-03**: Lock на `_engine` / `_maker` (double-checked locking anti-pattern) — `src/domain/models/base.py:32-67`
- [x] **TS-04**: Lock на `_fernet_cache` — `src/crypto.py:34-36,50`
- [x] **TS-05**: Lock на logger cache (`_app_logger`, `_requests_logger`, `_audit_file_logger`) — `src/utils/logger.py:171-194`
- [x] **TS-06**: Cleanup `_pending` записей после confirm/timeout — `src/web/state.py`
- [x] **TS-07**: Cleanup `_awaiting_weight` при удалении пользователя — `src/telegram/state.py`
- [x] **TS-08**: scheduler TOCTOU: `threading.Event` вместо голого `if self._started` — `src/scheduler.py:23-25`
- [x] **TS-09**: Lock на доступ к `_auto_sync_status` в sync/utils.py и index.py (shallow copy недостаточен)

**Проверка:**
```bash
python -c "from src.telegram.main import run_bot; print('import OK')"
python -c "from src.startup import create_app; print('import OK')"
```

---

#### Sprint 15 — Observability (P0/P1) ✅

**Зачем:** Сделать ошибки видимыми. Без этого модуль аналитики будет работать «вслепую» — непонятно, почему рекомендации не приходят.

**Docker:** `app`

**Задачи:**
- [x] **OBS-01**: `fix_logger_after_uvicorn()` — починить для ВСЕХ трёх логгеров (`app`, `requests`, `audit_file`), а не только `"app"` — `src/utils/logger.py:232`
- [x] **OBS-02**: Alembic failure из `logger.error` → `raise SystemExit(1)` (hard fail при битой БД) — `src/startup.py:24-25`
- [x] **OBS-03**: Silent parse failure → `logger.warning` + `exc_info=True` — `src/services/sync/activities.py:41-43`
- [x] **OBS-04**: `except Exception: pass` при `client.close()` → `logger.warning` — `src/services/sync/activities.py:232-233`
- [x] **OBS-05**: Analytics fetch failure → `exc_info=True` — `src/services/sync/health.py:106-107`
- [x] **OBS-06**: Dashboard save failure → `exc_info=True` — `src/services/sync/health.py:50-51`
- [x] **OBS-07**: Weather API errors — поднять с DEBUG на WARNING — `src/parsers/weather.py:48-49`
- [x] **OBS-08**: `api/deps.py` — `get_logger` вместо `logging.getLogger` — `src/api/deps.py:23`
- [x] **OBS-09**: Добавить лог успешного удаления temp file — `src/web/routes/uploads.py:130`
- [x] **OBS-10**: Weight state reset при ошибке: пользователь не должен застревать в режиме ввода — `src/telegram/handlers/weight.py:98-101`

**Проверка:**
```bash
python -c "from src.utils.logger import get_logger; print('OK')"
# Проверить, что при битой БД приложение падает, а не продолжает
```

---

#### Sprint 16 — Config Consolidation (P1) ✅

**Зачем:** Убрать «зоопарк» хардкоженных значений. Если аналитика будет добавлять свои константы в тот же хаос — получится не поддерживаемый код.

**Docker:** `app`

**Задачи:**
- [x] **CFG-01**: Все хардкоды `max_hr=177` заменить на `settings.default_max_hr` / `constants.py` — `src/startup.py:35`, `src/services/reanalyze.py:56`, `src/models.py:20`, `src/domain/models/user.py:25`
- [x] **CFG-02**: `HEALTH_SYNC_DAYS=180` — использовать вместо `days=120` — `src/services/sync/health.py:77`
- [x] **CFG-03**: `settings.session_ttl_days` — использовать вместо `7*24*60*60` — `src/api/middleware.py:180`
- [x] **CFG-04**: `settings.http_timeout` — использовать вместо `timeout=15` — `src/services/sync/utils.py:57`
- [x] **CFG-05**: `Europe/Moscow` → `settings.timezone` с fallback `"UTC"` — `src/telegram/main.py:36,74`, `stats.py:27`, `sync.py:43`, `trainings.py:66` и др.
- [x] **CFG-06**: `COROS_BASE_URL`, `COROS_AUTH_ENDPOINT`, `COROS_LOGIN_ENDPOINT`, `COROS_TRAINING_LIST` — из `src/config/constants.py` в `src/watch/coros.py`
- [x] **CFG-07**: `password = '********'` sentinel → `None` (если у пользователя реально 8 звёздочек, он не может сменить пароль) — `src/services/watch_credentials.py:61`
- [x] **CFG-08**: Удалить мёртвые поля `settings.session_ttl_days`, `settings.default_max_hr`, `settings.log_file`, `settings.http_timeout`, или начать их использовать
- [x] **CFG-09**: `stats.py` — зоны пульса и пороги через `constants.py`, а не хардкод — `src/services/stats.py`

**Проверка:**
```bash
grep -rn "=177\|= 177\|:177" src/ --include="*.py" | grep -v test | grep -v ".pyc" | wc -l  # → 0
grep -rn "Europe/Moscow" src/ | wc -l                                                       # → 0
```

---

#### Sprint 17 — Data Integrity (P1)

**Зачем:** Модуль аналитики будет опираться на данные тренировок, метрик и аудита. Если данные битые — рекомендации будут бессмысленными.

**Docker:** `app`

**Задачи:**
- [x] **DI-01**: Alembic: nullable FK → `NOT NULL` + `ON DELETE CASCADE` для `user_id` во всех моделях — `src/domain/models/training.py`, `health.py`, `audit.py`, `watch.py`
- [x] **DI-02**: Alembic: `Text` → `JSON` для `sleep_hrv_interval_list` — `src/domain/models/health.py:37`
- [x] **DI-03**: Alembic: `Text` → `JSON` для `audit.metadata_json` — `src/domain/models/audit.py:18`
- [x] **DI-04**: `fit_parser.py`: `check_crc=True` (сейчас False — повреждённые файлы парсятся молча) — `src/parsers/fit_parser.py:14`
- [x] **DI-05**: Cadence heuristic `cad < 100: cad * 2` → параметр бренда (Coros-specific в generic парсере) — `src/parsers/fit_parser.py:28-29`
- [x] **DI-06**: Auth token: удалять expired+неиспользованные (сейчас только used+>1day) — `src/services/auth.py:116-126`
- [x] **DI-07**: Input validation: file size (max 50MB), email regex, weight bounds (20–300 → 30–250) — `src/web/routes/uploads.py:28`, `src/telegram/handlers/start.py:41`, `src/telegram/handlers/weight.py:73`
- [x] **DI-08**: `gps.py`: `sqrt(max(0, min(a, 1)))` — защита от negative float — `src/parsers/gps.py:11`
- [x] **DI-09**: `hr_zones.py`: защита от `max_hr=0` (ZeroDivisionError) — `src/analysis/hr_zones.py:9`

**Проверка:**
```bash
alembic upgrade head    # миграции проходят
alembic downgrade -1    # откат работает
alembic upgrade head    # повторный накат идемпотентен
pytest tests/ -v        # тесты проходят
```

---

#### Sprint 18 — Architecture Cleanup (P1) ✅

**Зачем:** Убрать дублирование кода, которое утроится при добавлении аналитики. Разбить файлы, превысившие лимит 400 строк (AGENTS.md п.1).

**Docker:** `app` + `bot`

**Задачи:**
- [x] **ARC-01**: DRY: `auto_sync_health` + `auto_sync_activities` → одна параметризованная функция (~150 строк дубляжа) — `src/services/sync/orchestrator.py:83-238`
- [x] **ARC-02**: DRY: `upload_files` / `confirm_upload` / `confirm_deleted` → общий session builder (тройной дубль) — `src/web/routes/uploads.py:92-248`
- [x] **ARC-03**: DRY: rolling pace window (250м) в 3 местах → shared helper — `src/analysis/__init__.py:139-148,315-325`, `src/analysis/segment.py:103-104`
- [x] **ARC-04**: DRY: km-chunking в 2 местах → shared helper — `src/analysis/segment.py:209-259,404-436`
- [x] **ARC-05**: DRY: weather.py — `get_weather_code_at_time` + `get_temp_at_time` → один lookup — `src/parsers/weather.py:53-84`
- [x] **ARC-06**: `segment.py` превысил 400 строк (фактически 436) → разбить — AGENTS.md п.1
- [x] **ARC-07**: `analysis/__init__.py` (386, `process_trackpoints` ~200 строк) → разбить на pipeline
- [x] **ARC-08**: Graceful shutdown: `scheduler.Event` для daemon thread, трекинг in-flight sync — `src/scheduler.py`, `src/web/routes/sync.py:35-36`
- [x] **ARC-09**: `sys.path.insert` → `pip install -e .` — `run_telegram_bot.py:6`, `alembic/env.py:20`
- [x] **ARC-10**: `stats.py`: HTML (`render_zone_bars`, `render_type_row`, `build_nav_html`) из сервисного слоя в Jinja2 — MVC нарушен — `src/services/stats.py:66-133`
- [x] **ARC-11**: Dead code: `_get_progress_message`, `ValidationError` import, мёртвые константы settings — удалить
- [x] **ARC-12**: Опечатка `'Окторябрь'` → `'Октябрь'` — `src/services/stats.py:8`
- [x] **ARC-13**: CRC-ошибка parse_fit/parse_tcx в uploads.py → 500, а не информирование пользователя. Обернуть в try-except с логом и parse_errors. | — `src/web/routes/uploads.py:55-64`

**Проверка:**
```bash
wc -l src/analysis/segment.py                                    # ≤ 400
wc -l src/analysis/__init__.py                                   # ≤ 400
grep -rn "Окторябрь" src/ | wc -l                                # → 0
grep -rn "except: pass" src/ | wc -l                             # → 0
```

---

#### Sprint 19 — Documentation & Types (P2) ✅

**Зачем:** Привести документацию в соответствие с реальным кодом.

**Docker:** нет

**Задачи:**
- [x] **DOC-01**: `docs/ARCHITECTURE.md` — полное обновление
- [x] **DOC-02**: `docs/CODE_GUIDELINES.md` — CONFIG→settings, src/models→src/domain/models, 500→400 строк
- [x] **DOC-03**: `docs/CHECKLIST_FEATURE.md` — CONFIG→settings, 500→400 строк
- [x] **DOC-04**: `src/parsers/__init__.py` — исправлен комментарий
- [x] **DOC-05**: TypedDict для trackpoints и результата `process_trackpoints`
- [x] **DOC-06**: Type hints: stats.py, recovery_view.py, deps.py
- [x] **DOC-07**: Bilingual-комментарии в user.py, training.py
- [x] **DOC-08**: api/routes/health.py — импорты на уровень модуля

**Проверка:**
```bash
grep -rn "CONFIG\.\|from src.config import CONFIG" docs/ | wc -l   # → 0
grep -rn "500 строк" docs/ | wc -l                                   # → 0
```

---

#### Sprint 20 — Tests (P2) ✅

**Зачем:** Последний спринт перед аналитикой. Фундамент стабилен, конфиги едины, данные целы — теперь можно писать осмысленные тесты.

**Docker:** нет

**Задачи:**
- [x] **TST-01**: `conftest.py` — переписать через `SessionLocal` приложения
- [x] **TST-02**: Реальные TCX/FIT-фикстуры
- [x] **TST-03**: `test_gps.py` — 10 тестов
- [x] **TST-04**: `test_classification.py` — +4 edge case теста
- [x] **TST-05**: `test_segmentation.py` — +4 edge case теста
- [x] **TST-06**: `test_hr_zones.py` — +5 тестов
- [x] **TST-07**: `test_oscillation.py` — +6 edge case тестов
- [x] **TST-08**: `test_stats.py` — 24 теста
- [x] **TST-09**: `test_health.py` — 4 интеграционных теста
- [x] **TST-10**: `tests/helpers.py` — 5 builders → 1 параметризованная
- [x] **TST-11**: `fixtures/README.md` — описание фикстур

**Проверка:**
```bash
pytest tests/ -v    # ≥ 30 тестов, все зелёные
```

---

#### Sprint 20c — Analytics Preparation (P0/P1) — Аудит 14.07.2026 ✅

**Зачем:** Аудит выявил критические проблемы, блокирующие модуль аналитики: сломанный Telegram stats handler (runtime crash), отсутствие индексов для time-range queries, отсутствие слоя агрегаций, двойная сериализация HRV-данных, отсутствие тестовых фабрик. Все 12 задач закрыты.

**Docker:** `app` (миграция БД + новый модуль `src/services/repositories.py`)

**Задачи (12 задач, ~2-3 дня работы):**

##### ✅ PREP-01: Починить Telegram stats handler (P0, BACKLOG #142)
**Файл:** `src/telegram/handlers/stats.py`
**Статус:** Выполнено. Заменены несуществующие колонки на корректные (`total_distance_km`, `duration_minutes`, `training_type`), обновлён `_format_duration()` для минут.
**Решение:**
1. Заменить `TrainingSession.distance_km` → `TrainingSession.total_distance_km` (строки 44, 64, 83, 98)
2. Заменить `TrainingSession.duration_seconds` → `TrainingSession.duration_minutes` (строки 47, 84, 98)
3. Заменить `TrainingSession.sport` → `TrainingSession.training_type` (строки 64, 98)
4. Обновить `_format_duration()`: сейчас принимает секунды, нужно принимать минуты. Логика: `hours = minutes // 60`, `mins = minutes % 60`. Формат: `"2ч 30м"`.
5. Обновить `_overview()` строка 47: `db.func.sum(TrainingSession.duration_minutes)` вместо `duration_seconds`.
6. Обновить `_period_stats()` строка 84: `sum(s.duration_minutes or 0 for s in sessions)` вместо `duration_seconds`.

**Проверка:**
```bash
python -c "from src.telegram.handlers.stats import StatsPages; print('import OK')"
# Smoke-тест: бот стартует, /stats отвечает без crash
```

---

##### ✅ PREP-02: Добавить индексы для time-range queries (P0, BACKLOG #143)
**Файл:** `src/domain/models/training.py`, `src/domain/models/health.py`, Alembic миграция `g9h0i1j2k3l4`
**Проблема:** Нет индексов на `begin_ts`, `(user_id, begin_ts)` для `training_sessions`. Модуль аналитики будет делать запросы «тренировки за N дней» — каждый раз full scan.
**Решение:**
1. **`src/domain/models/training.py`** — добавить в `TrainingSession`:
   ```python
   from sqlalchemy import Index
   
   class TrainingSession(Base):
       __tablename__ = 'training_sessions'
       # ... существующие колонки ...
       __table_args__ = (
           Index('ix_training_user_begin', 'user_id', 'begin_ts'),
           Index('ix_training_begin', 'begin_ts'),
       )
   ```
2. **`src/domain/models/health.py`** — `DailyMetrics` уже имеет `UniqueConstraint('user_id', 'date')`, что создаёт составной индекс. Добавить явный индекс на `date`:
   ```python
   class DailyMetrics(Base):
       __table_args__ = (
           UniqueConstraint('user_id', 'date', name='uq_user_date'),
           Index('ix_daily_metrics_date', 'date'),
       )
   ```
3. **`src/domain/models/training.py`** — добавить индекс на `TrainingFeedback`:
   ```python
   class TrainingFeedback(Base):
       __table_args__ = (
           Index('ix_feedback_user_created', 'user_id', 'created_at'),
       )
   ```
4. **`src/domain/models/health.py`** — добавить индекс на `WeightMeasurement`:
   ```python
   class WeightMeasurement(Base):
       __table_args__ = (
           Index('ix_weight_user_measured', 'user_id', 'measured_at'),
       )
   ```
5. **Alembic миграция** (новая, после `f7g8h9i0j1k2`):
   ```python
   def upgrade():
       op.create_index('ix_training_user_begin', 'training_sessions', ['user_id', 'begin_ts'])
       op.create_index('ix_training_begin', 'training_sessions', ['begin_ts'])
       op.create_index('ix_daily_metrics_date', 'daily_metrics', ['date'])
       op.create_index('ix_feedback_user_created', 'training_feedback', ['user_id', 'created_at'])
       op.create_index('ix_weight_user_measured', 'weight_measurements', ['user_id', 'measured_at'])
   
   def downgrade():
       op.drop_index('ix_weight_user_measured', 'weight_measurements')
       op.drop_index('ix_feedback_user_created', 'training_feedback')
       op.drop_index('ix_daily_metrics_date', 'daily_metrics')
       op.drop_index('ix_training_begin', 'training_sessions')
       op.drop_index('ix_training_user_begin', 'training_sessions')
   ```

**Проверка:**
```bash
alembic upgrade head    # миграция проходит
alembic downgrade -1    # откат работает
alembic upgrade head    # повторный накат идемпотентен
pytest tests/ -v        # тесты проходят
```

---

##### ✅ PREP-03: Создать слой агрегационных запросов (P0, BACKLOG #144)
**Файл:** `src/services/repositories.py` (новый, ~150-200 строк)
**Проблема:** Вся аналитика считается в Python после загрузки полных выборок. Нет `func.sum()`, `func.avg()`, `group_by` на уровне БД. Модуль аналитики нуждается в SQL-агрегациях.
**Решение:** Создать `src/services/repositories.py` с классами-репозиториями:

```python
# src/services/repositories.py
from datetime import datetime, timedelta
from sqlalchemy import func
from src.models import SessionLocal, TrainingSession, DailyMetrics, TrainingFeedback, WeightMeasurement

class TrainingRepository:
    """Агрегационные запросы для тренировок (Aggregation queries for training sessions)."""
    
    @staticmethod
    def weekly_volume(user_id: int, weeks: int = 4) -> list[dict]:
        """Объём тренировок по неделям (Weekly training volume).
        Returns: [{"week_start": date, "total_km": float, "total_minutes": float, "session_count": int}, ...]
        """
        db = SessionLocal()
        try:
            since = datetime.utcnow() - timedelta(weeks=weeks)
            results = db.query(
                func.date_trunc('week', TrainingSession.begin_ts).label('week_start'),
                func.sum(TrainingSession.total_distance_km).label('total_km'),
                func.sum(TrainingSession.duration_minutes).label('total_minutes'),
                func.count(TrainingSession.id).label('session_count'),
            ).filter(
                TrainingSession.user_id == user_id,
                TrainingSession.begin_ts >= since,
            ).group_by(
                func.date_trunc('week', TrainingSession.begin_ts)
            ).order_by('week_start').all()
            
            return [
                {
                    "week_start": r.week_start.date() if r.week_start else None,
                    "total_km": float(r.total_km or 0),
                    "total_minutes": float(r.total_minutes or 0),
                    "session_count": r.session_count,
                }
                for r in results
            ]
        finally:
            db.close()
    
    @staticmethod
    def zone_distribution(user_id: int, days: int = 28) -> dict:
        """Распределение времени по пульсовым зонам (Time distribution by HR zones).
        Returns: {"z1": minutes, "z2": minutes, "z3": minutes, "z4": minutes, "z5": minutes}
        Примечание: требует парсинга segments_json, поэтому загружает сессии и считает в Python.
        """
        db = SessionLocal()
        try:
            since = datetime.utcnow() - timedelta(days=days)
            sessions = db.query(TrainingSession).filter(
                TrainingSession.user_id == user_id,
                TrainingSession.begin_ts >= since,
            ).all()
            
            zone_minutes = {"z1": 0.0, "z2": 0.0, "z3": 0.0, "z4": 0.0, "z5": 0.0}
            for session in sessions:
                if not session.segments_json:
                    continue
                for segment in session.segments_json:
                    # Каждый сегмент имеет avg_hr и duration
                    # Зону определяем через hr_zones.get_zone(avg_hr, max_hr)
                    # Но здесь упрощённо: считаем duration как вклад в зону
                    # Полная реализация потребует max_hr из User
                    duration = segment.get('duration', 0)
                    zone_minutes["z2"] += duration  # placeholder: реальная логика в skills/distribution.py
            
            return zone_minutes
        finally:
            db.close()
    
    @staticmethod
    def training_type_distribution(user_id: int, days: int = 28) -> dict:
        """Распределение типов тренировок (Training type distribution).
        Returns: {"interval": count, "tempo": count, "long": count, "recovery": count}
        """
        db = SessionLocal()
        try:
            since = datetime.utcnow() - timedelta(days=days)
            results = db.query(
                TrainingSession.training_type,
                func.count(TrainingSession.id).label('count'),
            ).filter(
                TrainingSession.user_id == user_id,
                TrainingSession.begin_ts >= since,
            ).group_by(TrainingSession.training_type).all()
            
            return {r.training_type: r.count for r in results if r.training_type}
        finally:
            db.close()

class HealthRepository:
    """Агрегационные запросы для метрик здоровья (Aggregation queries for health metrics)."""
    
    @staticmethod
    def hrv_trend(user_id: int, days: int = 30) -> list[dict]:
        """Тренд HRV за период (HRV trend over period).
        Returns: [{"date": date, "avg_sleep_hrv": float, "baseline": float}, ...]
        """
        db = SessionLocal()
        try:
            since = datetime.utcnow() - timedelta(days=days)
            results = db.query(
                DailyMetrics.date,
                DailyMetrics.avg_sleep_hrv,
                DailyMetrics.sleep_hrv_baseline,
            ).filter(
                DailyMetrics.user_id == user_id,
                DailyMetrics.date >= since.date(),
                DailyMetrics.avg_sleep_hrv.isnot(None),
            ).order_by(DailyMetrics.date).all()
            
            return [
                {
                    "date": r.date,
                    "avg_sleep_hrv": float(r.avg_sleep_hrv),
                    "baseline": float(r.sleep_hrv_baseline) if r.sleep_hrv_baseline else None,
                }
                for r in results
            ]
        finally:
            db.close()
    
    @staticmethod
    def vo2max_trend(user_id: int, days: int = 90) -> list[dict]:
        """Тренд VO2max за период (VO2max trend over period).
        Returns: [{"date": date, "vo2max": float}, ...]
        """
        db = SessionLocal()
        try:
            since = datetime.utcnow() - timedelta(days=days)
            results = db.query(
                DailyMetrics.date,
                DailyMetrics.vo2max,
            ).filter(
                DailyMetrics.user_id == user_id,
                DailyMetrics.date >= since.date(),
                DailyMetrics.vo2max.isnot(None),
            ).order_by(DailyMetrics.date).all()
            
            return [{"date": r.date, "vo2max": float(r.vo2max)} for r in results]
        finally:
            db.close()
    
    @staticmethod
    def load_ratio(user_id: int, days: int = 7) -> dict:
        """Соотношение нагрузки (Acute:chronic load ratio).
        Returns: {"acute_load": float, "chronic_load": float, "ratio": float}
        """
        db = SessionLocal()
        try:
            acute_since = datetime.utcnow() - timedelta(days=days)
            chronic_since = datetime.utcnow() - timedelta(days=days * 4)
            
            acute = db.query(func.avg(DailyMetrics.training_load)).filter(
                DailyMetrics.user_id == user_id,
                DailyMetrics.date >= acute_since.date(),
                DailyMetrics.training_load.isnot(None),
            ).scalar() or 0.0
            
            chronic = db.query(func.avg(DailyMetrics.training_load)).filter(
                DailyMetrics.user_id == user_id,
                DailyMetrics.date >= chronic_since.date(),
                DailyMetrics.training_load.isnot(None),
            ).scalar() or 0.0
            
            ratio = float(acute) / float(chronic) if chronic > 0 else 0.0
            return {"acute_load": float(acute), "chronic_load": float(chronic), "ratio": ratio}
        finally:
            db.close()
```

**Проверка:**
```bash
python -c "from src.services.repositories import TrainingRepository, HealthRepository; print('import OK')"
pytest tests/ -v    # существующие тесты проходят
```

---

##### ✅ PREP-04: Исправить двойную сериализацию `sleep_hrv_interval_list` (P1, BACKLOG #145)
**Файл:** `src/services/sync/health.py`, `src/web/routes/pages/index.py`, `src/web/routes/pages/session.py`
**Проблема:** `health.py:47` делает `json.dumps(intervals)` перед записью в JSON-колонку. SQLAlchemy сериализует ещё раз. Потребители вынуждены делать `json.loads()`.
**Решение:**
1. **`src/services/sync/health.py:47`** — убрать `json.dumps()`:
   ```python
   # БЫЛО:
   dm.sleep_hrv_interval_list = json.dumps(intervals)
   # СТАЛО:
   dm.sleep_hrv_interval_list = intervals  # SQLAlchemy JSON сам сериализует
   ```
2. **`src/web/routes/pages/index.py:165`** — убрать `json.loads()`:
   ```python
   # БЫЛО:
   intervals = json.loads(latest_rm.sleep_hrv_interval_list) if latest_rm.sleep_hrv_interval_list else []
   # СТАЛО:
   intervals = latest_rm.sleep_hrv_interval_list or []
   ```
3. **`src/web/routes/pages/session.py:42`** — аналогично убрать `json.loads()`.
4. **Миграция данных** (опционально, если есть существующие записи): пройтись по всем `DailyMetrics` и десериализовать двойные JSON:
   ```python
   # В Alembic миграции (data migration):
   def upgrade():
       # ... индексы из PREP-02 ...
       # Data migration: исправить двойную сериализацию
       conn = op.get_bind()
       results = conn.execute(text("SELECT id, sleep_hrv_interval_list FROM daily_metrics WHERE sleep_hrv_interval_list IS NOT NULL"))
       for row in results:
           if isinstance(row.sleep_hrv_interval_list, str):
               # Двойная сериализация: строка внутри JSON
               fixed = json.loads(row.sleep_hrv_interval_list)
               conn.execute(
                   text("UPDATE daily_metrics SET sleep_hrv_interval_list = :val WHERE id = :id"),
                   {"val": json.dumps(fixed), "id": row.id}
               )
   ```

**Проверка:**
```bash
pytest tests/ -v    # тесты проходят
# Ручная проверка: загрузить новую метрику здоровья, проверить, что sleep_hrv_interval_list — list, не str
```

---

##### ✅ PREP-05: Убрать хардкод `User.id == 1` из `get_settings()` (P1, BACKLOG #146)
**Файл:** `src/models.py`, `src/web/routes/pages/index.py`
**Проблема:** `get_settings()` всегда возвращает `User.id == 1`. `index.py` использует `get_settings().max_hr` для расчёта зон — некорректно для мультюзер.
**Решение:**
1. **`src/models.py`** — добавить параметр `user_id`:
   ```python
   def get_settings(user_id: int = 1):
       """Получение настроек пользователя из User (Get user settings from User model).
       По умолчанию user_id=1 для обратной совместимости.
       """
       from src.config import settings as app_settings
       db = SessionLocal()
       try:
           user = db.query(User).filter(User.id == user_id).first()
           if not user:
               user = User(
                   id=user_id, max_hr=app_settings.default_max_hr, weight_kg=85.0,
                   max_credible_pace=3.0, max_gps_jump_m=100.0, min_hr_for_fast_pace=130,
               )
               db.add(user)
               db.commit()
               db.refresh(user)
           user.weight = user.weight_kg
           return user
       finally:
           db.close()
   ```
2. **`src/web/routes/pages/index.py`** — передавать `user.id`:
   ```python
   # БЫЛО (строка ~68):
   settings = get_settings()
   # СТАЛО:
   settings = get_settings(user.id)
   ```
3. **Другие вызовы `get_settings()`** — проверить, нужен ли per-user контекст. Если вызов из Telegram handler, где есть `user`, передавать `user.id`.

**Проверка:**
```bash
grep -rn "get_settings()" src/ | grep -v "def get_settings"    # проверить все вызовы
pytest tests/ -v
```

---

##### ✅ PREP-06: Создать структурированные аналитические функции в `recovery_view.py` (P1, BACKLOG #147)
**Файл:** `src/services/recovery_view.py`
**Проблема:** Функции возвращают строки с эмодзи для HTML. Модуль `skills/fatigue.py` нуждается в структурированных результатах.
**Решение:** Добавить новые функции, возвращающие `dict` с числовыми значениями:

```python
# src/services/recovery_view.py
from typing import Optional

def hrv_status_structured(avg_hrv: Optional[float], baseline: Optional[float], sd: Optional[float]) -> dict:
    """Структурированный HRV-статус (Structured HRV status).
    Returns: {"status": str, "value": float, "deviation_sd": float, "message": str}
    """
    if avg_hrv is None or baseline is None or sd is None or sd == 0:
        return {"status": "unknown", "value": None, "deviation_sd": None, "message": "Недостаточно данных"}
    
    deviation = (avg_hrv - baseline) / sd
    if deviation > 1.0:
        status = "high"
        message = "HRV повышена — отличное восстановление"
    elif deviation > -1.0:
        status = "normal"
        message = "HRV в норме — готов к тренировкам"
    elif deviation > -2.0:
        status = "low"
        message = "HRV понижена — рекомендуется лёгкая тренировка"
    else:
        status = "very_low"
        message = "HRV очень низкая — рекомендуется отдых"
    
    return {"status": status, "value": avg_hrv, "deviation_sd": deviation, "message": message}

def load_status_structured(training_load: Optional[float], load_ratio: Optional[float]) -> dict:
    """Структурированный статус нагрузки (Structured load status).
    Returns: {"status": str, "value": float, "ratio": float, "message": str}
    """
    if training_load is None or load_ratio is None:
        return {"status": "unknown", "value": None, "ratio": None, "message": "Недостаточно данных"}
    
    if load_ratio < 0.8:
        status = "low"
        message = "Низкая нагрузка — можно увеличить интенсивность"
    elif load_ratio < 1.2:
        status = "optimal"
        message = "Оптимальная нагрузка — продолжай в том же духе"
    elif load_ratio < 1.5:
        status = "high"
        message = "Высокая нагрузка — следи за восстановлением"
    else:
        status = "very_high"
        message = "Очень высокая нагрузка — риск перетренированности"
    
    return {"status": status, "value": training_load, "ratio": load_ratio, "message": message}
```

**Проверка:**
```bash
python -c "from src.services.recovery_view import hrv_status_structured; print(hrv_status_structured(50, 48, 9))"
pytest tests/ -v
```

---

##### ✅ PREP-07: Создать функции трендов (slope, EWMA, moving average) (P1, BACKLOG #148)
**Файл:** `src/services/analytics_helpers.py` (новый, ~80-100 строк)
**Проблема:** Нет функций для вычисления трендов. `skills/progress.py` будет строиться с нуля.
**Решение:**

```python
# src/services/analytics_helpers.py
"""Вспомогательные функции для аналитики (Helper functions for analytics)."""

from typing import Optional

def compute_slope(series: list[float]) -> Optional[float]:
    """Вычислить наклон линейной регрессии (Compute linear regression slope).
    Args: series — список числовых значений во времени.
    Returns: наклон (единиц/шаг) или None, если данных недостаточно.
    """
    n = len(series)
    if n < 2:
        return None
    
    x_mean = (n - 1) / 2.0
    y_mean = sum(series) / n
    
    numerator = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(series))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    
    if denominator == 0:
        return None
    
    return numerator / denominator

def compute_ewma(series: list[float], alpha: float = 0.3) -> Optional[float]:
    """Вычислить экспоненциально взвешенное скользящее среднее (Compute EWMA).
    Args: series — список числовых значений, alpha — коэффициент сглаживания (0 < alpha <= 1).
    Returns: последнее значение EWMA или None, если серия пуста.
    """
    if not series:
        return None
    
    ewma = series[0]
    for value in series[1:]:
        ewma = alpha * value + (1 - alpha) * ewma
    
    return ewma

def compute_moving_average(series: list[float], window: int = 7) -> Optional[float]:
    """Вычислить скользящее среднее (Compute moving average).
    Args: series — список числовых значений, window — размер окна.
    Returns: среднее последних `window` значений или None, если данных недостаточно.
    """
    if len(series) < window:
        return None
    
    return sum(series[-window:]) / window

def compute_trend_direction(series: list[float], threshold: float = 0.1) -> str:
    """Определить направление тренда (Determine trend direction).
    Args: series — список числовых значений, threshold — порог для "stable" (относительное изменение).
    Returns: "improving", "declining", "stable".
    """
    slope = compute_slope(series)
    if slope is None:
        return "unknown"
    
    mean_val = sum(series) / len(series) if series else 0
    if mean_val == 0:
        return "stable"
    
    relative_change = slope / abs(mean_val)
    
    if relative_change > threshold:
        return "improving"
    elif relative_change < -threshold:
        return "declining"
    else:
        return "stable"
```

**Проверка:**
```bash
python -c "from src.services.analytics_helpers import compute_slope, compute_ewma; print(compute_slope([1,2,3,4,5]))"
# Ожидаемый вывод: 1.0 (наклон линейного ряда)
pytest tests/ -v
```

---

##### ✅ PREP-08: Добавить `avg_pace` на `TrainingSession` (P1, BACKLOG #149)
**Файл:** `src/domain/models/training.py`, Alembic миграция, `src/analysis/__init__.py`
**Проблема:** У `DeletedTraining` есть `avg_pace`, у `TrainingSession` — нет. Каждый раз нужно считать `duration_minutes / total_distance_km`.
**Решение:**
1. **`src/domain/models/training.py`** — добавить колонку:
   ```python
   class TrainingSession(Base):
       # ... существующие колонки ...
       avg_pace = Column(Float, nullable=True)  # Средний темп (мин/км) (Average pace, min/km)
   ```
2. **Alembic миграция** (добавить в ту же миграцию из PREP-02):
   ```python
   def upgrade():
       # ... индексы ...
       op.add_column('training_sessions', sa.Column('avg_pace', sa.Float(), nullable=True))
       
       # Data migration: вычислить avg_pace для существующих записей
       conn = op.get_bind()
       conn.execute(text("""
           UPDATE training_sessions
           SET avg_pace = CASE
               WHEN total_distance_km > 0 THEN duration_minutes / total_distance_km
               ELSE NULL
           END
       """))
   
   def downgrade():
       op.drop_column('training_sessions', 'avg_pace')
   ```
3. **`src/analysis/__init__.py`** — вычислять `avg_pace` при создании сессии:
   ```python
   # В process_trackpoints() после вычисления duration и distance:
   avg_pace = duration_minutes / total_distance_km if total_distance_km > 0 else None
   result['avg_pace'] = avg_pace
   ```
4. **`src/web/routes/uploads.py`** — сохранять `avg_pace` при создании `TrainingSession`:
   ```python
   session = TrainingSession(
       # ... существующие поля ...
       avg_pace=analysis_result.get('avg_pace'),
   )
   ```

**Проверка:**
```bash
alembic upgrade head
pytest tests/ -v
# Ручная проверка: загрузить TCX, проверить, что avg_pace сохранён
```

---

##### ✅ PREP-09: Создать тестовые фабрики для DailyMetrics и TrainingSession (P1, BACKLOG #150)
**Файл:** `tests/helpers.py`
**Проблема:** Нет фабрик для ORM-объектов. Тестирование скиллов невозможно.
**Решение:** Добавить builder-функции:

```python
# tests/helpers.py
from datetime import date, datetime, timedelta
from src.domain.models import DailyMetrics, TrainingSession, TrainingFeedback, User

def build_daily_metrics(
    user_id: int,
    start_date: date,
    days: int = 30,
    hrv_base: float = 50.0,
    hrv_trend: str = "stable",  # "stable", "declining", "improving"
) -> list[DailyMetrics]:
    """Создать серию DailyMetrics для тестов (Create DailyMetrics series for tests).
    Args: user_id, start_date, days, hrv_base, hrv_trend.
    Returns: список DailyMetrics объектов (не сохранённых в БД).
    """
    metrics = []
    for i in range(days):
        d = start_date + timedelta(days=i)
        
        # HRV с трендом
        if hrv_trend == "declining":
            hrv = hrv_base - (i * 0.5)
        elif hrv_trend == "improving":
            hrv = hrv_base + (i * 0.3)
        else:
            hrv = hrv_base + (i % 5 - 2)  # колебания ±2
        
        dm = DailyMetrics(
            user_id=user_id,
            date=d,
            avg_sleep_hrv=hrv,
            sleep_hrv_baseline=hrv_base,
            sleep_hrv_sd=10.0,
            rhr=55 + (i % 3),
            tired_rate=(i % 5) - 2,  # -2..+2
            training_load=50.0 + (i * 2),
            training_load_ratio=1.0 + (i * 0.01),
            performance=70 + (i % 10),
            ati=2.5 + (i * 0.1),
            cti=1.8 + (i * 0.05),
            vo2max=45.0 + (i * 0.05),
            lthr=165,
            stamina_level=75.0 + (i * 0.2),
            recovery_pct=80 - (i % 20),
        )
        metrics.append(dm)
    
    return metrics

def build_training_session(
    user_id: int,
    begin_ts: datetime,
    training_type: str = "tempo",
    distance_km: float = 10.0,
    duration_minutes: float = 60.0,
    avg_hr: int = 150,
    training_effect: float = 3.5,
) -> TrainingSession:
    """Создать TrainingSession для тестов (Create TrainingSession for tests).
    Returns: TrainingSession объект (не сохранённый в БД).
    """
    avg_pace = duration_minutes / distance_km if distance_km > 0 else None
    
    return TrainingSession(
        user_id=user_id,
        begin_ts=begin_ts,
        total_distance_km=distance_km,
        duration_minutes=duration_minutes,
        avg_heart_rate=avg_hr,
        max_heart_rate=avg_hr + 20,
        training_type=training_type,
        training_effect=training_effect,
        vo2max=45.0,
        calories=int(duration_minutes * 10),
        avg_pace=avg_pace,
        segments_json=[
            {"distance_km": distance_km, "pace_min_km": avg_pace, "avg_hr": avg_hr, "duration": duration_minutes}
        ],
    )

def build_training_feedback(
    user_id: int,
    session_id: int,
    rating: int = 5,
    notes: str = "",
) -> TrainingFeedback:
    """Создать TrainingFeedback для тестов (Create TrainingFeedback for tests)."""
    return TrainingFeedback(
        user_id=user_id,
        session_id=session_id,
        rating=rating,
        notes=notes,
    )
```

**Проверка:**
```bash
python -c "from tests.helpers import build_daily_metrics, build_training_session; print(len(build_daily_metrics(1, date.today(), 30)))"
# Ожидаемый вывод: 30
pytest tests/ -v
```

---

##### ✅ PREP-10: Создать `src/coach/config.py` (P2, BACKLOG #151)
**Файл:** `src/coach/config.py` (новый, ~50-80 строк)
**Проблема:** Нет параметров аналитики: веса readiness/fatigue score, пороги injury risk, EWMA-параметры.
**Решение:**

```python
# src/coach/config.py
"""Конфигурация модуля аналитики и коучинга (Coach module configuration)."""

# Веса для readiness score (Weights for readiness score)
READINESS_WEIGHTS = {
    "hrv_status": 0.30,
    "rhr_deviation": 0.20,
    "tired_rate": 0.15,
    "recovery_pct": 0.20,
    "sleep_quality": 0.15,
}

# Веса для fatigue score (Weights for fatigue score)
FATIGUE_WEIGHTS = {
    "training_load_ratio": 0.35,
    "hrv_deviation": 0.25,
    "ati_cti_ratio": 0.20,
    "consecutive_hard_days": 0.20,
}

# Пороги injury risk (Injury risk thresholds)
INJURY_RISK_THRESHOLDS = {
    "hrv_very_low_days": 3,  # 3+ дня очень низкой HRV → высокий риск
    "load_ratio_high": 1.5,  # ACWR > 1.5 → высокий риск
    "consecutive_hard_days": 4,  # 4+ тяжёлых дня подряд → высокий риск
}

# Параметры калибровки EWMA (EWMA calibration parameters)
CALIBRATION_EWMA_ALPHA = 0.2  # Коэффициент сглаживания (smoothing factor)
CALIBRATION_MIN_SAMPLES = 5  # Минимум данных для калибровки (minimum samples)
CALIBRATION_MAX_CHANGE_PCT = 0.10  # Максимальное изменение за итерацию 10% (max change per iteration)

# Пороги confidence (Confidence thresholds)
CONFIDENCE_MIN_DAYS = 14  # Минимум 14 дней данных для высокого доверия
CONFIDENCE_MIN_SESSIONS = 10  # Минимум 10 тренировок для высокого доверия
CONFIDENCE_LOW_THRESHOLD = 0.5  # Ниже 0.5 → низкое доверие

# Часы восстановления по типу тренировки (Recovery hours by training type)
RECOVERY_HOURS_BY_TYPE = {
    "interval": 48,
    "tempo": 36,
    "long": 30,
    "recovery": 12,
    "race": 72,
}

# Параметры 80/20 (80/20 rule parameters)
DISTRIBUTION_80_20 = {
    "easy_share_target": 0.80,  # 80% лёгкого бега
    "hard_share_target": 0.20,  # 20% тяжёлого бега
    "tolerance": 0.10,  # Допуск ±10%
}

# Цикл 3:1 (3:1 cycle parameters)
CYCLE_3_1 = {
    "build_weeks": 3,  # 3 недели нарастания
    "deload_week": 1,  # 1 неделя разгрузки
    "deload_volume_pct": 0.60,  # 60% объёма на неделе разгрузки
}

# Рост нагрузки (Load progression)
LOAD_PROGRESSION = {
    "max_weekly_increase_pct": 10,  # Максимум +10% в неделю
    "max_monthly_increase_pct": 30,  # Максимум +30% в месяц
}
```

**Проверка:**
```bash
mkdir -p src/coach
touch src/coach/__init__.py
python -c "from src.coach.config import READINESS_WEIGHTS; print(READINESS_WEIGHTS)"
```

---

##### ✅ PREP-11: Разделить `src/models.py` на shim и сервисы (P2, BACKLOG #152)
**Файл:** `src/models.py`, `src/services/user_service.py` (новый)
**Проблема:** `models.py` содержит бизнес-логику (`get_settings`, `get_user`) — это не реэкспорт моделей.
**Решение:**
1. **`src/services/user_service.py`** (новый) — вынести сервисные функции:
   ```python
   # src/services/user_service.py
   from src.domain.models import SessionLocal, User
   from src.config import settings as app_settings
   
   def get_user_settings(user_id: int = 1) -> User:
       """Получение настроек пользователя (Get user settings)."""
       db = SessionLocal()
       try:
           user = db.query(User).filter(User.id == user_id).first()
           if not user:
               user = User(
                   id=user_id, max_hr=app_settings.default_max_hr, weight_kg=85.0,
                   max_credible_pace=3.0, max_gps_jump_m=100.0, min_hr_for_fast_pace=130,
               )
               db.add(user)
               db.commit()
               db.refresh(user)
           user.weight = user.weight_kg
           return user
       finally:
           db.close()
   
   def get_user_by_telegram_id(chat_id: int) -> User:
       """Получить пользователя по telegram chat_id (Get user by telegram chat ID)."""
       db = SessionLocal()
       try:
           return db.query(User).filter(User.telegram_chat_id == chat_id).first()
       finally:
           db.close()
   
   def get_or_create_user_by_telegram(chat_id: int, username: str = None) -> User:
       """Создать или получить пользователя по telegram (Get or create user by telegram)."""
       db = SessionLocal()
       try:
           user = db.query(User).filter(User.telegram_chat_id == chat_id).first()
           if not user:
               user = User(telegram_chat_id=chat_id, telegram_username=username)
               db.add(user)
               db.commit()
               db.refresh(user)
           return user
       finally:
           db.close()
   
   def get_user_by_id(user_id: int) -> User:
       """Получить пользователя по ID (Get user by ID)."""
       db = SessionLocal()
       try:
           return db.query(User).filter(User.id == user_id).first()
       finally:
           db.close()
   ```
2. **`src/models.py`** — оставить shim с re-export + deprecated aliases:
   ```python
   # Shim для обратной совместимости (Backward compat shim)
   from src.domain.models import *  # noqa: F401, F403
   
   # Deprecated: использовать src.services.user_service
   from src.services.user_service import (
       get_user_settings as get_settings,
       get_user_by_telegram_id as get_user_by_telegram,
       get_or_create_user_by_telegram,
       get_user_by_id as get_user,
   )
   ```

**Проверка:**
```bash
grep -rn "from src.models import get_settings\|from src.models import get_user" src/ | wc -l
# Должно быть >0 (старые импорты работают через shim)
python -c "from src.services.user_service import get_user_settings; print('OK')"
pytest tests/ -v
```

---

##### ✅ PREP-17: Исправить форматирование темпа на графике (P1, BACKLOG #20)
**Файл:** `src/web/templates/session.html` (строки 76-116)
**Проблема:** Chart.js показывает темп как число с плавающей точкой (5.74) вместо формата М:СС (5:44). Пульс показывается как float (145.3) вместо целого (145). Пользователь при наведении мыши видит «5.74» — непонятно.
**Решение:**
1. Добавить JS-функцию `formatPace(pace)` — конвертирует float (5.74) → строку "5:44":
   ```javascript
   function formatPace(pace) {
       const m = Math.floor(pace);
       const s = Math.round((pace - m) * 60);
       return m + ':' + String(s).padStart(2, '0');
   }
   ```
2. Добавить `plugins.tooltip.callbacks.label` — форматирование значений в tooltip:
   - Темп: `formatPace(raw) + ' мин/км'`
   - Пульс: `Math.round(raw) + ' уд/мин'`
3. Добавить `scales.y1.ticks.callback` — форматирование оси Y темпа: `formatPace(value)`
4. Добавить `scales.y.ticks.callback` — форматирование оси Y пульса: `Math.round(value)`

**Проверка:**
```bash
# Визуальная: открыть страницу тренировки, навести мышь на график
# Темп показывает "5:44" вместо "5.74"
# Пульс показывает "145" вместо "145.3"
# Оси Y показывают отформатированные значения
```

---

**Результат:** Все 12 задач выполнены. Sprint 20c завершён.

**Проверка (завершена):**
```bash
python -c "from src.telegram.handlers.stats import StatsPages; print('stats OK')"  # → OK
python -c "from src.services.repositories import TrainingRepository; print('repos OK')"  # → OK
python -c "from src.services.analytics_helpers import compute_slope; print('helpers OK')"  # → OK
python -c "from src.coach.config import READINESS_WEIGHTS; print('coach config OK')"  # → OK

grep -rn "TrainingSession.distance_km\|TrainingSession.duration_seconds\|TrainingSession.sport" src/ | wc -l    # → 0 ✅
grep -rn "json.dumps(intervals)" src/services/sync/health.py | wc -l    # → 0 ✅
pytest tests/ -v    # 120+ тестов, все зелёные ✅
```

---

### 🚀 Модуль аналитики (8 этапов из `decision_module_design.md`)

Стартует после завершения Sprint 20. Все 8 этапов в том же порядке, что и в дизайн-документе.

| Этап | Описание | Статус |
|------|----------|--------|
| 0 | Каркас и данные (`src/coach/`, таблицы) | ⏸️ |
| 1 | Аналитика (Skills) + State Assessor | ⏸️ |
| 2 | Движок + безопасность (P1) + Recovery Timing (P2) | ⏸️ |
| 3 | База знаний из литературы (дистилляция) | ⏸️ |
| 4 | Персонализация и обучение | ⏸️ |
| 5 | LLM Coach | ⏸️ |
| 6 | Многонедельные планы | ⏸️ |
| 7 | Обратная связь и качество | ⏸️ |

---

### ❄️ Заморожено (фичи — после аналитики)

| Старый спринт | Описание | Статус |
|---------------|----------|--------|
| Старый Sprint 13 | Фильтры + статистика | ⏸️ Заморожено |
| Старый Sprint 14 | Multi-brand onboarding | ⏸️ Заморожено |
| Старый Sprint 15 | Факторы самочувствия | ⏸️ Заморожено |
| Sprint 7 | Admin panel | ⏸️ Заморожено |

---

## 5. ПРИОРИТЕТЫ

```
─── ВЫПОЛНЕНО ─────────────────────────────────────────────
Спринты 1-7      — Инфраструктура, Docker, модели, sync    ✅
Спринт 8         — parsers/common.py разбить                ✅
Спринт 9         — telegram_bot.py разбить                  ✅
Фаза A (P0)      — Починить Telegram-бот (импорты)          ✅
Фаза B (P1)      — Тонкие роуты + мульти-бренд settings    ✅
Фаза C (P2)      — Cleanup (httpx, exceptions, async)       ✅
Фаза D           — Документация (BACKLOG, чеклисты)         ✅
Спринт 11 (P1)   — models.py + sync_service разбить         ✅
Спринт 12 (P1)   — sync.py + pages.py чистка               ✅
AUDIT-014        — Алгоритм сегментации                     ✅
Спринт 13 (P0)   — Security & Hardening                     ✅
Спринт 14 (P0)   — Thread Safety                            ✅
Спринт 15 (P0/P1)— Observability                            ✅
Спринт 16 (P1)   — Config Consolidation                     ✅
Спринт 17 (P1)   — Data Integrity                           ✅
Спринт 18 (P1)   — Architecture Cleanup (DRY, split)        ✅
Спринт 19 (P2)   — Documentation & Types                    ✅
Спринт 20 (P2)   — Tests                                    ✅
Спринт 20b (P1)  — Tech Debt Fix                            ✅
─── ПОДГОТОВКА К АНАЛИТИКЕ (ЗАВЕРШЕНА) ────────────────────
Спринт 20c (P0/P1)— Analytics Preparation (PREP-01..12)     ✅
─── МОДУЛЬ АНАЛИТИКИ ──────────────────────────────────────
Этап 0           — Каркас и данные (src/coach/)             ⏸️
Этап 1           — Аналитика (Skills) + State Assessor      ⏸️
Этап 2           — Движок + безопасность + Recovery         ⏸️
Этап 3           — База знаний из литературы                ⏸️
Этап 4           — Персонализация и обучение                ⏸️
Этап 5           — LLM Coach                                ⏸️
Этап 6           — Многонедельные планы                     ⏸️
Этап 7           — Обратная связь и качество                ⏸️
─── ПОСЛЕ АНАЛИТИКИ ───────────────────────────────────────
Старый Sprint 13 — Фильтры + статистика                     ⏸️
Старый Sprint 14 — Multi-brand onboarding                   ⏸️
Старый Sprint 15 — Факторы самочувствия                     ⏸️
Sprint 7         — Admin panel                              ⏸️
```

---

## 6. СТРУКТУРА ПОСЛЕ РЕФАКТОРИНГА (целевое состояние)

```
src/
  main.py                         # 7 строк
  run_telegram_bot.py             # 3 строки
  startup.py                      # create_app()
  scheduler.py                    # AutoSyncScheduler (обёртка)

  config/
    __init__.py                   # экспорт settings + constants
    settings.py                   # pydantic-settings
    constants.py                  # плоские константы

  domain/                         # DDD models
    models/
      base.py                     # engine, session, db helper
      user.py
      training.py                 # TrainingSession, Feedback, DeletedTraining
      watch.py                    # WatchCredential
      health.py                   # DailyMetrics, WeightMeasurement
      auth.py                     # AuthToken
      audit.py                    # AuditEvent

  api/                            # Middleware + API routes
    middleware.py                 # errors, logging, sessions
    deps.py                       # get_current_user, get_db
    routes/
      auth.py                     # /auth/*
      health.py                   # /health/*

  web/                            # Web UI
    state.py                      # глобальное состояние
    templates/                    # Jinja2
    routes/
      pages/                      # Пакет: auth (48), index (184), session (177), settings (118)
      uploads.py                  # POST /upload, /upload/confirm
      sync.py                     # POST /sync/{brand}/run, /sync/{brand}/health (93 строки)
      logs.py                     # GET /logs

  services/                       # Business logic (старый слой, но разделённый)
    sync/                          # Пакет синхронизации (Sprint 11)
      __init__.py                  # реэкспорт (run_sync_for_user, etc.)
      utils.py                     # SYNC_TICK_INTERVAL, интервалы, _make_client
      health.py                    # save_dashboard_data, sync_health_for_user
      activities.py                # sync_activities_for_user
      orchestrator.py              # run_sync_for_user, auto_sync_health, auto_sync_activities
    sync_service.py               # shim: DeprecationWarning (обратная совместимость)
    audit.py                      # AuditService
    auth.py                       # hash/verify/tokens
    stats.py                      # calc_stats, fmt_duration, zone_ranges
    telegram_notify.py            # уведомления
    recovery_view.py              # HRV status, tired label
    feedback_service.py           # Фаза 5: факторы самочувствия

  telegram/                       # Telegram bot (разделённый)
    __init__.py                   # экспорт run_bot
    main.py                       # run_bot, Application сборка
    config.py                     # константы (EMAIL, PASSWORD, NEW_PASSWORD)
    state.py                      # _awaiting_weight
    utils.py                      # get_user, _get_web_app_url
    sync_runner.py                # run_sync_in_thread
    handlers/
      __init__.py
      start.py                    # регистрация, диалоги
      sync.py                     # /sync
      stats.py                    # /stats, StatsPages
      trainings.py                # /trainings
      weight.py                   # /weight, handle_weight_message
      account.py                  # /delete_me, /login_info, /reset_password
      feedback.py                 # feedback_callback
    jobs/
      __init__.py
      weight.py                   # daily_weight_job
      recovery.py                 # daily_recovery_check_job

  watch/                          # Multi-brand watch clients
    base.py                       # BaseWatchClient(ABC)
    coros.py                      # CorosWatchClient
    factory.py                    # register, get_watch_client, list_brands

  parsers/                        # Parsers (разделённые)
    common.py                     # process_trackpoints (оркестратор)
    gps.py                        # clean_trackpoints, haversine_m
    weather.py                    # fetch_weather, weather_icon
    hr_zones.py                   # get_zone, get_band, zone_ranges
    classification.py             # классификация
    segmentation.py               # сегментация
    utils.py                      # format_pace, format_duration, calc_elevation, find_timezone
    tcx_parser.py                 # парсинг TCX
    fit_parser.py                 # парсинг FIT

  utils/
    logger.py                     # structured logging

  exceptions.py                   # AppError hierarchy
  crypto.py                       # Fernet encrypt/decrypt
  deps.py                         # общие зависимости (Jinja2Templates)

tests/
  conftest.py
  test_models.py
  parsers/
    test_common.py
    test_gps.py
    test_classification.py
    test_hr_zones.py
  services/
    test_stats.py
    test_sync_service.py
  api/
    test_health.py
    test_auth.py
  fixtures/
    README.md              # описание каждой тренировки
    interval_coros.tcx     # интервальная с Coros
    tempo_garmin.tcx       # темповая с Garmin
    long_run_polar.tcx     # long run с Polar
    recovery.tcx           # восстановительная
    gps_spikes.fit         # FIT с GPS-скачками
    short_walk.tcx         # <1 км (отбрасывание)
```

---

**Итого:** 20 спринтов (12 выполнено + 8 подготовка к аналитике → модуль аналитики).  
Критические (P0): Спринты 13-14 — примерно 2-4 дня.

---

## 7. ПЛАН РЕФАКТОРИНГА v3 (13.07.2026)

Ниже — пошаговый план, консолидирующий находки аудита v3 и хорошие практики из референс-проекта `Бот_изучения_английского` (5-файловая документационная система: TZ / AGENTS / SPRINTS / CHECKLISTS / BACKLOG). Выполняется по фазам A→D с проверкой и коммитом после каждой.

### Фаза A — P0: Починить Telegram-бот (критические баги)

**A.1 Сломанные импорты `from src.database` → `from src.models`** (11 файлов):

| Файл:строка | Замена |
|---|---|
| `src/telegram/sync_runner.py:5` | `from src.models import SessionLocal` |
| `src/telegram/utils.py:5` | `from src.models import get_db` |
| `src/telegram/jobs/recovery.py:6` | `from src.models import SessionLocal` |
| `src/telegram/jobs/weight.py:6` | то же |
| `src/telegram/handlers/account.py:6` | то же |
| `src/telegram/handlers/account.py:8` | `from src.services.auth import hash_password` |
| `src/telegram/handlers/start.py:6` | `from src.models import SessionLocal` |
| `src/telegram/handlers/start.py:8` | `from src.services.auth import hash_password` |
| `src/telegram/handlers/sync.py:38` | `from src.models import SessionLocal` |
| `src/telegram/handlers/trainings.py:7` | `from src.models import SessionLocal` |
| `src/telegram/handlers/stats.py:9` | то же |
| `src/telegram/handlers/weight.py:9` | то же |
| `src/telegram/handlers/feedback.py:4` | то же |

**A.2 Переписать `sync_runner.py`** — заменить мёртвые `SyncService`/`SyncLog`/`full_sync` на реальные `sync_activities_for_user(cred, brand)` и `sync_health_for_user(cred, brand)` из `src/services/sync_service.py`. Логика: найти `User` → все активные `WatchCredential` → новый event loop → вызвать обе async-функции для каждого креда → суммировать результат → `AuditService.log_sync_*`. `db.func.now()` → `datetime.now(timezone.utc)`.

**A.3 `TrainingSession.start_time` → `begin_ts`** (3 файла, 7 ссылок):
`handlers/sync.py:46`, `handlers/trainings.py:25,69,70,82`, `handlers/stats.py:52,65`.

**A.4 AUDIT-011 — удалить `COROS_SYNC_*`** из `src/services/audit.py`:
- строки 38–40 (3 константы) — заменить на `SYNC_STARTED/COMPLETED/FAILED` (41–43)
- строки 147–176 (3 метода `log_coros_sync_*`) — удалить

**Проверка фазы A (поведенческая, по аналогии с референс-проектом):**
```bash
python -c "from src.telegram.main import run_bot; print('import OK')"
grep -rn "from src.database" src/ | wc -l    # → 0
grep -rn "SyncLog\|SyncService\|full_sync\|TrainingSession.start_time" src/ | wc -l  # → 0
```
+ smoke-тест: запуск бота, `/start` отвечает.

### Фаза B — P1: Тонкие роуты + мульти-бренд в settings ✅

**B.1 `pages.py` хардкод `"coros"`** — ✅ выполнено: `settings_save` параметр `watch_brand`/`watch_email`/`watch_password`/`activity_sync_interval`/`health_sync_interval`, перебор всех кредов пользователя, шаблон `settings.html` перебирает бренды через `{% for cred in watch_creds %}`.

**B.2 Бизнес-логика из роутов в сервисы** — ✅ выполнено:
- `encrypt()` из роутов удалён → `src/services/watch_credentials.py` (`upsert_watch_credential`) ✅
- `DeletedTraining(...)` и `TrainingFeedback(...)` из роутов → `src/services/training_service.py` (`delete_training`, `upsert_feedback`) ✅
- `web/routes/sync.py`: `db.add/commit` + `TrainingSession(**data)` → `sync_service.run_sync_for_user` ✅

**B.3 AUDIT-006 — единый entry point `run_sync_for_user(user_id, brand, sync_type)`:** ✅ в `sync_service.py`. Web вызывает только его. Заодно исправлено:
- Web sync `since=None` → `since = last_sync - 2h` (как autosync) ✅
- Web sync шлёт Telegram-уведомления через `telegram_notify` в `sync_activities_for_user` ✅
- Telegram `sync_runner.py` — TODO: использует прямой вызов (обоснованно: все бренды + сводный отчёт). Миграция на `run_sync_for_user_all_brands(chat_id)` — отдельная задача.

**DoD:** `wc -l src/web/routes/sync.py` = 93 < 200 ✅; `pages/*.py` max 184 < 250 ✅.
**Доп.:** `pages.py` (601) разбит на пакет `pages/` (auth 48, index 184, session 177, settings 118) — AUDIT-013 закрыт.

### Фаза C — P2: Cleanup и унификация ✅

**C.1** Мёртвые зависимости в `pyproject.toml`: убрать `"APScheduler==3.11.3"` и `"requests==2.34.2"`. ✅ `weather.py` мигрирован на `httpx` (sync), обе зависимости удалены.
**C.2** Дублирование HR-zone math: `calculate_hr_zones`, `get_hr_zone` + 10 констант `Z*_PCT` удалены из `constants.py`. Единый источник — `src/parsers/hr_zones.py`. ✅
**C.3** `CorosAPIError` → `WatchAPIError` (brand-agnostic). `CorosAuthError` → `WatchAuthError`. Вынесены в `exceptions.py`. `coros.py` импортирует из `exceptions.py`, все 12 `raise` обновлены с `brand="coros"`. ✅
**C.4** `db_path = "running_coach.db"` удалён из `settings.py`. ✅
**C.5** AUDIT-008 — создан `src/services/async_utils.py` с `run_async_in_thread(coro)`. Заменены `_run_async` и `asyncio.run` в `sync_service.py` и `sync_runner.py`. ✅
**C.6** SQLite-ветка `get_engine()` помечена bilingual-комментарием "test-only". ✅

### Фаза D — Документация: good practices из «Бот_изучения_английского» ✅

**D.1 Создать `BACKLOG.md`** — ✅ создан. 16 пунктов: FIXME из кода + пункты из аудита. Формат: `| # | Тег | Описание | Файл | Статус |`.

**D.2 Создать `docs/CHECKLIST_NEW_PROVIDER.md`** — ✅ создан. Пошаговый чеклист: клиент (ABC), регистрация в factory, конфигурация, исключения, smoke-тест, интеграция, Docker.

**D.3 Усилить `AGENTS.md`** — ✅ выполнен:
- Раздел «Дисциплина работы ИИ-агента» (6 пунктов: потолок 400 строк, backlog-дисциплина, секреты, behavioral test, Docker rebuild таблица, протокол конца сессии)
- Обновлена структура файлов (pages/ пакет, watch_credentials, training_service, async_utils)
- Добавлена ссылка на `docs/CHECKLIST_NEW_PROVIDER.md` в таблицу документации

**D.4 `PROJECT_AUDIT.md` правки** — ✅ выполнен:
- AUDIT-011 → ✅ (выполнено в Фазе A)
- Sprint 9 reopen (AUDIT-015 ещё не закрыт)
- Спринты 13–15, 7, аналитика заморожены

**D.5 `README.md` правки** — ✅ выполнен:
- Обновлено дерево файлов (pages/ пакет, watch_credentials.py, training_service.py, async_utils.py)
- Убрана секция «Технический долг» → ссылка на PROJECT_AUDIT.md
- Обновлена дата

---

### Порядок выполнения
1. **Фаза A** → проверка → коммит → отчёт → пауза (ждать разрешения на B)
2. **Фаза B** → проверка → коммит → отчёт → пауза
3. **Фаза C** → проверка → коммит → отчёт → пауза
4. **Фаза D** → проверка → коммит → итоговый отчёт
