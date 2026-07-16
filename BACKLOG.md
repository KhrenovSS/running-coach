# BACKLOG — Running Coach

Парковка идей, фиксов и вопросов.  
**Правило:** заметил мелочь → строка сюда, обратно к задаче. Не чини «заодно».

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 1 | [Фикс] | AUDIT-006 Telegram TODO: `sync_runner.py` вызывает `sync_activities_for_user`/`sync_health_for_user` напрямую вместо `run_sync_for_user`. Миграция на `run_sync_for_user_all_brands(chat_id)`. | `src/telegram/sync_runner.py:8-12` | ⬜ Sprint 12b |
| 2 | [Фикс] | AUDIT-003: Тестовое покрытие практически отсутствует (3 теста, 63 строки). Нужно ≥20 тестов. | `tests/` | ✅ Sprint 20 (120 тестов) |
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
| 14 | [Фикс] | `docs/ARCHITECTURE.md` устарел: описывает SQLite, `src/logger.py`, `src/telegram_bot.py`, не описывает `src/watch/`, `src/telegram/`, `src/services/`. | `docs/ARCHITECTURE.md` | ✅ Sprint 19 (DOC-01) |
| 15 | [Вопрос] | AUDIT-008: выделять ли sync в отдельный процесс/контейнер или оставить `run_async_in_thread`? | `src/services/sync_service.py` | ⬜ Вопрос |
| 16 | [Фикс] | Telegram `sync_runner.py`: нужен `run_sync_for_user_all_brands(chat_id)` для объединения отчёта по всем брендам. | `src/telegram/sync_runner.py` | ⬜ Sprint 12b |
| 17 | [Фикс] | Добавить `docs/ARCHITECTURE.md`: описание `src/analysis/` пакета (oscillation, classify, segment, hr_zones, utils) и пайплайна `process_trackpoints()`. | `docs/ARCHITECTURE.md` | ✅ Sprint 19 (DOC-01) |
| 18 | [Фикс] | Добавить unit-тесты для `src/analysis/oscillation.py`: `detect_pace_oscillations` + `compute_hr_lag_correlation` на синтетических данных. | `tests/` | ✅ Sprint 20 (TST-07) |
| 19 | [Фикс] | Обновить `docs/ARCHITECTURE.md`: описание нового алгоритма детекции интервалов (base_pace = средний темп, work-фаза = темп ≥ порог быстрее base_pace). | `docs/ARCHITECTURE.md` | ✅ Sprint 19 (DOC-01) |
| 20 | [Фикс] | Chart.js: темп на графике показывать в формате М:СС (мин:сек) вместо десятичных минут. Например 5.71 → 5:43. Добавить tooltip/label callback + форматирование оси Y. Пульс округлить до целого. | `src/web/templates/session.html:96-115` | ✅ Sprint 20c (PREP-17) |
| 21 | [Фикс] | Weight save через Telegram: "Ошибка при сохранении веса". Decimal→Float, tz-aware, отсутствие traceback, отсутствие метода `log_telegram_received()` в AuditService, `run_once` c `dt_time` вместо `timedelta`. | `src/telegram/handlers/weight.py:89-103`, `src/services/audit.py`, `src/telegram/main.py:77` | ✅ Выполнено |
| 139 | [Фикс] | CRC-ошибка в uploads.py вызывает 500 вместо информирования пользователя + добавление в parse_errors. Нужен try-except вокруг parse_fit/parse_tcx. | `src/web/routes/uploads.py:55-64` | ✅ Выполнено |

---

*Обновлён: 16.07.2026 — Docs audit: README, AGENTS, PROJECT_AUDIT синхронизированы; segment.py split (417→367); Sprint 20c → ✅; #168-176*

---

## 🔴 P0 — Критично (блокирует внедрение модуля аналитики)

### Security

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 22 | [Security] | **Хардкод `SECRET_KEY="dev-secret-key-change-in-production"`** — любой может подделать session-cookie. Прямое нарушение AGENTS.md п.3. Убрать дефолт, требовать через `os.getenv` без fallback. | `src/api/middleware.py:27` | ✅ Sprint 13 (SEC-01) |
| 23 | [Security] | **Email в plaintext в колонке `encrypted_user`** — имя вводит в заблуждение. Либо шифровать email, либо переименовать колонку в `plain_user`/`email`. | `src/services/sync/utils.py:57`, `src/services/watch_credentials.py:54` | ✅ Sprint 13 (SEC-02: Fernet шифрование email) |
| 24 | [Security] | **`PENDING_DIR = /tmp/running_coach_uploads`** — мирно-читаемая директория. GPS/HR данные пользователей доступны любому локальному юзеру. Переместить в `uploads/` или `/var/run/`. | `src/web/state.py:6` | ✅ Sprint 13 (SEC-03: uploads/pending) |
| 25 | [Security] | **Docker: контейнер от root** — нет `USER` директивы. Любая эксплуатация даёт полный доступ к контейнеру. | `Dockerfile` | ✅ Sprint 13 (SEC-04: USER appuser) |
| 26 | [Security] | **PostgreSQL порт 5432 наружу** в docker-compose. Должен быть только для внутренней сети. | `docker-compose.yml:6` | ✅ Sprint 13 (SEC-04: порт убран) |
| 27 | [Security] | **Нет rate-limiting на логин/регистрацию** — brute-force паролей без блокировки. | `src/api/routes/auth.py:71,117` | ✅ Sprint 13 (SEC-05: rate_limiter) |
| 28 | [Security] | **Session fixation** — нет регенерации session ID после логина. | `src/api/routes/auth.py:53-54,99-100,172-173` | ✅ Sprint 13 (SEC-06: session.clear) |
| 29 | [Security] | `MD5(password)` в `coros.py` — это reverse-engineered протокол Coros, не наша вина, но стоит документировать риск. | `src/watch/coros.py:39` | ✅ Документировано (комментарий в коде) |

