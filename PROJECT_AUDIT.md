# PROJECT AUDIT — Running Coach

**Дата:** 03.07.2026 (аудит v3 — 13.07.2026; Фаза B — 13.07.2026; Фаза C — 13.07.2026)  
**Версия:** 3.1  
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

#### AUDIT-004 — `src/services/sync_service.py` God Object (518 строк)

**Файл:** `src/services/sync_service.py` (518 строк)

**Проблема:** Мешает:
- Activity sync
- Health sync
- Credential management
- Notification (telegram_notify)
- Dashboard data
- Audit events

**Решение:** Разбить по доменам:
```
src/services/
  sync_service.py     (только оркестрация: auto_sync_health, auto_sync_activities)
  sync_health.py      (sync_health_for_user, save_dashboard_data)
  sync_activities.py  (sync_activities_for_user)
  sync_utils.py       (get_activity_interval_seconds, get_health_interval_seconds,
                       _is_sync_due, _make_client)
```

**DoD:**
- [ ] `wc -l src/services/sync_service*.py` каждый < 200 строк

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

#### AUDIT-005 — `src/models.py` God Object (344 строки)

**Файл:** `src/models.py` (344 строки, 9+ моделей, 8 функций)

**Проблема:** Все ORM модели + вспомогательные функции в одном файле.

**Решение:** Разделить по доменам:
```
src/domain/models/
  __init__.py
  base.py            (Base, utcnow, get_engine, SessionLocal, get_db, init_db)
  user.py            (User)
  training.py        (TrainingSession, TrainingFeedback, DeletedTraining)
  watch.py           (WatchCredential)
  health.py          (DailyMetrics, WeightMeasurement)
  auth.py            (AuthToken, AuthEvent -> AuditEvent)
  audit.py           (AuditEvent)
```

**DoD:**
- [ ] `src/models.py` удалён или пустой
- [ ] Все импорты обновлены
- [ ] Alembic миграции работают
- [ ] Docker пересобран

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
- [ ] `grep -rn "COROS_SYNC" src/` → 0

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

### Спринт 8 — Чистка парсеров (1-2 дня) — P0 ✅

**Задачи:**
- [x] **AUDIT-001-1**: Создать `src/parsers/gps.py` — clean_trackpoints, haversine_m
- [x] **AUDIT-001-2**: Создать `src/parsers/weather.py` — fetch_weather, weather_icon
- [x] **AUDIT-001-3**: Создать `src/parsers/hr_zones.py` — get_zone, get_band, zone_ranges, calculate_hr_zones
- [x] **AUDIT-001-4**: Создать `src/parsers/classification.py` — классификация тренировок
- [x] **AUDIT-001-5**: Создать `src/parsers/segmentation.py` — сегментация трека
- [x] **AUDIT-001-6**: Создать `src/parsers/utils.py` — format_pace, format_duration, calc_elevation, find_timezone
- [x] **AUDIT-001-7**: `src/parsers/common.py` оставить только process_trackpoints (оркестратор)
- [x] **AUDIT-001-8**: Обновить импорты в tcx_parser.py, fit_parser.py
- [ ] **AUDIT-001-9**: `pytest` проходит, парсинг TCX/FIT работает (тесты пока отсутствуют)
- [x] **AUDIT-010**: Убрать `src/logger.py` shim, обновить импорты
- [x] **CHANGELOG.md** обновить

**Docker:** пересобрать `app`

---

### Спринт 9 — Разделение telegram_bot.py (1-2 дня) — P0 ⚠️ reopen

