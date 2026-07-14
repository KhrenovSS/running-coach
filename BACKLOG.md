# BACKLOG — Running Coach

Парковка идей, фиксов и вопросов.  
**Правило:** заметил мелочь → строка сюда, обратно к задаче. Не чини «заодно».

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 1 | [Фикс] | AUDIT-006 Telegram TODO: `sync_runner.py` вызывает `sync_activities_for_user`/`sync_health_for_user` напрямую вместо `run_sync_for_user`. Миграция на `run_sync_for_user_all_brands(chat_id)`. | `src/telegram/sync_runner.py:8-12` | ⬜ Sprint 12b |
| 2 | [Фикс] | AUDIT-003: Тестовое покрытие практически отсутствует (3 теста, 63 строки). Нужно ≥20 тестов. | `tests/` | ⬜ Sprint 10 (возобновлён) |
| 3 | [Фикс] | AUDIT-004: `sync_service.py` God Object (702 строки). Разбить на sync_service + sync_health + sync_activities + sync_utils. | `src/services/sync_service.py` | ✅ Sprint 11 |
| 4 | [Фикс] | AUDIT-005: `models.py` God Object (344 строки, 9+ моделей). Разделить по доменам в `src/domain/models/`. | `src/models.py` | ✅ Sprint 11 |
| 5 | [Фикс] | AUDIT-008: Threading + asyncio anti-pattern. Scheduler — daemon thread, sync_service — `asyncio.run()` внутри синхронных функций. Планируется выделение sync в отдельный процесс. | `src/scheduler.py`, `src/services/sync_service.py` | ⬜ Отложено |
| 6 | [Фикс] | AUDIT-012: Type hints не везде. `mypy src/ --strict` не проходит. | Весь `src/` | ⬜ Отложено |
| 7 | [Фикс] | AUDIT-014: Сегментация привязана к км-блокам — `segment_by_km()` не работает для коротких интервалов (10×200м+600м). Замена на `segment_by_pace()`. | `src/parsers/segmentation.py` | ✅ Выполнено |
| 8 | [Идея] | Sprint 7: Admin panel — дашборд, управление пользователями, просмотр аудита, принудительный sync. Отложено до >1 пользователя. | PROJECT_AUDIT.md | ⬜ Отложено |
| 9 | [Идея] | Модуль аналитики — 8 этапов (Этап 0–7): каркас, аналитика, движок, база знаний, персонализация, LLM, планы, обратная связь. | `decision_module_design.md` | ⬜ Отложено |
| 10 | [Идея] | Фильтр по типу тренировки на главной, общая дистанция/время за неделю/месяц. | PROJECT_AUDIT.md | ⬜ Заморожено (после аналитики) |
| 11 | [Идея] | Sprint 14: Multi-brand onboarding — выбор бренда при `/start`, заглушки для Polar/Garmin/Suunto. | PROJECT_AUDIT.md | ⬜ Sprint 14 (заморожен) |
| 12 | [Идея] | Sprint 15: Факторы самочувствия — multi-select (ноги, дыхание, пульс, жара, недосып, стресс), адаптивные подсказки, хранение для аналитики. | PROJECT_AUDIT.md | ⬜ Sprint 15 (заморожен) |
| 13 | [Идея] | Мобильное PWA (Progressive Web App). | README.md | ⬜ Идея |
| 14 | [Фикс] | `docs/ARCHITECTURE.md` устарел: описывает SQLite, `src/logger.py`, `src/telegram_bot.py`, не описывает `src/watch/`, `src/telegram/`, `src/services/`. | `docs/ARCHITECTURE.md` | ⬜ Sprint 12b |
| 15 | [Вопрос] | AUDIT-008: выделять ли sync в отдельный процесс/контейнер или оставить `run_async_in_thread`? | `src/services/sync_service.py` | ⬜ Вопрос |
| 16 | [Фикс] | Telegram `sync_runner.py`: нужен `run_sync_for_user_all_brands(chat_id)` для объединения отчёта по всем брендам. | `src/telegram/sync_runner.py` | ⬜ Sprint 12b |
| 17 | [Фикс] | Добавить `docs/ARCHITECTURE.md`: описание `src/analysis/` пакета (oscillation, classify, segment, hr_zones, utils) и пайплайна `process_trackpoints()`. | `docs/ARCHITECTURE.md` | ⬜ Sprint 12b |
| 18 | [Фикс] | Добавить unit-тесты для `src/analysis/oscillation.py`: `detect_pace_oscillations` + `compute_hr_lag_correlation` на синтетических данных. | `tests/` | ⬜ Sprint 10 (возобновлён) |
| 19 | [Фикс] | Обновить `docs/ARCHITECTURE.md`: описание нового алгоритма детекции интервалов (base_pace = средний темп, work-фаза = темп ≥ порог быстрее base_pace). | `docs/ARCHITECTURE.md` | ⬜ Sprint 12b |
| 20 | [Фикс] | Chart.js: темп на графике показывать в формате М:СС (мин:сек) вместо десятичных минут. Например 5.71 → 5:43. Добавить tooltip/label callback + форматирование оси Y. Пульс округлить до целого. | `src/web/templates/session.html:96-115` | ⬜ Sprint 12b |
| 21 | [Фикс] | Weight save через Telegram: "Ошибка при сохранении веса". Decimal→Float, tz-aware, отсутствие traceback, отсутствие метода `log_telegram_received()` в AuditService, `run_once` c `dt_time` вместо `timedelta`. | `src/telegram/handlers/weight.py:89-103`, `src/services/audit.py`, `src/telegram/main.py:77` | ✅ Выполнено |
| 139 | [Фикс] | CRC-ошибка в uploads.py вызывает 500 вместо информирования пользователя + добавление в parse_errors. Нужен try-except вокруг parse_fit/parse_tcx. | `src/web/routes/uploads.py:55-64` | ⬜ Sprint 18 |