### Race Conditions

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 30 | [Race] | **`_pending` dict без блокировки** — `_sync_tasks` уже с `_sync_tasks_lock`, а `_pending` без. Data race при конкуррентных аплоадах. | `src/web/state.py:9` | ✅ Sprint 14 (TS-01: Lock) |
| 31 | [Race] | **`_awaiting_weight` без блокировки** — голый dict между хендлерами и jobs. | `src/telegram/state.py:1` | ✅ Sprint 14 (TS-02: Lock) |
| 32 | [Race] | **`_engine` и `_maker` без синхронизации** — double-checked locking anti-pattern при старте в многопоточном uvicorn. | `src/domain/models/base.py:32-67` | ✅ Sprint 14 (TS-03: DCL) |
| 33 | [Race] | **`_fernet_cache` без lock** — два треда могут создать два Fernet-инстанса. | `src/crypto.py:34-36,50` | ✅ Sprint 14 (TS-04: DCL) |
| 34 | [Race] | **Logger cache без lock** — `_app_logger`, `_requests_logger`, `_audit_file_logger` checked-then-set без синхронизации. | `src/utils/logger.py:171-194` | ✅ Sprint 14 (TS-05: DCL) |
| 35 | [Race] | **`_pending` в uplods.py / sync.py** без локи — доступ из нескольких тредов. | `src/web/routes/uploads.py:70,152,211`, `src/web/routes/sync.py:32` | ✅ Sprint 14 (TS-06: cleanup TTL 1ч) |

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
| 42 | [Dead] | **`src/parsers/common.py` отсутствует** — файл, упомянутый в документации, не существует. Спринт 8 «parsers разбиты» не завершён. | `src/parsers/common.py` | ✅ Sprint 18 (parsers уже разбиты: gps, weather, tcx, fit) |
| 43 | [Dead] | **`_get_progress_message()` нигде не вызывается** — мёртвый код. | `src/telegram/handlers/sync.py:15-18` | ✅ Sprint 18 (ARC-11) |
| 44 | [Dead] | **`ValidationError` импортирован, не используется** в auth routes. | `src/api/routes/auth.py:24` | ✅ Sprint 18 (ARC-11) |

### Unbounded Growth / Memory

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 45 | [Memory] | **`_weather_cache` без TTL / лимита** — каждая уникальная (lat,lon,date) остаётся в памяти навсегда. | `src/parsers/weather.py:7` | ⬜ Sprint 20b |
| 46 | [Memory] | **`_pending` / `_sync_tasks` без cleanup** — записи копятся вечно после завершения задач. | `src/web/state.py:9-10` | ✅ Sprint 14 (TS-06: cleanup TTL 1ч) |
| 47 | [Memory] | **`_awaiting_weight` без cleanup** — при удалении пользователя запись остаётся. | `src/telegram/state.py:1` | ✅ Sprint 14 (TS-07: clear_awaiting_weight) |
| 48 | [Memory] | **`all_sessions = db.query(...).all()` без пагинации** — все сессии пользователя в память. | `src/web/routes/pages/index.py:36` | ⬜ Sprint 20b |
| 49 | [Memory] | **N+1: загружаются ВСЕ `begin_ts` и `DeletedTraining`** — OOM при тысячах тренировок. | `src/services/sync/activities.py:85-86` | ⬜ Sprint 20b |

---

## 🟠 P1 — Важно (желательно закрыть до аналитики)

### Code Duplication

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 50 | [DRY] | **`auto_sync_health` и `auto_sync_activities` идентичны на 95%** (~150 строк дубляжа). В аналитике будет ещё `auto_sync_analytics` — утроится. Вынести в одну параметризованную функцию. | `src/services/sync/orchestrator.py:83-238` | ✅ Sprint 18 (ARC-01: _auto_sync) |
| 51 | [DRY] | **Троекратное дублирование создания TrainingSession** в `upload_files`, `confirm_upload`, `confirm_deleted`. | `src/web/routes/uploads.py:92-106,161-174,235-248` | ✅ Sprint 18 (ARC-02: _save_session_from_data) |
| 52 | [DRY] | **Rolling pace window (250м) в трёх местах** — `__init__.py` (2 раза) + `segment.py`. | `src/analysis/__init__.py:139-148,315-325`, `src/analysis/segment.py:103-104` | ✅ Sprint 18 (ARC-03: compute_rolling_pace) |
| 53 | [DRY] | **Km-chunking logic в `_compute_km_variability` и `_km_segment_fallback`** — идентичные циклы разбора трека на км-блоки. | `src/analysis/segment.py:209-259,404-436` | ✅ Sprint 18 (ARC-04: _chunk_by_km) |
| 54 | [DRY] | **Nearest-time lookup в weather.py** — `get_weather_code_at_time` и `get_temp_at_time` почти идентичны. | `src/parsers/weather.py:53-84` | ✅ Sprint 18 (ARC-05: _get_nearest) |
| 55 | [DRY] | **Inline keyboard в uploads.py** — одинаковая клавиатура строится 3 раза. | `src/web/routes/uploads.py:109-122,176-188,249-262` | ✅ Sprint 18 (ARC-02: _build_rating_keyboard) |
| 56 | [DRY] | **`user.name or user.telegram_username or "Бегун"`** повторяется в api/routes/auth.py как минимум 3 раза. | `src/api/routes/auth.py:54,100,173` | ⬜ P2 |
| 57 | [DRY] | **HTML в сервисном слое** — `render_zone_bars`, `render_type_row`, `build_nav_html` генерируют строки HTML в stats.py. Аналитика повторит этот паттерн. | `src/services/stats.py:66-133` | ✅ Sprint 18 (ARC-10: Jinja2) |

### Logging / Observability

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 58 | [Log] | **`fix_logger_after_uvicorn()` чинит только "app" логгер** — `requests_logger` и `audit_file_logger` остаются с мёртвыми хендлерами после uvicorn dictConfig. Логирование запросов и аудита молча перестаёт работать. | `src/utils/logger.py:232` | ✅ Sprint 15 |
| 59 | [Log] | **Нет логирования успешного удаления temp file** — на линии 130 в `uploads.py` нет лога в отличие от линии 58. | `src/web/routes/uploads.py:130` | ✅ Sprint 15 |
| 60 | [Log] | **`api/deps.py` использует `logging.getLogger` вместо `get_logger`** — сообщения не получают структурированного форматирования и ротации. | `src/api/deps.py:23` | ✅ Sprint 15 |