**Задачи:**
- [x] **AUDIT-002-1**: Создать `src/telegram/` пакет
- [x] **AUDIT-002-2**: `src/telegram/handlers/start.py` — регистрация
- [x] **AUDIT-002-3**: `src/telegram/handlers/sync.py` + `stats.py` + `trainings.py` + `weight.py` + `account.py`
- [x] **AUDIT-002-4**: `src/telegram/handlers/feedback.py` — feedback_callback
- [x] **AUDIT-002-5**: `src/telegram/jobs/weight.py` + `recovery.py`
- [x] **AUDIT-002-6**: `src/telegram/utils.py` — get_user, _get_web_app_url
- [x] **AUDIT-002-7**: `src/telegram/main.py` — run_bot, Application сборка
- [x] **AUDIT-002-8**: `src/telegram/sync_runner.py` — sync в отдельном треде
- [x] **AUDIT-002-9**: `src/telegram/state.py` — _awaiting_weight
- [x] **AUDIT-007**: Заменить прямой импорт `CorosWatchClient` на `get_watch_client()`
- [ ] **AUDIT-011**: Удалить `COROS_SYNC_*` константы из audit.py — *помечено выполнено, фактически нет*
- [x] `src/telegram_bot.py` удалён
- [x] `run_telegram_bot.py` обновлён на `from src.telegram import run_bot`
- [x] Все 12 файлов проходят py_compile — *py_compile недостаточен (см. AUDIT-015)*

> ⚠️ **Reopen:** Спринт помечен `✅`, но пакет невозможно импортировать — сломанные импорты (AUDIT-015). `py_compile` проверяет только синтаксис, не разрешение импортов. Проверка спринта должна быть **поведенческой**: импорт запускается, бот отвечает на `/start`.

**Docker:** пересобрать `bot`

---

### Спринт 10 — Тесты (2-3 дня) — P0