---

*Обновлён: 14.07.2026 — Sprint 15 (Observability): 10 пунктов закрыты*

---

## 🔴 P0 — Критично (блокирует внедрение модуля аналитики)

### Security

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 22 | [Security] | **Хардкод `SECRET_KEY="dev-secret-key-change-in-production"`** — любой может подделать session-cookie. Прямое нарушение AGENTS.md п.3. Убрать дефолт, требовать через `os.getenv` без fallback. | `src/api/middleware.py:27` | ⬜ P0 |
| 23 | [Security] | **Email в plaintext в колонке `encrypted_user`** — имя вводит в заблуждение. Либо шифровать email, либо переименовать колонку в `plain_user`/`email`. | `src/services/sync/utils.py:57`, `src/services/watch_credentials.py:54` | ⬜ P0 |
| 24 | [Security] | **`PENDING_DIR = /tmp/running_coach_uploads`** — мирно-читаемая директория. GPS/HR данные пользователей доступны любому локальному юзеру. Переместить в `uploads/` или `/var/run/`. | `src/web/state.py:6` | ⬜ P0 |
| 25 | [Security] | **Docker: контейнер от root** — нет `USER` директивы. Любая эксплуатация даёт полный доступ к контейнеру. | `Dockerfile` | ⬜ P0 |
| 26 | [Security] | **PostgreSQL порт 5432 наружу** в docker-compose. Должен быть только для внутренней сети. | `docker-compose.yml:6` | ⬜ P0 |
| 27 | [Security] | **Нет rate-limiting на логин/регистрацию** — brute-force паролей без блокировки. | `src/api/routes/auth.py:71,117` | ⬜ P0 |
| 28 | [Security] | **Session fixation** — нет регенерации session ID после логина. | `src/api/routes/auth.py:53-54,99-100,172-173` | ⬜ P0 |
| 29 | [Security] | `MD5(password)` в `coros.py` — это reverse-engineered протокол Coros, не наша вина, но стоит документировать риск. | `src/watch/coros.py:39` | ⬜ P0 |