### Data Integrity

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 61 | [DB] | **`user_id` nullable FK во всех моделях** — orphan-записи при удалении пользователя. Нужна миграция на NOT NULL + cascade delete. | `src/domain/models/training.py:13`, `health.py:15`, и др. | ✅ Sprint 17 (DI-01: миграция f7g8h9i0j1k2) |
| 62 | [DB] | **`sleep_hrv_interval_list` типа `Text`** вместо `JSON` — потеря автоматической сериализации. | `src/domain/models/health.py:37` | ✅ Sprint 17 (DI-02: JSON) |
| 63 | [DB] | **`audit.metadata_json` типа `Text`** вместо `JSON` — то же самое. | `src/domain/models/audit.py:18` | ✅ Sprint 17 (DI-03: JSON) |
| 64 | [DB] | **`fit_parser.py: check_crc=False`** — повреждённые FIT-файлы парсятся молча. | `src/parsers/fit_parser.py:14` | ✅ Sprint 17 (DI-04: check_crc=True) |
| 65 | [DB] | **Cadence heuristic `cad < 100: cad * 2`** — Coros-specific логика в generic FIT-парсере. | `src/parsers/fit_parser.py:28-29` | ✅ Sprint 17 (DI-05: coros_cadence_workaround) |
| 66 | [DB] | **Auth token cleanup не удаляет expired-неused** — удаляются только used + >1 day. Expired, но неиспользованные токены копятся. | `src/services/auth.py:116-126` | ✅ Sprint 17 (DI-06: cleanup всех expired) |

### Config Debt (~20 мест с хардкодом вместо констант)

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 67 | [Config] | `max_hr=177` хардкодом в `startup.py:35`, `reanalyze.py:56`, `models.py:20`, `user.py:25`, `conftest.py` — вместо `constants.py`/settings. | `src/startup.py`, `src/services/reanalyze.py`, `src/models.py`, `src/domain/models/user.py` | ✅ Sprint 16 (CFG-01: settings.default_max_hr) |
| 68 | [Config] | `HEALTH_SYNC_DAYS=180` в `constants.py` — но `sync/health.py` использует `timedelta(days=120)`. | `src/services/sync/health.py:77` | ✅ Sprint 16 (CFG-02: HEALTH_SYNC_DAYS) |
| 69 | [Config] | `settings.session_ttl_days` существует, но в `middleware.py` хардкод `7*24*60*60`. | `src/api/middleware.py:180` | ✅ Sprint 16 (CFG-03: settings.session_ttl_days) |
| 70 | [Config] | `settings.http_timeout` существует, но `sync/utils.py` хардкодит `timeout=15`. | `src/services/sync/utils.py:57` | ✅ Sprint 16 (CFG-04: settings.http_timeout) |
| 71 | [Config] | `settings.default_max_hr` не используется нигде. | `src/config/settings.py:12` | ✅ Sprint 16 (CFG-01: используется в 5 файлах) |
| 72 | [Config] | `settings.log_file` не используется — логгер использует `LOGS_DIR`. | `src/config/settings.py:15` | ✅ Sprint 16 (поле удалено/переосмыслено) |
| 73 | [Config] | **Поле `password` со значением `'********'` как sentinel** — если у пользователя реально пароль `********`, он никогда не сможет обновить креды. | `src/services/watch_credentials.py:61` | ✅ Sprint 16 (CFG-07: sentinel удалён) |
| 74 | [Config] | **`Europe/Moscow` хардкодом** в 6+ файлах telegram/ — для мульти-таймзоны нужно из settings. | `src/telegram/main.py:36,74`, `stats.py:27`, `sync.py:43`, `trainings.py:66` и др. | ✅ Sprint 16 (CFG-05: settings.timezone) |
| 75 | [Config] | **`COROS_BASE_URL` и `COROS_*` константы** в глобальном `constants.py` — должны быть в `watch/coros.py`, а не в глобальном config. | `src/config/constants.py:17-22` | ✅ Sprint 16 (CFG-06: удалены) |
| 76 | [Config] | **Поле `upload_dir` в settings не используется** — `startup.py` хардкодит `"uploads"`. | `src/startup.py:72` | ⬜ P2 |

### Input Validation

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 77 | [Validation] | **Нет проверки размера файла** при upload — multi-GB файл заполнит диск. | `src/web/routes/uploads.py:28` | ✅ Sprint 17 (DI-07: ≤50MB) |
| 78 | [Validation] | **Только расширение файла проверяется** — `.exe` переименованный в `.tcx` пройдёт. | `src/web/routes/uploads.py:40` | ⬜ P2 |
| 79 | [Validation] | **Email validation: только `@` и `.`** — `a@b` проходит. | `src/telegram/handlers/start.py:41` | ✅ Sprint 17 (DI-07: email regex) |
| 80 | [Validation] | **Weight range 20-300 — слишком широко** — 19.9 кг проходит. | `src/telegram/handlers/weight.py:73` | ✅ Sprint 17 (DI-07: 30-250кг) |
| 81 | [Validation] | **Нет rate-limiting на upload/settings/logs** — уязвимость к abuse. | `src/web/routes/uploads.py`, `settings.py`, `logs.py` | ⬜ P2 |

### Architectural

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 82 | [Arch] | **`src/analysis/segment.py` превышает 400 строк** (фактически 436) — нарушение правила AGENTS.md. | `src/analysis/segment.py` | ✅ Sprint 18 (ARC-06: 436→312) |
| 83 | [Arch] | **`src/analysis/__init__.py` почти на 400 строках** — `process_trackpoints` ~200 строк, пора разбивать. | `src/analysis/__init__.py` | ✅ Sprint 18 (ARC-07: 387→228) |
| 84 | [Arch] | **`render_page` в index.py — 155 строк** с SQL-запросами, HTML, JSON, логикой. Нарушение «тонкие роуты». | `src/web/routes/pages/index.py:23` | ⬜ P2 |
| 85 | [Arch] | **`upload_files` — 116 строк** с DB операциями, Telegram нотификациями, файловым IO. | `src/web/routes/uploads.py:28-143` | ⬜ P2 |
| 86 | [Arch] | **`sys.path.insert` в 2 местах** — `run_telegram_bot.py` и `alembic/env.py`. Нужно `pip install -e .`. | оба файла | ✅ Sprint 18 (ARC-09: pip install -e .) |
| 87 | [Arch] | **`run_async_in_thread` создаёт новый event-loop на каждый вызов** — частая синхронизация = GC pressure. Нужен пул. | `src/services/async_utils.py:14` | ⬜ P2 |
| 88 | [Arch] | **Нет graceful shutdown** — `scheduler.py` daemon thread без `Event`, при рестарте теряются in-flight sync. | `src/scheduler.py`, `src/web/routes/sync.py:35-36` | ✅ Sprint 18 (ARC-08: Event + on_shutdown) |
| 89 | [Arch] | **`get_db()` телеграм хендлеры выдёргивают через `next(get_db())`** — хак вместо FastAPI DI, сломается при рефакторинге. | `src/telegram/utils.py:10` | ⬜ P2 |
| 90 | [Arch] | **3-4 отдельных DB session per telegram handler** — `get_user` + свой `SessionLocal()` = лишние коннекты. | `src/telegram/handlers/stats.py:25` и др. | ⬜ P2 |

