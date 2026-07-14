# Контекст проекта Running Coach

## Суть
Персональный AI-тренер для бега. Парсит TCX-файлы (любые часы: Garmin, Coros, Polar, Suunto), анализирует тренировки, определяет тип (интервальная/темповая/long/recovery), разбивает на сегменты, считает пульсовые зоны, очищает GPS-ошибки.

## Стек
Python + FastAPI + PostgreSQL 16 (Docker Compose), написано через ИИ (open code style).
Сервер: Docker Compose — 3 контейнера (`db`, `app`, `bot`).
Локальная разработка: `docker compose up db -d && DATABASE_URL=postgresql://running_coach:<PASSWORD>@localhost:5432/running_coach uvicorn main:app --host 0.0.0.0 --port 8000`.

## Дисциплина работы ИИ-агента (AI Agent Discipline)

0. **Автономность спринта.** По завершении всех задач спринта и поведенческих проверок — выполнить протокол конца спринта (п.6) **автоматически**, без ожидания команды пользователя. Это overriding-правило для `NEVER commit unless asked` — для данного проекта протокол завершения спринта всегда включает коммит.

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

6. **Протокол завершения спринта.** После выполнения всех задач спринта и поведенческих проверок — автоматически выполнить без дополнительного запроса:
   - Отметить спринт как ✅ в `AGENTS.md` (секция «Текущее состояние»)
   - **Удалить выполненные пункты из «Следующие шаги»**
   - Обновить `CHANGELOG.md` (дата, список изменений)
   - `git add` + `git commit` с сообщением вида `Sprint N: <описание>`
   - `git push`
   - Сообщить пользователю: «Спринт N завершён, данные в AGENTS/CHANGELOG, коммит сделан, сессию можно закрывать»
   - Начать следующий спринт (если указан в «Следующие шаги»)

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
1. **Константы** — используй `from src.config import settings` / `from src.config.constants import NAME`. Никаких magic numbers.
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

## Текущее состояние (Session — 14.07.2026 — Sprint 17: Data Integrity)

**Фаза A ✅:** Починены сломанные импорты в `src/telegram/` (AUDIT-015), удалены `COROS_SYNC_*` константы (AUDIT-011).
**Фаза B ✅:** Тонкие роуты (sync.py 444→93), мульти-бренд settings, единый `run_sync_for_user`, пакет `pages/`.
**Фаза C ✅:** Cleanup: `requests`→`httpx`, удалены мёртвые зависимости, `CorosAPIError`→`WatchAPIError` (brand-agnostic).
**Фаза D ✅:** Документация: `BACKLOG.md`, `docs/CHECKLIST_NEW_PROVIDER.md`, усилен `AGENTS.md`.
**Модуль анализа ✅:** Новый пакет `src/analysis/` (классификация, сегментация, пульсовые зоны, утилиты).
**Алгоритм интервалов ✅:** `src/analysis/oscillation.py` — детекция по базовому темпу (easy pace) + HR-lag корреляция.
**Отладка анализа ✅:** Исправлены баги: base_pace self-defeating, HR-lag инверсия, time units, NameError. Добавлен умный fallback: км-блоки если сегменты похожи или число отлично от км. 40 тестов, 29 тренировок пересчитаны (27/29 ✓).
**Сегментация ✅:** Distance-based change points + адаптивный порог + защита oscillation-сегментов + km fallback для монотонных.
**Sprint 11 ✅:** Разбивка models.py на `src/domain/models/` (9 моделей, 7 файлов) + разбивка sync_service.py на `src/services/sync/` (4 модуля: utils, health, activities, orchestrator).

**Sprint 12 ✅:** Чистка роутов — `sync.py` (444→93 строк), `pages.py` разбит на пакет `pages/` (max 184 строк). `AUDIT-009` и `AUDIT-013` закрыты.

**Sprint 13 ✅:** Security & Hardening — SECRET_KEY без fallback, шифрование email (Fernet), PENDING_DIR → `uploads/pending`, Docker `USER appuser`, rate-limiting, CSRF (Origin/Referer), session fixation, `except:pass` устранены, `reload=True` убран.

**Sprint 14 ✅:** Thread Safety — `threading.Lock` на `_pending`, `_awaiting_weight`, `_engine`/`_maker`, `_fernet_cache`, logger cache; cleanup утечек `_pending`/`_awaiting_weight`; TOCTOU scheduler → `threading.Event`; deep copy `_auto_sync_status`.