### Race Conditions

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 30 | [Race] | **`_pending` dict без блокировки** — `_sync_tasks` уже с `_sync_tasks_lock`, а `_pending` без. Data race при конкуррентных аплоадах. | `src/web/state.py:9` | ⬜ P0 |
| 31 | [Race] | **`_awaiting_weight` без блокировки** — голый dict между хендлерами и jobs. | `src/telegram/state.py:1` | ⬜ P0 |
| 32 | [Race] | **`_engine` и `_maker` без синхронизации** — double-checked locking anti-pattern при старте в многопоточном uvicorn. | `src/domain/models/base.py:32-67` | ⬜ P0 |
| 33 | [Race] | **`_fernet_cache` без lock** — два треда могут создать два Fernet-инстанса. | `src/crypto.py:34-36,50` | ⬜ P0 |
| 34 | [Race] | **Logger cache без lock** — `_app_logger`, `_requests_logger`, `_audit_file_logger` checked-then-set без синхронизации. | `src/utils/logger.py:171-194` | ⬜ P0 |
| 35 | [Race] | **`_pending` в uplods.py / sync.py** без локи — доступ из нескольких тредов. | `src/web/routes/uploads.py:70,152,211`, `src/web/routes/sync.py:32` | ⬜ P0 |

### Silent Failures

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 36 | [Silent] | **Alembic migration failure** → `logger.error` и continue. База может быть в неконсистентном состоянии, а приложение стартует. Нужен hard fail. | `src/startup.py:24-25` | ✅ Sprint 15 |
| 37 | [Silent] | **`except Exception: pass` при `client.close()`** — ошибки закрытия клиента съедаются без следа. | `src/services/sync/activities.py:232-233` | ✅ Sprint 15 |
| 38 | [Silent] | **Parse errors → return None** без traceback. Любая ошибка парсинга становится «не доступно». | `src/services/sync/activities.py:41-43` | ✅ Sprint 15 |
| 39 | [Silent] | **Weather API errors silenced на DEBUG уровне** — в production погода падает молча, без признаков в логе. | `src/parsers/weather.py:48-49` | ✅ Sprint 15 |
| 40 | [Silent] | **Analytics fetch failure** — `except Exception` → `logger.warning` без exc_info. | `src/services/sync/health.py:106-107` | ✅ Sprint 15 |
| 41 | [Silent] | **Dashboard save failure** — `except Exception` → `logger.warning` без exc_info. | `src/services/sync/health.py:50-51` | ✅ Sprint 15 |

### Dead / Broken Code

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 42 | [Dead] | **`src/parsers/common.py` отсутствует** — файл, упомянутый в документации, не существует. Спринт 8 «parsers разбиты» не завершён. | `src/parsers/common.py` | ⬜ P0 |
| 43 | [Dead] | **`_get_progress_message()` нигде не вызывается** — мёртвый код. | `src/telegram/handlers/sync.py:15-18` | ⬜ P0 |
| 44 | [Dead] | **`ValidationError` импортирован, не используется** в auth routes. | `src/api/routes/auth.py:24` | ⬜ P0 |

### Unbounded Growth / Memory

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 45 | [Memory] | **`_weather_cache` без TTL / лимита** — каждая уникальная (lat,lon,date) остаётся в памяти навсегда. | `src/parsers/weather.py:7` | ⬜ P0 |
| 46 | [Memory] | **`_pending` / `_sync_tasks` без cleanup** — записи копятся вечно после завершения задач. | `src/web/state.py:9-10` | ⬜ P0 |
| 47 | [Memory] | **`_awaiting_weight` без cleanup** — при удалении пользователя запись остаётся. | `src/telegram/state.py:1` | ⬜ P0 |
| 48 | [Memory] | **`all_sessions = db.query(...).all()` без пагинации** — все сессии пользователя в память. | `src/web/routes/pages/index.py:24` | ⬜ P0 |
| 49 | [Memory] | **N+1: загружаются ВСЕ `begin_ts` и `DeletedTraining`** — OOM при тысячах тренировок. | `src/services/sync/activities.py:85-86` | ⬜ P0 |