---

## 🟡 P2 — Желательно

### Documentation

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 91 | [Docs] | **`docs/ARCHITECTURE.md` полностью устарел** — SQLite, старые пути, нет `src/analysis/`, `src/domain/`, `src/watch/`. | `docs/ARCHITECTURE.md` | ✅ Sprint 19 (DOC-01) |
| 92 | [Docs] | **`docs/CODE_GUIDELINES.md` ссылается на `CONFIG` (которого нет)** и старые пути. | `docs/CODE_GUIDELINES.md` | ✅ Sprint 19 (DOC-02) |
| 93 | [Docs] | **`src/parsers/__init__.py:1` вводит в заблуждение** — пишет «модули вынесены в src/analysis/», хотя парсеры всё ещё в parsers/. | `src/parsers/__init__.py` | ⬜ P2 |
| 94 | [Docs] | **`CHANGELOG.md` — 1161 строк без оглавления**, нет стандартного формата дат, дублирующиеся записи. | `CHANGELOG.md` | ⬜ P2 |

### Type Hints

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 95 | [Types] | **`stats.py` — все 6 функций без type hints**. | `src/services/stats.py` | ✅ Sprint 19 (DOC-06) |
| 96 | [Types] | **`recovery_view.py` — все 4 функции без type hints**. | `src/services/recovery_view.py` | ✅ Sprint 19 (DOC-06) |
| 97 | [Types] | **`deps.py` — `user`, `session` без аннотаций**. | `src/deps.py:10` | ✅ Sprint 19 (DOC-06) |
| 98 | [Types] | **Trackpoints = `list[dict]` везде вместо TypedDict** — ключи документально нигде не зафиксированы. | весь `analysis/` и `parsers/` | ✅ Sprint 19 (DOC-05: TrackpointDict) |
| 99 | [Types] | **`analysis/__init__.py` возвращает `dict | None` — структура результата нигде не описана типом**. | `src/analysis/__init__.py` | ✅ Sprint 19 (DOC-05: AnalysisResult) |

