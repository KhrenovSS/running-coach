# PROJECT AUDIT — Running Coach

**Дата:** 14.07.2026 (аудит v3 — 13.07.2026; реструктуризация спринтов под модуль аналитики — 14.07.2026)  
**Версия:** 4.0  
**Формат:** Architecture Refactoring Backlog + Tech Debt Registry

---

## 0. Контекст

Система: монолитное backend-приложение на FastAPI (~7157 строк, 48 `.py` файлов).

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
- [ ] `wc -l src/parsers/common.py` < 100 строк
- [ ] Все тесты проходят
- [ ] Парсинг TCX и FIT работает

---

#### AUDIT-002 — `src/telegram_bot.py` превышал лимит в 2 раза (1142 строки) ⚠️ reopen

**Файл:** `src/telegram_bot.py` (1142 строк) — **удалён, разбит на пакет `src/telegram/`**
> ⚠️ Пакет создан, но не запускается из-за сломанных импортов — см. **AUDIT-015**.

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
- [x] Каждый файл < 300 строк
- [x] Все 12 файлов проходят py_compile

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

#### AUDIT-015 — `src/telegram/` пакет не запускается (сломанные импорты) 🔴 P0 — найдено в аудите v3

**Файлы:** 11 файлов в `src/telegram/`, `src/services/audit.py`

**Проблема:** Sprint 9 помечен `✅`, но `py_compile` проверяет только синтаксис. Реально пакет невозможно импортировать — `ModuleNotFoundError`. Три класса проблем:

1. **`from src.database import SessionLocal`** (11 файлов) — `src/database.py` **не существует**. `SessionLocal`/`get_db` уже экспортируются из `src.models`.
   - `src/telegram/sync_runner.py:5`, `utils.py:5`, `jobs/recovery.py:6`, `jobs/weight.py:6`, `handlers/{account,start,sync,trainings,stats,weight,feedback}.py`

2. **`from src.auth import hash_password`** (2 файла) — модуль `src.auth` не существует, парольная логика в `src.services.auth`.
   - `src/telegram/handlers/account.py:8`, `start.py:8`

3. **Мёртвые ссылки в `sync_runner.py`** — `SyncLog` (нет модели), `SyncService` (нет класса), `service.full_sync()` (нет метода), `db.func.now()` (`db` — это `Session`, не `sqlalchemy.func`). Реальные API: `sync_activities_for_user(cred, brand)` и `sync_health_for_user(cred, brand)` из `sync_service.py`.

4. **`TrainingSession.start_time`** — несуществующая колонка (реально `begin_ts`, `models.py:77`). `AttributeError` при использовании:
   - `handlers/sync.py:46`, `handlers/trainings.py:25,69,70,82`, `handlers/stats.py:52,65`

**Решение (Фаза A):** см. раздел 7 «План рефакторинга v3».

**DoD:**
- [ ] `python -c "from src.telegram.main import run_bot; print('OK')"` — без `ModuleNotFoundError`
- [ ] `grep -rn "from src.database" src/` → 0
- [ ] `grep -rn "src.auth import\|SyncLog\|SyncService\|full_sync\|TrainingSession.start_time" src/` → 0
- [ ] AUDIT-011 (устаревшие `COROS_SYNC_*` константы) выполнен
- [ ] Smoke-тест: бот стартует, `/start` отвечает

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
- [ ] `wc -l src/web/routes/sync.py` < 200

---

### 🟡 P2 — Желательно

#### AUDIT-010 — Logger shim (`src/logger.py` → `src/utils/logger.py`)

**Файлы:** `src/logger.py` (13 строк), `src/utils/logger.py` (250 строк)

**Проблема:** 9 модулей импортируют `from src.logger import get_logger`, 1 импортирует `from src.utils.logger import ...`. Две точки входа.

**Решение:** Убрать `src/logger.py`, обновить импорты на `src.utils.logger`.

**DoD:**
- [ ] `grep -rn "from src.logger" src/` → 0
- [ ] `src/logger.py` удалён

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
- [ ] `wc -l src/web/routes/pages*.py` каждый < 250

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

### ✅ Выполнено (Sprints 1–12)