---

## 🟠 P1 — Важно (желательно закрыть до аналитики)

### Code Duplication

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 50 | [DRY] | **`auto_sync_health` и `auto_sync_activities` идентичны на 95%** (~150 строк дубляжа). В аналитике будет ещё `auto_sync_analytics` — утроится. Вынести в одну параметризованную функцию. | `src/services/sync/orchestrator.py:83-238` | ⬜ P1 |
| 51 | [DRY] | **Троекратное дублирование создания TrainingSession** в `upload_files`, `confirm_upload`, `confirm_deleted`. | `src/web/routes/uploads.py:92-106,161-174,235-248` | ⬜ P1 |
| 52 | [DRY] | **Rolling pace window (250м) в трёх местах** — `__init__.py` (2 раза) + `segment.py`. | `src/analysis/__init__.py:139-148,315-325`, `src/analysis/segment.py:103-104` | ⬜ P1 |
| 53 | [DRY] | **Km-chunking logic в `_compute_km_variability` и `_km_segment_fallback`** — идентичные циклы разбора трека на км-блоки. | `src/analysis/segment.py:209-259,404-436` | ⬜ P1 |
| 54 | [DRY] | **Nearest-time lookup в weather.py** — `get_weather_code_at_time` и `get_temp_at_time` почти идентичны. | `src/parsers/weather.py:53-84` | ⬜ P1 |
| 55 | [DRY] | **Inline keyboard в uploads.py** — одинаковая клавиатура строится 3 раза. | `src/web/routes/uploads.py:109-122,176-188,249-262` | ⬜ P1 |
| 56 | [DRY] | **`user.name or user.telegram_username or "Бегун"`** повторяется в api/routes/auth.py как минимум 3 раза. | `src/api/routes/auth.py:54,100,173` | ⬜ P1 |
| 57 | [DRY] | **HTML в сервисном слое** — `render_zone_bars`, `render_type_row`, `build_nav_html` генерируют строки HTML в stats.py. Аналитика повторит этот паттерн. | `src/services/stats.py:66-133` | ⬜ P1 |

### Logging / Observability

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 58 | [Log] | **`fix_logger_after_uvicorn()` чинит только "app" логгер** — `requests_logger` и `audit_file_logger` остаются с мёртвыми хендлерами после uvicorn dictConfig. Логирование запросов и аудита молча перестаёт работать. | `src/utils/logger.py:232` | ✅ Sprint 15 |
| 59 | [Log] | **Нет логирования успешного удаления temp file** — на линии 130 в `uploads.py` нет лога в отличие от линии 58. | `src/web/routes/uploads.py:130` | ✅ Sprint 15 |
| 60 | [Log] | **`api/deps.py` использует `logging.getLogger` вместо `get_logger`** — сообщения не получают структурированного форматирования и ротации. | `src/api/deps.py:23` | ✅ Sprint 15 |