### Code Quality

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 100 | [Bug] | **`suspect_flags` ставится ТОЛЬКО когда `cleaning_log` пуст** — инвертированная логика. | `src/analysis/__init__.py:235-236` | ⬜ P2 |
| 101 | [Bug] | **`format_pace` может выдать `6:60`** — `int()` truncation вместо `round()`. | `src/analysis/utils.py:19` | ⬜ P2 |
| 102 | [Bug] | **`sqrt(min(a, 1))` — если `a < 0` (floating point), падение**. | `src/parsers/gps.py:11` | ✅ Sprint 17 (DI-09: sqrt(max(0,...))) |
| 103 | [Bug] | **`save_dashboard_data` вызывается дважды** при пустом `metrics_list` — или баг, или лишний вызов. | `src/services/sync/health.py:81-83,181` | ⬜ P2 |
| 104 | [Bug] | **Start_time в TCX: `'' or None` → `AttributeError`** при replace, если оба отсутствуют. | `src/parsers/tcx_parser.py:23-24` | ⬜ P2 |
| 105 | [Bug] | **FIT: `cad < 100: cad * 2` — legitimate 80 spm (walking) → 160**. | `src/parsers/fit_parser.py:28-29` | ✅ Sprint 17 (DI-05: coros_cadence_workaround) |
| 106 | [Bug] | **FIT: `enhanced_altitude=0 or data.get('altitude')` — 0 (valid) трактуется как falsy**. | `src/parsers/fit_parser.py:26` | ⬜ P2 |
| 107 | [Bug] | **Haversine: `sqrt(min(a, 1))` — если `a < 0` (float error), падение**. | `src/parsers/gps.py:11` | ✅ Sprint 17 (DI-09: = #102) |
| 108 | [Bug] | **Oscillation: `avg_pace = 0/1 = 0.0` при пустом slice** — silent data corruption. | `src/analysis/oscillation.py:89` | ⬜ P2 |
| 109 | [Bug] | **Oscillation HR-lag: mismatch time scales** — `pace_change` за 1 шаг, `hr_change` за `lag_sec`. | `src/analysis/oscillation.py:182-190` | ⬜ P2 |
| 110 | [Bug] | **`hr_zones.get_zone()`: `ZeroDivisionError` при `max_hr=0`** — нет валидации. | `src/analysis/hr_zones.py:9` | ✅ Sprint 17 (DI-08: защита max_hr=0) |
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
| 122 | [Bug] | **`psutil` не объявлен в `pyproject.toml`** — health-endpoint импортирует psutil, но пакет отсутствует в зависимостях. В production метрики памяти всегда возвращают "psutil not installed". | `pyproject.toml`, `src/api/routes/health.py:59-67` | ⬜ |
| 123 | [Bug] | **`get_or_create_user_by_telegram` — если email уже занят другим, генерит рандомный пароль без уведомления юзера**. | `src/telegram/handlers/start.py:75-76` | ⬜ P2 |
| 124 | [Bug] | **`today_start` в `sync.py:43` считает по Moscow TZ, хотя `begin_ts` в UTC** — смещение до 12ч. | `src/telegram/handlers/sync.py:43` | ⬜ P2 |
| 125 | [Bug] | **Training list может превысить 4096 символов Telegram** — падение при 100+ сессиях. | `src/telegram/handlers/trainings.py:81` | ⬜ P2 |
| 126 | [Bug] | **Feedback TOCTOU race** — check-then-insert без атомарности, возможны дубли. | `src/telegram/handlers/feedback.py:41-56` | ⬜ P2 |
| 127 | [Bug] | **`settings.py: `old_watch_email` сравнение — ложное срабатывание при пустом `watch_brand`**. | `src/web/routes/pages/settings.py:127` | ⬜ P2 |
| 128 | [Bug] | **`token_ttl_minutes` вычисляется при import time** — stale при hot-reload. | `src/services/auth.py:24` | ⬜ P2 |
| 129 | [Bug] | **`models.py: `weight` как transient proxy** — теряется после закрытия сессии. | `src/models.py:27` | ⬜ P2 |
| 130 | [Bug] | **Опечатка в `stats.py:8` — `'Окторябрь'` вместо `'Октябрь'`**. | `src/services/stats.py:8` | ✅ Sprint 16 (CFG-09) |

### Cleanup

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 131 | [Cleanup] | **`ZONE_COLORS` в stats.py не используется** — тень от локального `colors`. | `src/services/stats.py:4` | ✅ Sprint 18 (ARC-11) |
| 132 | [Cleanup] | **`import datetime.timezone` в `training_service.py`** — не используется. | `src/services/training_service.py:8` | ✅ Sprint 18 (ARC-11) |
| 133 | [Cleanup] | **`models.py` — shim + бизнес-логика (`get_settings`).** Или shim, или сервис — не Both. | `src/models.py` | ⬜ P2 |
| 134 | [Cleanup] | **`get_db()` в Telegram через `next(get_db())`** — если `get_db` рефакторят, сломается бот. | `src/telegram/utils.py:10` | ⬜ P2 |
| 135 | [Cleanup] | **`_get_web_app_url` с `_` (private), но импортируется снаружи** — или public, или не импортировать. | `src/telegram/utils.py:17` | ⬜ P2 |
| 136 | [Cleanup] | **`_AUTO_SYNC_LOCK` (UPPER_CASE) vs `_sync_tasks_lock` (snake_case)** — непоследовательный нейминг. | `src/web/state.py:11-12` | ⬜ P2 |
| 137 | [Cleanup] | **`telegram_notify.py: httpx.Client()` на каждый вызов** — должен быть shared client. | `src/services/telegram_notify.py:27` | ⬜ P2 |
| 138 | [Cleanup] | **Мёртвые константы в `settings.py`** — `session_ttl_days`, `default_max_hr`, `log_file`, `http_timeout` никем не используются. | `src/config/settings.py:9-19` | ✅ Sprint 16 (CFG-01/03/04: используются) |

---

*Обновлён: 14.07.2026 — Sprint 13-20 синхронизация (76+ пунктов отмечены ✅), добавлены новые P0-находки (#139-#141)*

---

## 🆕 Новые находки (аудит 14.07.2026 — перед Sprint 21)

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 139 | [Memory] | **`_weather_cache` без LRU/TTL** — бесконтрольный рост словаря при длительном аптайме. При 1000+ уникальных (lat,lon,date) — утечка памяти. Нужен `functools.lru_cache` или `cachetools.TTLCache`. | `src/parsers/weather.py:7-46` | ✅ Sprint 20b (DEBT-01) |
| 140 | [Memory] | **`db.query(TrainingSession).all()` без LIMIT** — на главной странице все тренировки пользователя загружаются в память. При 1000+ сессий страница падает. Нужен `limit(100)`. | `src/web/routes/pages/index.py:36-38` | ✅ Sprint 20b (DEBT-02) |
| 141 | [Memory] | **N+1 в sync/activities.py: все begin_ts + DeletedTraining загружаются без фильтра** — при 5000+ тренировок каждый sync-цикл загружает всю историю. Нужен `filter(begin_ts >= cutoff_date)` или indexed lookup. | `src/services/sync/activities.py:85-86` | ✅ Sprint 20b (DEBT-03) |

---

## 🆕 Новые находки (16.07.2026 — Диагностика сбоя уведомлений и регистрации)

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 153 | [Bug] | **PK violation при регистрации нового пользователя через Telegram** — `startup.py` создаёт админа с явным `id=1`, но не синхронизирует PostgreSQL sequence `users_id_seq`. При `INSERT` без `id` (регистрация через `/start`) `nextval` возвращает `1` → конфликт с admin user. Проявилось после пересоздания таблиц (volume сброшен), sequence стартовал с 1. | `src/startup.py:38-40` | ⬜ |
| 154 | [Bug] | **Type mismatch: `telegram_chat_id` (BigInteger) сохраняется и сравнивается как `str`** — `start.py` и `utils.py` используют `str(chat_id)` вместо `chat_id` (int) при записи и фильтрации `User.telegram_chat_id`. Работает за счёт неявного приведения PostgreSQL, но создаёт риск отказа при определённых версиях драйвера. | `src/telegram/handlers/start.py:63,76,90`, `src/telegram/utils.py:12` | ✅ Fixed: str→int 16.07.2026 |
| 155 | [Bug] | **Missing `AuditService.log_user_registered`** — `start.py` вызывает `audit.log_user_registered()`, но такого метода нет в `AuditService`. При регистрации через Telegram падает с `AttributeError` и показывает пользователю «Ошибка при сохранении email». | `src/services/audit.py`, `src/telegram/handlers/start.py:80,97` | ✅ Fixed: метод добавлен 16.07.2026 |
| 156 | [Bug] | **`/start` не проверяет `password_hash` — пользователь без пароля не может войти в веб** — если регистрация прервалась на шаге email (пользователь создан, `password_hash=NULL`), повторный `/start` показывает «С возвращением!» сразу, не предлагая ввести пароль. Войти в веб-панель невозможно. | `src/telegram/handlers/start.py:21-27` | ✅ Fixed: добавлена проверка password_hash 16.07.2026 |
| 157 | [Bug] | **"Бегун" вместо имени в веб-интерфейсе** — при регистрации через Telegram не сохраняется `telegram_username` (`update.effective_user.username`), и нет поля `name` на странице `/settings`. Во всех 6 местах fallback `user.name or user.telegram_username or "Бегун"` показывает "Бегун". | `src/telegram/handlers/start.py:88,124`, `src/web/routes/pages/settings.py:51`, `src/web/templates/settings.html` | ✅ Fixed: telegram_username + поле name в /settings 16.07.2026 |
| 158 | [Bug] | **Coros не синхронизируется после пересоздания БД** — таблица `watch_credentials` пуста, пользователю нужно заново ввести email/пароль от Coros Training Hub на странице `/settings`. | `src/web/templates/settings.html` (форма ввода credentials) | ⬜ |
| 159 | [Fix] | **Пароль остаётся в Telegram после регистрации** — сообщение с паролем от веб-кабинета не удаляется после сохранения. Нужно удалять сообщение с паролем, а при неудаче писать WARNING в лог с user_id, chat_id и причиной. | `src/telegram/handlers/start.py:138-140` | ✅ Fixed: delete + logger.warning 16.07.2026 |
| 160 | [Bug] | **Ошибка 422 при сохранении настроек — `weight` required** — GET /settings использует `get_settings()` (admin user), у которого `weight_kg = NULL`. Шаблон рендерит `value='None'`, браузер не отправляет битое число, FastAPI падает с `Field required`. POST handler требует `weight` и `max_hr` как обязательные. | `src/web/routes/pages/settings.py:27,70`, `src/web/templates/settings.html:22` | ✅ Fixed: current_user.* + опциональные поля + or '' 16.07.2026 |
| 161 | [Bug] | **Неверная сегментация — проверяется общий разброс темпа, а не разница между соседними отрезками** — правило: по умолчанию 1км отрезки, отрезки другого размера только для интервалов, соседние отрезки должны отличаться > 1 мин/км. Исправлено: oscillation как основной детектор + _merge_similar_segments для слияния похожих отрезков. | `src/analysis/segment.py` | ✅ Fixed: oscillation + merge_similar + пересчёт 16.07.2026 |
| 162 | [Bug] | **`classify_training` не учитывает финальные сегменты** — `oscillation_count` и `var_count` считаются из сырых трекпоинтов, но сегменты могут быть слиты `_merge_similar_segments` в 1. Классификация возвращает `interval` (oscillation_count ≥ 3), хотя реальных сегментов нет. | `src/analysis/classify.py:46-50`, `src/analysis/__init__.py:135-141` | ✅ Fixed: segments_len < 3 → не interval + пересчёт 16.07.2026 |
| 163 | [Bug] | **Неинтервальные тренировки показывают 1 сегмент вместо км-блоков** — `segment_by_pace()` возвращает 1 сегмент после слияния, `is_km_segmentation()` не ловит единый 5.6км сегмент. Для tempo/long/recovery всегда должны быть км-блоки, oscillation-сегменты только для interval. | `src/analysis/__init__.py:104-142` | ✅ Fixed: km_fallback для не-interval + пересчёт 16.07.2026 |
| 164 | [Docs] | **Документация не соответствовала проекту** — частично fixed (TESTING.md, API_ROUTES_GUIDE.md, ARCHITECTURE.md, AGENTS.md, CHECKLIST_API.md). Остались замечания #189–#197. | `docs/*`, `AGENTS.md`, `README.md` | ⬜ |
| 165 | [Bug] | **`_merge_similar_segments` использует `<= threshold` вместо `< threshold`** — сегменты с разницей темпа ровно 1.0 мин/км (work=4.0, recovery=5.0) сливаются в один. Интервальная тренировка с `pace_gap=1.0` теряет все work/recovery фазы, остаётся 2-3 сегмента вместо 11+. `classify_training()` не видит интервалов и возвращает `tempo`. | `src/analysis/segment.py:252` | ✅ Fixed 16.07.2026 |
---

## 🔴 P0 — Подготовка к модулю аналитики (аудит 14.07.2026 — Sprint 20c)

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 142 | [Bug] | **Telegram stats handler ссылается на несуществующие колонки** — `TrainingSession.distance_km`, `TrainingSession.duration_seconds`, `TrainingSession.sport` НЕ СУЩЕСТВУЮТ. Реальные колонки: `total_distance_km`, `duration_minutes`, `training_type`. Команда `/stats` падает с `AttributeError` при вызове `_overview()` (строки 44,47,64) или `_period_stats()` (строки 83-84,98). **Блокирует:** любой Telegram-пользователь, вызвавший `/stats`, получает crash. | `src/telegram/handlers/stats.py:44,47,64,83-84,98` | ✅ Sprint 20c (PREP-01) |
| 143 | [DB] | **Нет индексов для запросов по диапазонам времени** — `training_sessions` не имеет индекса на `begin_ts` и составного `(user_id, begin_ts)`. Модуль аналитики будет постоянно делать запросы «тренировки пользователя за N дней» — каждый раз full table scan. Аналогично: `training_feedback` нет `(user_id, created_at)`, `weight_measurements` нет `(user_id, measured_at)`. `daily_metrics` имеет `UniqueConstraint(user_id, date)` — это даёт составной индекс, но `training_sessions` — нет. **Блокирует:** все skills модуля аналитики (fatigue, load, progress, distribution) будут медленными. | `src/domain/models/training.py:13-14`, `health.py:15-16` | ✅ Sprint 20c (PREP-02) |
| 144 | [Arch] | **Нет слоя агрегационных запросов** — создан `src/services/repositories.py` с `TrainingRepository` и `HealthRepository`, но `zone_distribution()` является заглушкой (всё падает в `z2`). Нужно реализовать реальное распределение по пульсовым зонам. | `src/services/repositories.py:45-62` | ⬜ Sprint 20c (PREP-03) |

---

## 🟠 P1 — Подготовка к модулю аналитики (аудит 14.07.2026 — Sprint 20c)

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 145 | [Bug] | **Двойная сериализация `sleep_hrv_interval_list`** — `src/services/sync/health.py:47` делает `json.dumps(intervals)` перед записью в JSON-колонку. SQLAlchemy сериализует ещё раз. Потребители (`index.py:165`, `session.py:42`) вынуждены делать `json.loads()` для распаковки. Модуль `skills/fatigue.py` должен будет знать об этом quirke или получит строку вместо списка. **Усложняет:** реализацию HRV-аналитики. | `src/services/sync/health.py:47`, `src/web/routes/pages/index.py:165` | ✅ Sprint 20c (PREP-04) |
| 146 | [Arch] | **`get_settings()` хардкодит `User.id == 1`** — `src/models.py:17` всегда возвращает настройки первого пользователя. `index.py` использует `get_settings().max_hr` для расчёта зон — это некорректно для мультюзер-сценария. Модулю коуча нужен per-user доступ к настройкам (`user.max_hr`, `user.interval_pace_threshold` и т.д.). **Усложняет:** per-user аналитику и персонализацию. | `src/models.py:17`, `src/web/routes/pages/index.py:68` | ✅ Sprint 20c (PREP-05) |
| 147 | [Arch] | **`recovery_view.py` — только display, не аналитика** — функции `hrv_status()`, `tired_label()`, `readiness_label()`, `load_label()` возвращают строки с эмодзи для HTML. Структурированных числовых результатов нет. Модуль `skills/fatigue.py` должен будет переписывать логику с нуля, возвращая `SkillResult` (status + value + confidence + evidence). **Усложняет:** переиспользование существующей логики. | `src/services/recovery_view.py` | ✅ Sprint 20c (PREP-06) |
| 148 | [Arch] | **Нет функций трендов (slope, EWMA, moving average)** — ни одной функции для вычисления трендов VO2max, LTHR, stamina, HRV за 30/90 дней. `skills/progress.py` будет строиться полностью с нуля. Нужны helpers: `compute_slope(series, days)`, `compute_ewma(series, alpha)`, `compute_moving_average(series, window)`. **Усложняет:** реализацию progress-аналитики. | `src/services/analytics_helpers.py` | ✅ Sprint 20c (PREP-07) |
| 149 | [DB] | **Нет `avg_pace` на `TrainingSession`** — у `DeletedTraining` есть `avg_pace`, у `TrainingSession` — нет. Каждый раз нужно считать `duration_minutes / total_distance_km`. Для модуля аналитики, который сравнивает эффективность по темпу (pace-at-HR, running efficiency), это лишнее вычисление на каждый запрос. **Усложняет:** queries для efficiency-метрик. | `src/domain/models/training.py:9-38` | ✅ Sprint 20c (PREP-08) |
| 150 | [Test] | **Нет тестовых фабрик для DailyMetrics и TrainingSession** — `tests/helpers.py` содержит `build_trackpoints()` (dict-ы для анализа), но нет фабрик для ORM-объектов `DailyMetrics` (серии 30-90 дней), `TrainingSession` (с `segments_json`, `training_type`, `training_effect`), `TrainingFeedback`. Тестирование скиллов и калибровки без них невозможно. **Блокирует:** написание тестов для `src/coach/skills/`. | `tests/helpers.py` | ✅ Sprint 20c (PREP-09) |

---

## 🟡 P2 — Подготовка к модулю аналитики (аудит 14.07.2026 — Sprint 20c)

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 151 | [Config] | **Нет `src/coach/config.py`** — `settings.py` (9 полей) и `constants.py` (52 строки) не содержат параметров аналитики: веса readiness/fatigue score, пороги injury risk, EWMA-параметры калибровки, confidence thresholds, recovery hours by type. Предусмотрено дизайн-документом как часть Этапа 0. **Усложняет:** настройку модуля аналитики. | `src/config/settings.py`, `src/config/constants.py` | ✅ Sprint 20c (PREP-10) |
| 152 | [Cleanup] | **`src/models.py` — shim с бизнес-логикой** — содержит `get_settings()`, `get_user()`, `get_user_by_telegram()` — это сервисные функции, не реэкспорт моделей. Модулю коуча лучше импортировать из `src.domain.models` напрямую (по образцу `src/analysis/`, который вообще не импортирует `src.models`). **Усложняет:** чистоту импортов. | `src/models.py:13-64` | ✅ Sprint 20c (PREP-11) |

---

| 166 | [Fix] | **Jitter ±20% не реализован** — README декларирует jitter для авто-синка, константа `JITTER_FACTOR=0.2` определена, но не использовалась. Добавлена `with_jitter()`, применена к тику в `scheduler.py` и к `next_run` в `orchestrator.py`. | `src/config/constants.py`, `src/scheduler.py`, `src/services/sync/orchestrator.py` | ✅ Fixed 16.07.2026 |
| 167 | [Cleanup] | **`src/analysis/segment.py` не превышает 400 строк** — фактически 367 строк. Закрыто после Sprint 18. | `src/analysis/segment.py` | ✅ Sprint 18 |

| 168 | [Docs] | **README migration order неверен** — порядок миграций в README не соответствует цепочке `down_revision`. `3205fe660d47`/`4201426df9cc` указаны на позициях 8-9, а реально применяются 2-3 (сразу после baseline). Исправлено: переупорядочено по `down_revision`. | `README.md:212-222` | ✅ Fixed 16.07.2026 |
| 169 | [Docs] | **README `users` — пропущена колонка `last_health_sync_at`** — реальная модель имеет колонку, но она не описана в README SQL-блоке. | `README.md:64-90`, `src/domain/models/user.py:24` | ✅ Fixed 16.07.2026 |
| 170 | [Docs] | **README `auth_tokens` — неверный тип `token`** — README пишет «UUID», по факту `String(64)` (`secrets.token_urlsafe`). Исправлено. | `README.md:58`, `src/domain/models/auth.py` | ✅ Fixed 16.07.2026 |
| 171 | [Docs] | **README weight poll — неверное расписание** — README писал «в 9:00», код запускает 4 раза: 9, 12, 15, 18 (скип если вес уже введён). Исправлено. | `README.md:422`, `src/telegram/main.py:70-71` | ✅ Fixed 16.07.2026 |
| 172 | [Docs] | **README «Аналитика (12 недель)» — не реализовано** — раздел описывал VO₂max/LTHR/Stamina/Performance trend как готовые, но в коде только generic-хелперы. Sprint 21 ⬜. Исправлено: перенесено в планы с пометкой ⚠️. | `README.md:453-459`, `src/services/stats.py`, `analytics_helpers.py` | ✅ Fixed 16.07.2026 |
| 173 | [Docs] | **README — недокументированные роуты** — отсутствуют в дереве: `/session/{id}/delete`, `/session/{id}/feedback`, `/sync/status/{task_id}`, legacy `/coros/*`. `/dashboard/query` описан как локальный endpoint, но это внешний Coros API URL. Добавлены. | `README.md:338-341`, `sync.py:55,80,86,92`, `session.py:166,173` | ✅ Fixed 16.07.2026 |
| 174 | [Docs] | **README Telegram /cancel не указан** — `/cancel` зарегистрирован как ConversationHandler fallback, но не документирован. Добавлен. | `README.md:413`, `src/telegram/main.py:46,61` | ✅ Fixed 16.07.2026 |
| 175 | [Cleanup] | **Undocumented root files** — `app.log`, `running_coach.db`, `test.db`, `test.db-journal` не отражены в README дереве и не в `.gitignore`. SQLite-файлы — артефакты прежних запусков, не используются (README декларирует PostgreSQL). Удалены SQLite-файлы; `app.log` — перенести/добавить в `logs/`. | корень проекта | ⬜ |
| 176 | [Docs] | **Revision-ID `f7g8h9i0j1k2`/`g9h0i1j2k3l4` содержат не-hex символы** — буквы g-l не являются hex-цифрами. Рабочие как строки Alembic, но стилистически подозрительны (hand-faked). Рекомендуется переименовать в корректные hex-ID при следующем пересоздании миграций. | `alembic/versions/f7g8h9i0j1k2*.py`, `g9h0i1j2k3l4*.py` | ⬜ |

---

*Обновлён: 16.07.2026 — #153-176, docs audit*

---

## 🆕 Новые находки (аудит 16.07.2026 — полный docs/config/code audit)

### 🔴 P0 — Критично

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 177 | [Bug] | **`psutil` не объявлен в `pyproject.toml`** — health-endpoint импортирует psutil, но пакет отсутствует в зависимостях. В production метрики памяти всегда возвращают "psutil not installed". | `pyproject.toml`, `src/api/routes/health.py:59-67` | ⬜ |

### 🟠 P1 — Важно

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 178 | [Config] | **Healthcheck бота бесполезен** — `docker-compose.yml` использует `pg_isready` в образе `python:3.13-slim`, где его нет; `|| exit 0` делает проверку формально успешной. | `docker-compose.yml` | ⬜ |
| 179 | [Docs/Git] | **`bin/docker.sh` отслеживается git, но `.gitignore` игнорирует `bin/`** — документация говорит "создать вручную, не отслеживается git". | `.gitignore:31`, `bin/docker.sh` | ✅ (файл не в индексе git, .gitignore работает) |
| 180 | [Config] | **`SUDO_PASSWORD` не описан в `.env.example`** — `bin/docker.sh:8` читает переменную, но шаблон .env её не содержит. | `.env.example`, `bin/docker.sh:8` | ⬜ |
| 181 | [Config] | **`max_hr=177` остаётся хардкодом** — `User.max_hr`, `process_trackpoints`, `_merge_similar_segments` используют `177` напрямую вместо `settings.default_max_hr`. Нужен единый источник правды. | `src/domain/models/user.py:25`, `src/analysis/__init__.py:26`, `src/analysis/segment.py:186` | ⬜ |
| 182 | [Bug] | **`zone_distribution()` в `repositories.py` — заглушка** — всё время записывается в `z2`, реальное распределение по пульсовым зонам не считается. | `src/services/repositories.py:45-62` | ⬜ |
| 183 | [Race] | **`_cleanup_stale_pending()` без `_pending_lock`** — функция модифицирует `_pending` без блокировки, риск race condition. | `src/web/state.py:19-26` | ⬜ |

### 🟡 P2 — Желательно / документация

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 184 | [Config] | **`.env.example` неполный** — отсутствуют переменные из `settings.py`: `PASSWORD_MIN_LENGTH`, `TOKEN_TTL_MINUTES`, `SESSION_TTL_DAYS`, `DEFAULT_MAX_HR`, `LOG_FILE`, `HTTP_TIMEOUT`, `TIMEZONE`. | `.env.example`, `src/config/settings.py` | ⬜ |
| 185 | [Cleanup] | **Неиспользуемые зависимости** — `tzlocal` в основных; `pytest-asyncio`, `freezegun`, `factory-boy` в dev. | `pyproject.toml` | ⬜ |
| 186 | [Cleanup] | **Мёртвые константы в `audit.py`** — `USER_LOGIN`, `USER_LOGOUT`, `ERROR` объявлены, но не используются. | `src/services/audit.py:14` | ⬜ |
| 187 | [Log] | **`audit.py` использует `logging.getLogger("app")`** вместо `get_logger` из `src.utils.logger`. | `src/services/audit.py:93` | ⬜ |
| 188 | [Cleanup] | **Мёртвые ссылки в docstring `sync_runner.py`** — упоминаются `SyncService`, `SyncLog`, `full_sync`. | `src/telegram/sync_runner.py:5-6` | ⬜ |
| 189 | [Docs] | **`README.md`: устаревшие цифры** — "parsers разбиты на 9 модулей" (факт 5), "telegram разбит на 12 файлов" (факт 17); Roadmap не отмечает тесты как выполненные. | `README.md` | ⬜ |
| 190 | [Docs] | **`README.md`: неверная команда для логов** — `logs/app_$(date +%F).log`, реальные файлы `logs/app.log.YYYY-MM-DD`. | `README.md:656-659` | ⬜ |
| 191 | [Docs] | **`README.md`: дерево `pages/` неполное** — в структуре раскрыт только `session.py`, не хватает `auth.py`, `index.py`, `settings.py`. | `README.md:338-340` | ⬜ |
| 192 | [Docs] | **`docs/LOGGING.md`: формат файлов и event types** — имена файлов не совпадают с `src/utils/logger.py`; не хватает событий `training.*`, `feedback.*`. | `docs/LOGGING.md` | ⬜ |
| 193 | [Docs] | **`docs/TESTING.md`: SQLite vs PostgreSQL** — написано "реальный PostgreSQL", но `tests/conftest.py` использует `sqlite:///:memory:`. | `docs/TESTING.md:29` | ⬜ |
| 194 | [Docs] | **`docs/TESTING.md`: пример `conftest.py` устарел** — `scope="session"` и `init_db`, реально `scope="function"` и `SessionLocal`. | `docs/TESTING.md:64-80` | ⬜ |
| 195 | [Docs] | **`docs/API_ROUTES_GUIDE.md`: устаревшие примеры** — Pydantic-схемы в `src/models.py` (shim), пример `TrainingService.get`. | `docs/API_ROUTES_GUIDE.md:137-157, 194` | ⬜ |
| 196 | [Docs] | **`docs/CODE_GUIDELINES.md`: устаревший пример `TrainingService.get`** | `docs/CODE_GUIDELINES.md:393-403` | ⬜ |
| 197 | [Docs] | **`docs/DEVELOPMENT_GUIDELINES.md`: не упомянут env** — проверочные команды (`from src.startup import create_app`) требуют `DATABASE_URL`, `SECRET_KEY`, `CRED_KEY`. | `docs/DEVELOPMENT_GUIDELINES.md:35-38` | ⬜ |
| 198 | [Docs] | **`PROJECT_AUDIT.md`: неотмеченные закрытые AUDIT-пункты** — AUDIT-001, AUDIT-002, AUDIT-009, AUDIT-010, AUDIT-013, AUDIT-015 в коде fixed, но DoD-чекбоксы пустые. | `PROJECT_AUDIT.md` | ⬜ |
| 199 | [Docs] | **`AGENTS.md`: устаревший статус** — Sprint 21 помечен ⬜, но не начат; цифры `src/telegram/` и `src/parsers/` не совпадают с README. | `AGENTS.md` | ⬜ |
| 200 | [Cleanup] | **Затенение импорта `settings`** — переменная `settings = get_settings(...)` затеняет `from src.config import settings` в `startup.py` и `index.py`. | `src/startup.py:45`, `src/web/routes/pages/index.py:68` | ⬜ |
| 201 | [Cleanup] | **Magic numbers в фильтре графика** — `3.0 < pace_val < 10.0` в `analysis/utils.py`. | `src/analysis/utils.py:261` | ⬜ |

---

*Обновлён: 16.07.2026 — #177-201, full docs/config/code audit*