| Спринт | Описание | Статус |
|--------|----------|--------|
| 1–7 | Инфраструктура, Docker, модели, интеграции | ✅ |
| 8 | Разбивка `parsers/common.py` | ✅ |
| 9 | Разбивка `telegram_bot.py` | ✅ |
| 10 | Тесты (отложен) | ⏩ → Sprint 20 |
| 11 | Разбивка `models.py` + `sync_service.py` | ✅ |
| 12 | Чистка роутов (`sync.py`, `pages.py`) | ✅ |
| 17 | Data Integrity — NOT NULL FKs, cascade, JSON, валидация | ✅ |

---

### 🔴 Этап подготовки к модулю аналитики (Sprints 13–20)

Цель: последовательно закрыть технические дыры, чтобы модуль аналитики стартовал на стабильном фундаменте.  
Каждый спринт содержит **поведенческую проверку** (behavioral test, AGENTS.md п.4), **Docker rebuild** (AGENTS.md п.5) и **протокол конца сессии** (AGENTS.md п.6).

---

#### Sprint 13 — Security & Hardening (P0)

**Зачем:** Закрыть критические дыры безопасности, делающие всю систему уязвимой.

**Docker:** `app` + `bot`

**Задачи:**
- [ ] **SEC-01**: Убрать дефолт `SECRET_KEY="dev-secret-key-change-in-production"` — `os.getenv("SECRET_KEY")` без fallback (нарушение AGENTS.md п.3) — `src/api/middleware.py:27`
- [ ] **SEC-02**: `encrypted_user` — шифровать через Fernet или переименовать колонку в `email` (вводит в заблуждение) — `src/services/watch_credentials.py:54`, Alembic migration
- [ ] **SEC-03**: `PENDING_DIR` из `/tmp` в `uploads/` (мирно-читаемая директория с GPS/HR) — `src/web/state.py:6`
- [ ] **SEC-04**: Docker: `USER appuser`, убрать порт 5432 наружу, healthcheck для `app`+`bot` — `Dockerfile`, `docker-compose.yml`
- [ ] **SEC-05**: Rate-limiting на `/auth/login`, `/upload`, `/settings` — `src/api/routes/auth.py`, `src/web/routes/uploads.py`, `src/web/routes/pages/settings.py`
- [ ] **SEC-06**: Session fixation: `request.session.clear()` + `session.regenerate()` после логина — `src/api/routes/auth.py`
- [ ] **SEC-07**: Нет CSRF защиты на POST endpoints — `src/api/routes/auth.py`, веб-роуты
- [ ] **SEC-08**: `except Exception: pass` в `account.py:118-119,127-129` — заменить на конкретные типы (AGENTS.md п.2) — `src/telegram/handlers/account.py`
- [ ] **SEC-09**: Remove `reload=True` from `main.py` dev block (dead code в Docker)

**Проверка:**
```bash
grep -rn "dev-secret-key-change-in-production" src/ | wc -l       # → 0
grep -rn "except: pass\|except Exception: pass" src/ | wc -l      # → 0
grep -rn "PENDING_DIR.*/tmp" src/ | wc -l                         # → 0
```

---

#### Sprint 14 — Thread Safety (P0)

**Зачем:** Устранить race conditions, которые делают поведение недетерминированным при конкуррентном доступе.

**Docker:** `app` + `bot`

**Задачи:**
- [ ] **TS-01**: `threading.Lock` на `_pending` — `src/web/state.py:9`
- [ ] **TS-02**: `threading.Lock` на `_awaiting_weight` — `src/telegram/state.py:1`
- [ ] **TS-03**: Lock на `_engine` / `_maker` (double-checked locking anti-pattern) — `src/domain/models/base.py:32-67`
- [ ] **TS-04**: Lock на `_fernet_cache` — `src/crypto.py:34-36,50`
- [ ] **TS-05**: Lock на logger cache (`_app_logger`, `_requests_logger`, `_audit_file_logger`) — `src/utils/logger.py:171-194`
- [ ] **TS-06**: Cleanup `_pending` записей после confirm/timeout — `src/web/state.py`
- [ ] **TS-07**: Cleanup `_awaiting_weight` при удалении пользователя — `src/telegram/state.py`
- [ ] **TS-08**: scheduler TOCTOU: `threading.Event` вместо голого `if self._started` — `src/scheduler.py:23-25`
- [ ] **TS-09**: Lock на доступ к `_auto_sync_status` в sync/utils.py и index.py (shallow copy недостаточен)