### Data Integrity

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 61 | [DB] | **`user_id` nullable FK во всех моделях** — orphan-записи при удалении пользователя. Нужна миграция на NOT NULL + cascade delete. | `src/domain/models/training.py:13`, `health.py:15`, и др. | ⬜ P1 |
| 62 | [DB] | **`sleep_hrv_interval_list` типа `Text`** вместо `JSON` — потеря автоматической сериализации. | `src/domain/models/health.py:37` | ⬜ P1 |
| 63 | [DB] | **`audit.metadata_json` типа `Text`** вместо `JSON` — то же самое. | `src/domain/models/audit.py:18` | ⬜ P1 |
| 64 | [DB] | **`fit_parser.py: check_crc=False`** — повреждённые FIT-файлы парсятся молча. | `src/parsers/fit_parser.py:14` | ⬜ P1 |
| 65 | [DB] | **Cadence heuristic `cad < 100: cad * 2`** — Coros-specific логика в generic FIT-парсере. | `src/parsers/fit_parser.py:28-29` | ⬜ P1 |
| 66 | [DB] | **Auth token cleanup не удаляет expired-неused** — удаляются только used + >1 day. Expired, но неиспользованные токены копятся. | `src/services/auth.py:116-126` | ⬜ P1 |

### Config Debt (~20 мест с хардкодом вместо констант)

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 67 | [Config] | `max_hr=177` хардкодом в `startup.py:35`, `reanalyze.py:56`, `models.py:20`, `user.py:25`, `conftest.py` — вместо `constants.py`/settings. | `src/startup.py`, `src/services/reanalyze.py`, `src/models.py`, `src/domain/models/user.py` | ⬜ P1 |
| 68 | [Config] | `HEALTH_SYNC_DAYS=180` в `constants.py` — но `sync/health.py` использует `timedelta(days=120)`. | `src/services/sync/health.py:77` | ⬜ P1 |
| 69 | [Config] | `settings.session_ttl_days` существует, но в `middleware.py` хардкод `7*24*60*60`. | `src/api/middleware.py:180` | ⬜ P1 |
| 70 | [Config] | `settings.http_timeout` существует, но `sync/utils.py` хардкодит `timeout=15`. | `src/services/sync/utils.py:57` | ⬜ P1 |
| 71 | [Config] | `settings.default_max_hr` не используется нигде. | `src/config/settings.py:12` | ⬜ P1 |
| 72 | [Config] | `settings.log_file` не используется — логгер использует `LOGS_DIR`. | `src/config/settings.py:15` | ⬜ P1 |
| 73 | [Config] | **Поле `password` со значением `'********'` как sentinel** — если у пользователя реально пароль `********`, он никогда не сможет обновить креды. | `src/services/watch_credentials.py:61` | ⬜ P1 |
| 74 | [Config] | **`Europe/Moscow` хардкодом** в 6+ файлах telegram/ — для мульти-таймзоны нужно из settings. | `src/telegram/main.py:36,74`, `stats.py:27`, `sync.py:43`, `trainings.py:66` и др. | ⬜ P1 |
| 75 | [Config] | **`COROS_BASE_URL` и `COROS_*` константы** в глобальном `constants.py` — должны быть в `watch/coros.py`, а не в глобальном config. | `src/config/constants.py:17-22` | ⬜ P1 |
| 76 | [Config] | **Поле `upload_dir` в settings не используется** — `startup.py` хардкодит `"uploads"`. | `src/startup.py:72` | ⬜ P1 |

### Input Validation

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 77 | [Validation] | **Нет проверки размера файла** при upload — multi-GB файл заполнит диск. | `src/web/routes/uploads.py:28` | ⬜ P1 |
| 78 | [Validation] | **Только расширение файла проверяется** — `.exe` переименованный в `.tcx` пройдёт. | `src/web/routes/uploads.py:40` | ⬜ P1 |
| 79 | [Validation] | **Email validation: только `@` и `.`** — `a@b` проходит. | `src/telegram/handlers/start.py:41` | ⬜ P1 |
| 80 | [Validation] | **Weight range 20-300 — слишком широко** — 19.9 кг проходит. | `src/telegram/handlers/weight.py:73` | ⬜ P1 |
| 81 | [Validation] | **Нет rate-limiting на upload/settings/logs** — уязвимость к abuse. | `src/web/routes/uploads.py`, `settings.py`, `logs.py` | ⬜ P1 |