**Важно:** для тестов парсеров и классификации нужны **реальные данные тренировок**.
Использовать:
- TCX/FIT-файлы реальных тренировок от спортсменов (разные типы: интервальная, темповая, long run, recovery)
- Типичный тренировочный план (например, из открытых источников: Jack Daniels' VDOT, Pfitzinger, FIRST)
- Разные часы (Garmin, Coros, Polar) — чтобы проверить мульти-брендовость
- Крайние случаи: GPS-скачки, обрыв трека, пульс 0, короткая тренировка (<1 км)

Файлы складываются в `tests/fixtures/` с README-описанием каждой тренировки:
```
tests/fixtures/
  README.md            # описание: дата, тип, часы, дистанция, что проверяем
  interval_coros.tcx   # интервальная с Coros Pace 4
  tempo_garmin.tcx     # темповая с Garmin Forerunner 255
  long_run_polar.tcx   # long run с Polar Vantage
  recovery.tcx         # восстановительная, <5 км
  gps_spikes.fit       # FIT с GPS-скачками для clean_trackpoints
  short_walk.tcx       # короткая прогулка <1 км (проверка отбрасывания)
```

**Задачи:**
- [ ] **AUDIT-003-0**: Собрать тестовые TCX/FIT-файлы (TODO — приложить реальные тренировки от спортсменов или взять типичный тренировочный план)
- [ ] **AUDIT-003-1**: conftest.py — фикстуры (тестовая БД, user, session, sample data)
- [ ] **AUDIT-003-2**: test_gps.py — clean_trackpoints (норма, скачок, нереальный темп)
- [ ] **AUDIT-003-3**: test_classification.py — interval, tempo, long, recovery
- [ ] **AUDIT-003-4**: test_segmentation.py — км-блоки, сплит интервальной
- [ ] **AUDIT-003-5**: test_hr_zones.py — зоны, get_zone, get_band
- [ ] **AUDIT-003-6**: test_stats.py — calc_stats, fmt_duration
- [ ] **AUDIT-003-7**: test_health.py — GET /health/
- [ ] **AUDIT-003-8**: tests/fixtures/README.md — описание тестовых файлов
- [ ] **CHANGELOG.md** обновить

---

### Спринт 11 — Разделение models.py + sync_service (1-2 дня) — P1

**Задачи:**
- [ ] **AUDIT-005-1**: Создать `src/domain/` пакет
- [ ] **AUDIT-005-2**: `src/domain/models/base.py` — Base, utcnow, get_engine, SessionLocal, get_db, init_db
- [ ] **AUDIT-005-3**: `src/domain/models/user.py` — User
- [ ] **AUDIT-005-4**: `src/domain/models/training.py` — TrainingSession, TrainingFeedback, DeletedTraining
- [ ] **AUDIT-005-5**: `src/domain/models/watch.py` — WatchCredential
- [ ] **AUDIT-005-6**: `src/domain/models/health.py` — DailyMetrics, WeightMeasurement
- [ ] **AUDIT-005-7**: `src/domain/models/auth.py` — AuthToken
- [ ] **AUDIT-005-8**: `src/domain/models/audit.py` — AuditEvent
- [ ] **AUDIT-004-1**: Создать `src/services/sync_activities.py`
- [ ] **AUDIT-004-2**: Создать `src/services/sync_health.py`
- [ ] **AUDIT-004-3**: Создать `src/services/sync_utils.py`
- [x] **AUDIT-006**: Единый entry point `run_sync_for_user()` в sync_service.py (web; Telegram — TODO, обоснованно)
- [ ] Все импорты обновлены
- [ ] Alembic миграции работают
- [ ] Docker пересобран
- [ ] **CHANGELOG.md** обновить

---

### Спринт 12 — Чистка роутов + web (1 день) — P1

**Задачи:**
- [x] **AUDIT-009**: sync.py (444 → 93 строк)
- [x] **AUDIT-013**: pages.py (601 → пакет pages/, max 184 строк)
- [ ] **AUDIT-008**: Threading review — хотя бы зафиксировать known issues
- [ ] **CHANGELOG.md** обновить

---

### Спринт 13 — Фаза 3: Фильтры + статистика (1-2 дня) — Новая функциональность

**Задачи:**
- [ ] Фильтр по типу тренировки на главной (Все / Бег / Ходьба)
- [ ] Общая дистанция и время за неделю/месяц
- [ ] **CHANGELOG.md** обновить

---

### Спринт 14 — Фаза 4: Multi-brand onboarding (1-2 дня) — Новая функциональность

**Задачи:**
- [ ] Telegram /start — выбор бренда часов
- [ ] Coros — существующий флоу
- [ ] Polar/Garmin/Suunto — заглушка
- [ ] **CHANGELOG.md** обновить

---

### Спринт 15 — Фаза 5: Факторы самочувствия (2-3 дня) — Новая функциональность

**Задачи:**
- [ ] Константы (BUILTIN_FACTORS, FACTOR_INACTIVITY_DAYS)
- [ ] Модели (FeedbackFactor, UserActiveFactor)
- [ ] Сервис (feedback_service.py)
- [ ] Telegram — callback `factor:`
- [ ] Web — чекбоксы факторов в форме оценки
- [ ] Alembic миграция
- [ ] **CHANGELOG.md** обновить

---

### Спринт 7 (отложенный) — Admin panel (2-3 дня)

**Отложен** до появления >1 пользователя или до запуска модуля аналитики.

- [ ] **7.1** `src/models.py` — колонка `role` (String(20), default='user', значения: 'user', 'admin') в модель User + Alembic миграция. Установить `role='admin'` для user id=1.
- [ ] **7.2** `src/api/deps.py` — зависимость `get_admin_user`: проверяет `role == 'admin'`, иначе 403. Параллельно с `get_current_user`.
- [ ] **7.3** `src/api/routes/admin.py` — роутер с префиксом `/admin`, все эндпоинты под `Depends(get_admin_user)`.
- [ ] **7.4** `/admin` — дашборд: количество пользователей, тренировок, синхронизаций за день (агрегатные запросы по audit_events и таблицам).
- [ ] **7.5** `/admin/users` — список пользователей (id, email, telegram, дата регистрации, last_sync, is_active, role).
- [ ] **7.6** `/admin/audit` — просмотр audit_events с фильтром по пользователю/типу/дате.
- [ ] **7.7** `/admin/sync` — глобальный статус синхронизаций + принудительный sync для конкретного пользователя.
- [ ] **7.8** `/admin/users/{id}` — управление пользователем: ban/unban (is_active toggle), сброс пароля, просмотр тренировок и метрик.
- [ ] **7.9** Очистка старых данных: audit_events старше N дней, удалённые лог-файлы.

**Что уже есть:** `AuditEvent` + `AuditService`, `is_active` на User, `get_current_user`, `/health/` endpoint, `/logs` endpoint, per-user data isolation, индексы на audit_events.

**Дизайн:** встроенная HTML-страница `/admin` (как `/settings`, `/logs`), не отдельный фронтенд. Доступ через `get_admin_user`. User id=1 получает `role='admin'` при миграции.

---

### Модуль аналитики (8 этапов из decision_module_design.md)

- [ ] **Этап 0–7**: после всех спринтов

---

## 5. ПРИОРИТЕТЫ

```
Спринт 8  (P0) — parsers/common.py разбить + logger shim       ✅
Спринт 9  (P0) — telegram_bot.py разбить                        ✅
AUDIT-014      — Алгоритм сегментации (change-point detection)  ✅
Фаза A    (P0) — Починить Telegram-бот (сломанные импорты)      ✅
Фаза B    (P1) — Тонкие роуты + мульти-бренд settings           ✅
Фаза C    (P2) — Cleanup и унификация                            ✅
Спринт 10 (P0) — тесты (минимум 20)                             🔴 2-3 дня
Спринт 11 (P1) — models.py + sync_service разбить               🟠 1-2 дня
Спринт 12 (P1) — sync.py + pages.py чистка                      🟠 1 день
Спринт 13      — Фаза 3: фильтры + статистика                   🟢 1-2 дня
Спринт 14      — Фаза 4: multi-brand onboarding                  🟢 1-2 дня
Спринт 15      — Фаза 5: факторы самочувствия                    🟢 2-3 дня
Спринт 7       — Admin panel (отложено)                          ❄️ 2-3 дня
Модуль аналитики — 8 этапов                                      ❄️
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
      pages.py                    # GET /, /login, /register, /session/{id}, /settings
      uploads.py                  # POST /upload, /upload/confirm
      sync.py                     # POST /sync/{brand}/run, /sync/{brand}/health
      logs.py                     # GET /logs

  services/                       # Business logic (старый слой, но разделённый)
    sync_service.py               # оркестрация auto_sync
    sync_activities.py            # sync_activities_for_user
    sync_health.py                # sync_health_for_user, save_dashboard_data
    sync_utils.py                 # _is_sync_due, _make_client, интервалы
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

**Итого:** 15 спринтов (8 рефакторинг + 3 новые фичи + 1 админка + 3 модуль аналитики).  
Критические (P0): Спринты 8-10 — примерно 4-7 дней.

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

### Фаза D — Документация: good practices из «Бот_изучения_английского»

**D.1 Создать `BACKLOG.md`** — парковка идей/фиксов/вопросов с тегами `[Идея|Фикс|Вопрос]`. Правило: «Заметил мелочь — строка в BACKLOG, обратно к задаче. Не чини "заодно".»

**D.2 Создать `docs/CHECKLIST_NEW_PROVIDER.md`** — чеклист «новый бренд часов»: реализация в `src/watch/<brand>.py`, тот же ABC-метод, регистрация в `factory.py` (не `if/else`), ключ из config, smoke-test:
```bash
python -c "from src.watch.factory import get_watch_client; c = get_watch_client('coros'); print(type(c).__name__)"
```

**D.3 Усилить `AGENTS.md`** — добавить раздел «Дисциплина работы ИИ-агента» (по AGENTS.md референса):
- потолок ~400 строк/файл с обоснованием AI-поведения («модель дописывает в существующий файл; потолок этому противодействует»)
- backlog-дисциплина
- секреты («нет ключа — остановись и спроси, не выдумывай плейсхолдер»)
- проверка спринта — behavioral test, не `py_compile`
- таблица Docker rebuild (что изменено → что пересобрать)
- протокол конца сессии (commit → чекбоксы → отчёт)

**D.4 `PROJECT_AUDIT.md` правки:** AUDIT-011 уже возвращён в открытые (выполнено выше); Sprint 9 → reopen. Заморозить дальние спринты (13–15 + 7 + аналитика) как заголовки — детализировать только перед стартом (план не устареет).

**D.5 `README.md` правки:** секция «Парсеры» (≈стр. 35) — обновить список модулей; секция настроек — кадрировать как мульти-бренд после B.1; обновить дату; убрать дублирование roadmap/спринт-плана (sprint-трекинг — в PROJECT_AUDIT, README — product features).

---

### Порядок выполнения
1. **Фаза A** → проверка → коммит → отчёт → пауза (ждать разрешения на B)
2. **Фаза B** → проверка → коммит → отчёт → пауза
3. **Фаза C** → проверка → коммит → отчёт → пауза
4. **Фаза D** → проверка → коммит → итоговый отчёт