**Проверка:**
```bash
python -c "from src.telegram.main import run_bot; print('import OK')"
python -c "from src.startup import create_app; print('import OK')"
```

---

#### Sprint 15 — Observability (P0/P1)

**Зачем:** Сделать ошибки видимыми. Без этого модуль аналитики будет работать «вслепую» — непонятно, почему рекомендации не приходят.

**Docker:** `app`

**Задачи:**
- [ ] **OBS-01**: `fix_logger_after_uvicorn()` — починить для ВСЕХ трёх логгеров (`app`, `requests`, `audit_file`), а не только `"app"` — `src/utils/logger.py:232`
- [ ] **OBS-02**: Alembic failure из `logger.error` → `raise SystemExit(1)` (hard fail при битой БД) — `src/startup.py:24-25`
- [ ] **OBS-03**: Silent parse failure → `logger.warning` + `exc_info=True` — `src/services/sync/activities.py:41-43`
- [ ] **OBS-04**: `except Exception: pass` при `client.close()` → `logger.warning` — `src/services/sync/activities.py:232-233`
- [ ] **OBS-05**: Analytics fetch failure → `exc_info=True` — `src/services/sync/health.py:106-107`
- [ ] **OBS-06**: Dashboard save failure → `exc_info=True` — `src/services/sync/health.py:50-51`
- [ ] **OBS-07**: Weather API errors — поднять с DEBUG на WARNING — `src/parsers/weather.py:48-49`
- [ ] **OBS-08**: `api/deps.py` — `get_logger` вместо `logging.getLogger` — `src/api/deps.py:23`
- [ ] **OBS-09**: Добавить лог успешного удаления temp file — `src/web/routes/uploads.py:130`
- [ ] **OBS-10**: Weight state reset при ошибке: пользователь не должен застревать в режиме ввода — `src/telegram/handlers/weight.py:98-101`

**Проверка:**
```bash
python -c "from src.utils.logger import get_logger; print('OK')"
# Проверить, что при битой БД приложение падает, а не продолжает
```

---

#### Sprint 16 — Config Consolidation (P1)

**Зачем:** Убрать «зоопарк» хардкоженных значений. Если аналитика будет добавлять свои константы в тот же хаос — получится не поддерживаемый код.

**Docker:** `app`

**Задачи:**
- [ ] **CFG-01**: Все хардкоды `max_hr=177` заменить на `settings.default_max_hr` / `constants.py` — `src/startup.py:35`, `src/services/reanalyze.py:56`, `src/models.py:20`, `src/domain/models/user.py:25`
- [ ] **CFG-02**: `HEALTH_SYNC_DAYS=180` — использовать вместо `days=120` — `src/services/sync/health.py:77`
- [ ] **CFG-03**: `settings.session_ttl_days` — использовать вместо `7*24*60*60` — `src/api/middleware.py:180`
- [ ] **CFG-04**: `settings.http_timeout` — использовать вместо `timeout=15` — `src/services/sync/utils.py:57`
- [ ] **CFG-05**: `Europe/Moscow` → `settings.timezone` с fallback `"UTC"` — `src/telegram/main.py:36,74`, `stats.py:27`, `sync.py:43`, `trainings.py:66` и др.
- [ ] **CFG-06**: `COROS_BASE_URL`, `COROS_AUTH_ENDPOINT`, `COROS_LOGIN_ENDPOINT`, `COROS_TRAINING_LIST` — из `src/config/constants.py` в `src/watch/coros.py`
- [ ] **CFG-07**: `password = '********'` sentinel → `None` (если у пользователя реально 8 звёздочек, он не может сменить пароль) — `src/services/watch_credentials.py:61`
- [ ] **CFG-08**: Удалить мёртвые поля `settings.session_ttl_days`, `settings.default_max_hr`, `settings.log_file`, `settings.http_timeout`, или начать их использовать
- [ ] **CFG-09**: `stats.py` — зоны пульса и пороги через `constants.py`, а не хардкод — `src/services/stats.py`

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
- [ ] **DI-01**: Alembic: nullable FK → `NOT NULL` + `ON DELETE CASCADE` для `user_id` во всех моделях — `src/domain/models/training.py`, `health.py`, `auth.py`, `audit.py`, `watch.py`
- [ ] **DI-02**: Alembic: `Text` → `JSON` для `sleep_hrv_interval_list` — `src/domain/models/health.py:37`
- [ ] **DI-03**: Alembic: `Text` → `JSON` для `audit.metadata_json` — `src/domain/models/audit.py:18`
- [ ] **DI-04**: `fit_parser.py`: `check_crc=True` (сейчас False — повреждённые файлы парсятся молча) — `src/parsers/fit_parser.py:14`
- [ ] **DI-05**: Cadence heuristic `cad < 100: cad * 2` → параметр бренда (Coros-specific в generic парсере) — `src/parsers/fit_parser.py:28-29`
- [ ] **DI-06**: Auth token: удалять expired+неиспользованные (сейчас только used+>1day) — `src/services/auth.py:116-126`
- [ ] **DI-07**: Input validation: file size (max 50MB), email regex, weight bounds (20–300 → 30–250) — `src/web/routes/uploads.py:28`, `src/telegram/handlers/start.py:41`, `src/telegram/handlers/weight.py:73`
- [ ] **DI-08**: `gps.py`: `sqrt(max(0, min(a, 1)))` — защита от negative float — `src/parsers/gps.py:11`
- [ ] **DI-09**: `hr_zones.py`: защита от `max_hr=0` (ZeroDivisionError) — `src/analysis/hr_zones.py:9`