### Architectural

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 82 | [Arch] | **`src/analysis/segment.py` превышает 400 строк** (фактически 436) — нарушение правила AGENTS.md. | `src/analysis/segment.py` | ⬜ P1 |
| 83 | [Arch] | **`src/analysis/__init__.py` почти на 400 строках** — `process_trackpoints` ~200 строк, пора разбивать. | `src/analysis/__init__.py` | ⬜ P1 |
| 84 | [Arch] | **`render_page` в index.py — 155 строк** с SQL-запросами, HTML, JSON, логикой. Нарушение «тонкие роуты». | `src/web/routes/pages/index.py:23` | ⬜ P1 |
| 85 | [Arch] | **`upload_files` — 116 строк** с DB операциями, Telegram нотификациями, файловым IO. | `src/web/routes/uploads.py:28-143` | ⬜ P1 |
| 86 | [Arch] | **`sys.path.insert` в 2 местах** — `run_telegram_bot.py` и `alembic/env.py`. Нужно `pip install -e .`. | оба файла | ⬜ P1 |
| 87 | [Arch] | **`run_async_in_thread` создаёт новый event-loop на каждый вызов** — частая синхронизация = GC pressure. Нужен пул. | `src/services/async_utils.py:14` | ⬜ P1 |
| 88 | [Arch] | **Нет graceful shutdown** — `scheduler.py` daemon thread без `Event`, при рестарте теряются in-flight sync. | `src/scheduler.py`, `src/web/routes/sync.py:35-36` | ⬜ P1 |
| 89 | [Arch] | **`get_db()` телеграм хендлеры выдёргивают через `next(get_db())`** — хак вместо FastAPI DI, сломается при рефакторинге. | `src/telegram/utils.py:10` | ⬜ P1 |
| 90 | [Arch] | **3-4 отдельных DB session per telegram handler** — `get_user` + свой `SessionLocal()` = лишние коннекты. | `src/telegram/handlers/stats.py:25` и др. | ⬜ P1 |

---

## 🟡 P2 — Желательно

### Documentation

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 91 | [Docs] | **`docs/ARCHITECTURE.md` полностью устарел** — SQLite, старые пути, нет `src/analysis/`, `src/domain/`, `src/watch/`. | `docs/ARCHITECTURE.md` | ⬜ P2 |
| 92 | [Docs] | **`docs/CODE_GUIDELINES.md` ссылается на `CONFIG` (которого нет)** и старые пути. | `docs/CODE_GUIDELINES.md` | ⬜ P2 |
| 93 | [Docs] | **`src/parsers/__init__.py:1` вводит в заблуждение** — пишет «модули вынесены в src/analysis/», хотя парсеры всё ещё в parsers/. | `src/parsers/__init__.py` | ⬜ P2 |
| 94 | [Docs] | **`CHANGELOG.md` — 1161 строк без оглавления**, нет стандартного формата дат, дублирующиеся записи. | `CHANGELOG.md` | ⬜ P2 |

### Type Hints

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 95 | [Types] | **`stats.py` — все 6 функций без type hints**. | `src/services/stats.py` | ⬜ P2 |
| 96 | [Types] | **`recovery_view.py` — все 4 функции без type hints**. | `src/services/recovery_view.py` | ⬜ P2 |
| 97 | [Types] | **`deps.py` — `user`, `session` без аннотаций**. | `src/deps.py:10` | ⬜ P2 |
| 98 | [Types] | **Trackpoints = `list[dict]` везде вместо TypedDict** — ключи документально нигде не зафиксированы. | весь `analysis/` и `parsers/` | ⬜ P2 |
| 99 | [Types] | **`analysis/__init__.py` возвращает `dict | None` — структура результата нигде не описана типом**. | `src/analysis/__init__.py` | ⬜ P2 |