**Sprint 15 ✅:** Observability — `fix_logger_after_uvicorn` для всех 3 логгеров; Alembic hard fail (`raise SystemExit(1)`); silent failures → `exc_info=True` (activities, health); `except: pass` → `logger.warning`; weather ошибки → WARNING; `get_logger` в api/deps.py; лог удаления temp-файлов; сброс `_awaiting_weight` при ошибке.

**Sprint 16 ✅:** Config Consolidation — `max_hr=177` → `settings.default_max_hr` (5 файлов); `days=120` → `HEALTH_SYNC_DAYS`; `7*24*60*60` → `settings.session_ttl_days`; `timeout=15` → `settings.http_timeout`; `Europe/Moscow` → `settings.timezone` (13 мест); удалены `COROS_*` из `constants.py`; удалён sentinel `'********'`; HR-зоны вынесены в `constants.py`; опечатка `Окторябрь` → `Октябрь`. 56 тестов зелёные.

**Sprint 17 ✅:** Data Integrity — nullable FK → NOT NULL + ON DELETE CASCADE (6 таблиц); Text→JSON для `sleep_hrv_interval_list` и `metadata_json`; `fit_parser.py`: `check_crc=True`, cadence workaround как `coros_cadence_workaround` параметр; `auth.py`: cleanup удаляет expired+неиспользованные токены; валидация ввода: размер файла ≤50MB, email regex, вес 30-250кг; защита `max_hr=0` и `sqrt(negative)` в gps.py. 53/53 тестов зелёные.

**Sprint 18 ✅:** Architecture Cleanup — DRY orchestrator (2 × 150 строк → 1 параметризованная `_auto_sync`), DRY uploads (общий `_save_session_from_data`), rolling pace window helper (compute_rolling_pace), km-chunking helper (`_chunk_by_km`), weather lookup DRY (`_get_nearest`). split segment.py (436→312) + segment_km.py (140). split analysis/__init__.py (387→227) — 6 helpers в utils.py (233). graceful shutdown (scheduler stop Event). pip install -e . вместо sys.path.insert (2 файла). HTML из stats.py в Jinja2 шаблоны (zone bars, nav). dead code cleanup (4 элемента). 56/56 тестов зелёные.

### Что сделано в сессии (14.07.2026) — Sprint 18 / Architecture Cleanup:

1. **ARC-01**: `src/services/sync/orchestrator.py` — `auto_sync_health` + `auto_sync_activities` → единая `_auto_sync(sync_type)` через `SYNC_CONFIG` словарь (~150 строк дубляжа убрано)
2. **ARC-02**: `src/web/routes/uploads.py` — общий `_save_session_from_data()` + `_notify_new_session()` + `_build_rating_keyboard()` — тройной дубль создания TrainingSession убран
3. **ARC-03**: `src/analysis/utils.py` — `compute_rolling_pace()` — rolling pace helper (250м окно), использован в `__init__.py` (2 места)
4. **ARC-04**: `src/analysis/segment_km.py` — `_chunk_by_km()` — km-chunking helper, использован в `compute_km_variability` + `km_segment_fallback`
5. **ARC-05**: `src/parsers/weather.py` — `_get_nearest()` — единый lookup для `get_weather_code_at_time` + `get_temp_at_time`
6. **ARC-06**: `src/analysis/segment.py` (436→312) + новый `src/analysis/segment_km.py` (140) — km-функции вынесены в отдельный модуль
7. **ARC-07**: `src/analysis/__init__.py` (387→227) — 6 helper-функций (`_interpolate_paces`, `_smooth_paces_for_oscillation`, `_build_hr_pace_series`, `_serialize_trackpoints`, `_is_km_segmentation`) вынесены в `src/analysis/utils.py` (233)
8. **ARC-08**: `src/scheduler.py` — `_stop = threading.Event()`, `stop()`, `_stop.wait()`; `src/startup.py` — `on_shutdown()` + `AutoSyncScheduler().stop()`
9. **ARC-09**: `run_telegram_bot.py` + `alembic/env.py` — `sys.path.insert` → `pip install -e .`
10. **ARC-10**: `src/services/stats.py` — `render_zone_bars` + `render_type_row` + `build_nav_html` → `get_zone_bars_data` + `get_nav_data` (данные, не HTML); `src/web/templates/index.html` — Jinja2 loops для зон + навигации
11. **ARC-11**: Dead code cleanup — `_get_progress_message` (sync.py), `ZONE_COLORS` (stats.py), `ValidationError` import (auth.py), `from datetime import timezone` (training_service.py)
12. **ARC-12**: Проверено: опечатка `Окторябрь` — уже исправлена в Sprint 16
13. Поведенческие проверки: импорты OK, `from src.database` → 0, `except:pass` → 0, Окторябрь → 0, 56/56 тестов зелёные, pip install -e . работает