**Проверка:**
```bash
alembic upgrade head    # миграции проходят
alembic downgrade -1    # откат работает
alembic upgrade head    # повторный накат идемпотентен
pytest tests/ -v        # тесты проходят
```

---

#### Sprint 18 — Architecture Cleanup (P1)

**Зачем:** Убрать дублирование кода, которое утроится при добавлении аналитики. Разбить файлы, превысившие лимит 400 строк (AGENTS.md п.1).

**Docker:** `app` + `bot`

**Задачи:**
- [ ] **ARC-01**: DRY: `auto_sync_health` + `auto_sync_activities` → одна параметризованная функция (~150 строк дубляжа) — `src/services/sync/orchestrator.py:83-238`
- [ ] **ARC-02**: DRY: `upload_files` / `confirm_upload` / `confirm_deleted` → общий session builder (тройной дубль) — `src/web/routes/uploads.py:92-248`
- [ ] **ARC-03**: DRY: rolling pace window (250м) в 3 местах → shared helper — `src/analysis/__init__.py:139-148,315-325`, `src/analysis/segment.py:103-104`
- [ ] **ARC-04**: DRY: km-chunking в 2 местах → shared helper — `src/analysis/segment.py:209-259,404-436`
- [ ] **ARC-05**: DRY: weather.py — `get_weather_code_at_time` + `get_temp_at_time` → один lookup — `src/parsers/weather.py:53-84`
- [ ] **ARC-06**: `segment.py` превысил 400 строк (фактически 436) → разбить — AGENTS.md п.1
- [ ] **ARC-07**: `analysis/__init__.py` (386, `process_trackpoints` ~200 строк) → разбить на pipeline
- [ ] **ARC-08**: Graceful shutdown: `scheduler.Event` для daemon thread, трекинг in-flight sync — `src/scheduler.py`, `src/web/routes/sync.py:35-36`
- [ ] **ARC-09**: `sys.path.insert` → `pip install -e .` — `run_telegram_bot.py:6`, `alembic/env.py:20`
- [ ] **ARC-10**: `stats.py`: HTML (`render_zone_bars`, `render_type_row`, `build_nav_html`) из сервисного слоя в Jinja2 — MVC нарушен — `src/services/stats.py:66-133`
- [ ] **ARC-11**: Dead code: `_get_progress_message`, `ValidationError` import, мёртвые константы settings — удалить
- [ ] **ARC-12**: Опечатка `'Окторябрь'` → `'Октябрь'` — `src/services/stats.py:8`

**Проверка:**
```bash
wc -l src/analysis/segment.py                                    # ≤ 400
wc -l src/analysis/__init__.py                                   # ≤ 400
grep -rn "Окторябрь" src/ | wc -l                                # → 0
grep -rn "except: pass" src/ | wc -l                             # → 0
```