### Code Quality

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 100 | [Bug] | **`suspect_flags` ставится ТОЛЬКО когда `cleaning_log` пуст** — инвертированная логика. | `src/analysis/__init__.py:235-236` | ⬜ P2 |
| 101 | [Bug] | **`format_pace` может выдать `6:60`** — `int()` truncation вместо `round()`. | `src/analysis/utils.py:19` | ⬜ P2 |
| 102 | [Bug] | **`sqrt(min(a, 1))` — если `a < 0` (floating point), падение**. | `src/parsers/gps.py:11` | ⬜ P2 |
| 103 | [Bug] | **`save_dashboard_data` вызывается дважды** при пустом `metrics_list` — или баг, или лишний вызов. | `src/services/sync/health.py:81-83,181` | ⬜ P2 |
| 104 | [Bug] | **Start_time в TCX: `'' or None` → `AttributeError`** при replace, если оба отсутствуют. | `src/parsers/tcx_parser.py:23-24` | ⬜ P2 |
| 105 | [Bug] | **FIT: `cad < 100: cad * 2` — legitimate 80 spm (walking) → 160**. | `src/parsers/fit_parser.py:28-29` | ⬜ P2 |
| 106 | [Bug] | **FIT: `enhanced_altitude=0 or data.get('altitude')` — 0 (valid) трактуется как falsy**. | `src/parsers/fit_parser.py:26` | ⬜ P2 |
| 107 | [Bug] | **Haversine: `sqrt(min(a, 1))` — если `a < 0` (float error), падение**. | `src/parsers/gps.py:11` | ⬜ P2 |
| 108 | [Bug] | **Oscillation: `avg_pace = 0/1 = 0.0` при пустом slice** — silent data corruption. | `src/analysis/oscillation.py:89` | ⬜ P2 |
| 109 | [Bug] | **Oscillation HR-lag: mismatch time scales** — `pace_change` за 1 шаг, `hr_change` за `lag_sec`. | `src/analysis/oscillation.py:182-190` | ⬜ P2 |
| 110 | [Bug] | **`hr_zones.get_zone()`: `ZeroDivisionError` при `max_hr=0`** — нет валидации. | `src/analysis/hr_zones.py:9` | ⬜ P2 |
| 111 | [Bug] | **Сегментация O(n^2)** — while loop по trackpoints для rolling window при равных dist. | `src/analysis/segment.py:103-104` | ⬜ P2 |
| 112 | [Bug] | **Сегментация: `max_credible_upper=15.0` хардкодом** — не из конфига. | `src/analysis/segment.py:111` | ⬜ P2 |
| 113 | [Bug] | **Сегментация: `count_off_osc = len(osc) < num_kms * 0.5` — предел 50-150% слишком широк**. | `src/analysis/segment.py:370-371` | ⬜ P2 |
| 114 | [Bug] | **Sync audit: `log_sync_completed` вызывается внутри per-cred цикла, передаёт cumulative totals** — искажение per-brand статистики. | `src/telegram/sync_runner.py:84-90` | ⬜ P2 |
| 115 | [Bug] | **`cmd_delete_me` — немедленное удаление без подтверждения**. | `src/telegram/handlers/account.py:28-33` | ⬜ P2 |
| 116 | [Bug] | **Пароль показывается в plaintext в Telegram** — self-deleting, но может засветиться в нотификациях. | `src/telegram/handlers/account.py:121-127` | ⬜ P2 |
| 117 | [Bug] | **`handle_weight_message` — catch-all для всех не-командных сообщений** — любой текст в неудачный момент попытается стать weight. | `src/telegram/main.py:68` | ⬜ P2 |
| 118 | [Bug] | **Weight state не сбрасывается при ошибке** — пользователь застревает в режиме ввода веса. | `src/telegram/handlers/weight.py:98-101` | ✅ Sprint 15 |
| 119 | [Bug] | **`/logs` endpoint без аутентификации** + path traversal (хотя `os.path.join` немного защищает). | `src/web/routes/logs.py:10` | ⬜ P2 |
| 120 | [Bug] | **`/logs` уровень детекции по подстроке** — слово `"WARNING"` в сообщении даёт неверный CSS. | `src/web/routes/logs.py:40-41` | ⬜ P2 |
| 121 | [Bug] | **`/health` всегда 200, даже при `degraded`** — маскирует проблемы от load balancer. | `src/api/routes/health.py:92` | ⬜ P2 |
| 122 | [Bug] | **`psutil` в health — опциональный import, но не в зависимостях** — всегда падает в production. | `src/api/routes/health.py:69` | ⬜ P2 |
| 123 | [Bug] | **`get_or_create_user_by_telegram` — если email уже занят другим, генерит рандомный пароль без уведомления юзера**. | `src/telegram/handlers/start.py:75-76` | ⬜ P2 |
| 124 | [Bug] | **`today_start` в `sync.py:43` считает по Moscow TZ, хотя `begin_ts` в UTC** — смещение до 12ч. | `src/telegram/handlers/sync.py:43` | ⬜ P2 |
| 125 | [Bug] | **Training list может превысить 4096 символов Telegram** — падение при 100+ сессиях. | `src/telegram/handlers/trainings.py:81` | ⬜ P2 |
| 126 | [Bug] | **Feedback TOCTOU race** — check-then-insert без атомарности, возможны дубли. | `src/telegram/handlers/feedback.py:41-56` | ⬜ P2 |
| 127 | [Bug] | **`settings.py: `old_watch_email` сравнение — ложное срабатывание при пустом `watch_brand`**. | `src/web/routes/pages/settings.py:127` | ⬜ P2 |
| 128 | [Bug] | **`token_ttl_minutes` вычисляется при import time** — stale при hot-reload. | `src/services/auth.py:24` | ⬜ P2 |
| 129 | [Bug] | **`models.py: `weight` как transient proxy** — теряется после закрытия сессии. | `src/models.py:27` | ⬜ P2 |
| 130 | [Bug] | **Опечатка в `stats.py:8` — `'Окторябрь'` вместо `'Октябрь'`**. | `src/services/stats.py:8` | ⬜ P2 |