### Что сделано в сессии (14.07.2026) — Sprint 17 / Data Integrity:

1. **DI-01**: `src/domain/models/training.py`, `health.py`, `audit.py` — `user_id` FK: `nullable=True` → `nullable=False`, добавлен `ondelete='CASCADE'`
2. **DI-02**: `src/domain/models/health.py` — `sleep_hrv_interval_list`: `Text` → `JSON`
3. **DI-03**: `src/domain/models/audit.py` — `metadata_json`: `Text` → `JSON`
4. **DI-04**: `src/parsers/fit_parser.py` — `check_crc=False` → `True`
5. **DI-05**: `src/parsers/fit_parser.py` — cadence heuristic `cad < 100: cad*2` → параметр `coros_cadence_workaround` (default `False` для generic, `True` в Coros sync)
6. **DI-06**: `src/services/auth.py` — `cleanup_expired_tokens()`: теперь удаляет **все** просроченные токены (а не только used + >1day)
7. **DI-07**: `src/web/routes/uploads.py` — проверка размера файла (≤50MB); `src/telegram/handlers/start.py` — email regex; `src/telegram/handlers/weight.py` — bounds 30-250кг
8. **DI-08**: `src/analysis/hr_zones.py` — защита `ZeroDivisionError` при `max_hr=0`
9. **DI-09**: `src/parsers/gps.py` — `sqrt(min(a, 1))` → `sqrt(max(0, min(a, 1)))` защита от negative float
10. **Alembic миграция `f7g8h9i0j1k2`** — удаление orphan-записей, NOT NULL + CASCADE, Text→JSON. Downgrade/upgrade идемпотентен.
11. Поведенческие проверки: импорты OK, `from src.database` → 0, `except:pass` → 0, 53/53 тестов зелёные, миграция применена

### Что сделано в сессии (13.07.2026) — модуль анализа:
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

### Что сделано в сессии (14.07.2026) — Sprint 12 / чистка роутов:
1. `web/routes/sync.py`: 444→93 строки (статус-трекинг вынесен в `web/state.py`, бизнес-логика в сервисы)
2. `web/routes/pages.py`: 601 строка разбита на пакет `pages/` (auth 48, index 184, session 177, settings 118)
3. `AGENTS.md` / `BACKLOG.md` / `PROJECT_AUDIT.md`: синхронизация с актуальным состоянием

### Что сделано в сессии (14.07.2026) — Sprint 13 / Security & Hardening:
1. `src/api/middleware.py`: SECRET_KEY без fallback (SEC-01)
2. `src/crypto.py`: safe_decrypt() для обратной совместимости; шифрование email (SEC-02)
3. `src/web/state.py`: PENDING_DIR → `uploads/pending` (SEC-03)
4. `Dockerfile` + `docker-compose.yml`: USER appuser, порт db убран, healthcheck (SEC-04)
5. `src/utils/rate_limit.py` (новый): in-memory rate limiter (SEC-05)
6. `src/api/routes/auth.py`: session fixation — clear перед login (SEC-06)
7. `src/api/middleware.py`: CSRFProtectMiddleware — проверка Origin/Referer (SEC-07)
8. `src/telegram/handlers/account.py`: except:pass → конкретные типы (SEC-08)
9. `main.py`: убран reload=True (SEC-09)
10. `AGENTS.md` / `CHANGELOG.md` / `BACKLOG.md`: обновление по протоколу конца спринта

### Что сделано в сессии (14.07.2026) — Sprint 15 / Observability:
1. **OBS-01**: `fix_logger_after_uvicorn()` — починена для всех 3 логгеров (app, requests, audit_file) через общий helper `_fix_single_logger()` — `src/utils/logger.py`
2. **OBS-02**: Alembic failure — `logger.exception` + `raise SystemExit(1)` (hard stop) — `src/startup.py`
3. **OBS-03**: Parse error в activities.py — `logger.warning` + `exc_info=True` — `src/services/sync/activities.py`
4. **OBS-04**: `except: pass` при `client.close()` → `logger.warning` с exc_info — `src/services/sync/activities.py`
5. **OBS-05**: Analytics fetch failure — `exc_info=True` — `src/services/sync/health.py`
6. **OBS-06**: Dashboard save failure — `exc_info=True` — `src/services/sync/health.py`
7. **OBS-07**: Weather API errors — подняты с DEBUG на WARNING — `src/parsers/weather.py`
8. **OBS-08**: `api/deps.py` — `logging.getLogger` → `get_logger("api.deps")` из проекта
9. **OBS-09**: Добавлен лог успешного удаления temp-файла — `src/web/routes/uploads.py`
10. **OBS-10**: Сброс `_awaiting_weight` при ошибке сохранения веса — пользователь не застревает — `src/telegram/handlers/weight.py`
11. Поведенческие проверки: импорты OK, `from src.database` → 0, `except:pass` → 0, 53/56 тестов зелёные