---

#### Sprint 19 — Documentation & Types (P2)

**Зачем:** Привести документацию в соответствие с реальным кодом. Сейчас `ARCHITECTURE.md`, `CODE_GUIDELINES.md` и `AGENTS.md` противоречат друг другу и коду.

**Docker:** нет

**Задачи:**
- [ ] **DOC-01**: `docs/ARCHITECTURE.md` — полное обновление: SQLite → PostgreSQL, новая структура файлов, `src/analysis/`, `src/domain/`, `src/watch/`, `src/services/sync/`, `src/telegram/`
- [ ] **DOC-02**: `docs/CODE_GUIDELINES.md` — `CONFIG.*` → `settings.*` / `constants.*`; `src/models.py` → `src/domain/models/`; лимит 500 → 400 строк
- [ ] **DOC-03**: `docs/CHECKLIST_FEATURE.md` — 500 → 400 строк; `CONFIG` → `settings` / `constants`
- [ ] **DOC-04**: `src/parsers/__init__.py:1` — исправить комментарий (сейчас вводит в заблуждение)
- [ ] **DOC-05**: TypedDict для trackpoints и результата `process_trackpoints` — `src/analysis/`
- [ ] **DOC-06**: Type hints: `stats.py` (6 функций), `recovery_view.py` (4 функции), `deps.py` — добавить
- [ ] **DOC-07**: Bilingual-комментарии: `src/domain/models/user.py` (id, email, password_hash), `src/domain/models/training.py` (id, user_id в DeletedTraining/TrainingFeedback)
- [ ] **DOC-08**: `api/routes/health.py` — вынести импорты из тела функции на уровень модуля

**Проверка:**
```bash
grep -rn "CONFIG\.\|from src.config import CONFIG" docs/ | wc -l   # → 0
grep -rn "500 строк" docs/ | wc -l                                   # → 0
```

---

#### Sprint 20 — Tests (P2)

**Зачем:** Последний спринт перед аналитикой. Фундамент стабилен, конфиги едины, данные целы — теперь можно писать осмысленные тесты.

**Docker:** нет

**Задачи:**
- [ ] **TST-01**: `conftest.py` — переписать через `SessionLocal` из приложения (сейчас самодельный engine, не тестирующий реальную инфраструктуру) — `tests/conftest.py`
- [ ] **TST-02**: Реальные TCX/FIT-фикстуры — `tests/fixtures/`
- [ ] **TST-03**: `test_gps.py` — clean_trackpoints (норма, скачок, нереальный темп) — `tests/`
- [ ] **TST-04**: `test_classification.py` — interval, tempo, long, recovery — `tests/`
- [ ] **TST-05**: `test_segmentation.py` — км-блоки, сплит интервальной, short track — `tests/`
- [ ] **TST-06**: `test_hr_zones.py` — зоны, max_hr=0, None — `tests/`
- [ ] **TST-07**: `test_oscillation.py` — дописать edge cases (short phases, None HR) — `tests/`
- [ ] **TST-08**: `test_stats.py` — calc_stats, fmt_duration — `tests/`
- [ ] **TST-09**: `test_health.py` — GET /health/ — `tests/`
- [ ] **TST-10**: `helpers.py` — 5 builder-функций → 1 параметризованная — `tests/helpers.py`
- [ ] **TST-11**: `fixtures/README.md` — описание тестовых файлов — `tests/fixtures/`

**Проверка:**
```bash
pytest tests/ -v    # ≥ 30 тестов, все зелёные
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
─── ПОДГОТОВКА К АНАЛИТИКЕ ────────────────────────────────
Спринт 13 (P0)   — Security & Hardening                    🔴
Спринт 14 (P0)   — Thread Safety                            🔴
Спринт 15 (P0/P1)— Observability                            🟠
Спринт 16 (P1)   — Config Consolidation                     🟠
Спринт 17 (P1)   — Data Integrity                           ✅
Спринт 18 (P1)   — Architecture Cleanup (DRY, split)        🟠
Спринт 19 (P2)   — Documentation & Types                    🟡
Спринт 20 (P2)   — Tests                                    🟡
─── ПОСЛЕ АНАЛИТИКИ ───────────────────────────────────────
Модуль аналитики — 8 этапов                                 ⏸️
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