### Cleanup

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 131 | [Cleanup] | **`ZONE_COLORS` в stats.py не используется** — тень от локального `colors`. | `src/services/stats.py:4` | ⬜ P2 |
| 132 | [Cleanup] | **`import datetime.timezone` в `training_service.py`** — не используется. | `src/services/training_service.py:8` | ⬜ P2 |
| 133 | [Cleanup] | **`models.py` — shim + бизнес-логика (`get_settings`).** Или shim, или сервис — не Both. | `src/models.py` | ⬜ P2 |
| 134 | [Cleanup] | **`get_db()` в Telegram через `next(get_db())`** — если `get_db` рефакторят, сломается бот. | `src/telegram/utils.py:10` | ⬜ P2 |
| 135 | [Cleanup] | **`_get_web_app_url` с `_` (private), но импортируется снаружи** — или public, или не импортировать. | `src/telegram/utils.py:17` | ⬜ P2 |
| 136 | [Cleanup] | **`_AUTO_SYNC_LOCK` (UPPER_CASE) vs `_sync_tasks_lock` (snake_case)** — непоследовательный нейминг. | `src/web/state.py:11-12` | ⬜ P2 |
| 137 | [Cleanup] | **`telegram_notify.py: httpx.Client()` на каждый вызов** — должен быть shared client. | `src/services/telegram_notify.py:27` | ⬜ P2 |
| 138 | [Cleanup] | **Мёртвые константы в `settings.py`** — `session_ttl_days`, `default_max_hr`, `log_file`, `http_timeout` никем не используются. | `src/config/settings.py:9-19` | ⬜ P2 |

---

*Пополнено: 14.07.2026 — аудит перед модулем аналитики (138 пунктов, P0-P2)*