### Что сделано в сессии (14.07.2026) — Sprint 14 / Thread Safety:
1. **TS-01**: `threading.Lock` на `_pending` — `src/web/state.py`
2. **TS-02**: `threading.Lock` на `_awaiting_weight` — `src/telegram/state.py`
3. **TS-03**: Double-checked locking на `_engine`/`_maker` — `src/domain/models/base.py`
4. **TS-04**: Double-checked locking на `_fernet_cache` — `src/crypto.py`
5. **TS-05**: Double-checked locking на logger cache — `src/utils/logger.py`
6. **TS-06**: Cleanup stale `_pending` записей (TTL 1ч) + `_created` timestamp
7. **TS-07**: `clear_awaiting_weight()` при удалении пользователя — `src/telegram/handlers/account.py`
8. **TS-08**: Scheduler TOCTOU — `threading.Event` + `_lock` guard — `src/scheduler.py`
9. **TS-09**: `get_auto_sync_status_snapshot()` с `copy.deepcopy` — `src/services/sync/utils.py`
10. 56 тестов, все зелёные; Docker rebuild app + bot

### Что сделано в сессии (14.07.2026) — Sprint 16 / Config Consolidation:
1. **CFG-01**: `startup.py`, `reanalyze.py`, `models.py`, `tcx_parser.py`, `fit_parser.py` — `max_hr=177` → `settings.default_max_hr`
2. **CFG-02**: `health.py` — `days=120` → `HEALTH_SYNC_DAYS=180`
3. **CFG-03**: `middleware.py` — `7*24*60*60` → `settings.session_ttl_days * 24 * 60 * 60`
4. **CFG-04**: `sync/utils.py` — `timeout=15` → `settings.http_timeout`
5. **CFG-05**: 13 файлов — `Europe/Moscow` → `settings.timezone` (UTC по умолчанию)
6. **CFG-06**: `constants.py` — удалены неиспользуемые `COROS_*` константы
7. **CFG-07**: `watch_credentials.py` — удалён sentinel `'********'`
8. **CFG-08**: Начато использование `default_max_hr`, `http_timeout`, `session_ttl_days`
9. **CFG-09**: `constants.py` — добавлены `HR_ZONE_*_MAX_PCT`; `stats.py` + `hr_zones.py` — пороги через константы; опечатка `Окторябрь` → `Октябрь`
10. Поведенческие проверки: импорты OK, `from src.database` → 0, `except:pass` → 0, `Europe/Moscow` → только комментарии, 56/56 тестов зелёные

### Коммиты:
- `cda4a0a` Sprint 8+9: разбивка parsers/common.py и telegram_bot.py на пакеты
- `3b4dd34` fix segmentation and tcx_parser import
- `f1a60fa` feat: модуль анализа + новый алгоритм детекции интервалов
- `99be684` fix: отладка и улучшение алгоритма анализа (40 тестов, 29 тренировок пересчитаны)
- (текущий) Sprint 17: Data Integrity — NOT NULL FKs, cascade, JSON, валидация

### Следующие шаги (подготовка к модулю аналитики):
Порядок выполнения — строго последовательный. Каждый спринт = behavioral test + CHANGELOG + commit.
- **Sprint 19** (Documentation & Types): ARCHITECTURE.md, CODE_GUIDELINES.md, TypedDicts, type hints
- **Sprint 20** (Tests): conftest, fixtures, ≥30 тестов

🚀 **После Sprint 20** — модуль аналитики (8 этапов из `decision_module_design.md`).

❄️ Заморожено (после аналитики): фильтры, multi-brand onboarding, факторы самочувствия, admin panel.

### Команды управления:
```bash
./bin/docker.sh up -d        # запуск
./bin/docker.sh down          # остановка
./bin/docker.sh build app     # пересборка app
./bin/docker.sh build bot     # пересборка bot
python3 -m alembic upgrade head  # миграции
```
