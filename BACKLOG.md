# BACKLOG — Running Coach

Парковка идей, фиксов и вопросов.  
**Правило:** заметил мелочь → строка сюда, обратно к задаче. Не чини «заодно».

> **Сверка 03.08.2026 (tech-debt спринт):** статусы синхронизированы с кодом. Закрыты как
> уже-сделанные (были ⬜, по факту исправлены): #93, #100, #101, #108, #115, #122, #129, #144,
> #153, #180, #184, #185, #186, #187, #188, #218 (P0), #76. Исправлены в этом спринте:
> #56, #137, #200, #201. Остаются открытыми (вне скоупа): безопасность #78/#116/#119/#123,
> архитектура #1/#16/#84/#85/#87/#89/#90/#133, анализ #103/#104/#106/#109/#111/#112/#113/#114,
> и отложенные фичи #5/#6/#8–#13/#15. См. также `PROJECT_AUDIT.md`.

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
| 9 | [Coach] | Гибридный ИИ-коуч (пересмотр «8 этапов»: LLM рассуждает, скиллы — tools, safety — фильтр). Нормативный план — `docs/coach/DEV_PLAN.md`. | `docs/coach/DEV_PLAN.md` | ✅ **Чек-листы C0–C9 закрыты** (C8 — 24.08.2026: LLM-разбор+недельный отчёт+гейт; деплой C8 — отдельно). Дальнейшее — #241/#242/#247 и др. |
| 10 | [Идея] | Фильтр по типу тренировки на главной, общая дистанция/время за неделю/месяц. | PROJECT_AUDIT.md | ⬜ Заморожено (после C8/C9 DEV_PLAN) |
| 11 | [Идея] | Sprint 14: Multi-brand onboarding — выбор бренда при `/start`, заглушки для Polar/Garmin/Suunto. | PROJECT_AUDIT.md | ⬜ Sprint 14 (заморожен) |
| 12 | [Идея] | Факторы самочувствия — multi-select (ноги, дыхание, пульс, жара, недосып, стресс), адаптивные подсказки. | PROJECT_AUDIT.md | 🔶 Частично закрыт C3/C4 23.08.2026 (`wellness_reports`: боль/крепатура/настроение/сон + вечерний опрос); полный multi-select открыт |
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

*Обновлён: 21.07.2026 — Docs audit #2: BACKLOG синхронизирован со Sprint 20b/21/24/Docs audit; #45,48,49,177-183,189-199,211-217 отмечены ✅*

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
| 45 | [Memory] | **`_weather_cache` без TTL / лимита** — каждая уникальная (lat,lon,date) остаётся в памяти навсегда. | `src/parsers/weather.py:7` | ✅ Sprint 20b |
| 46 | [Memory] | **`_pending` / `_sync_tasks` без cleanup** — записи копятся вечно после завершения задач. | `src/web/state.py:9-10` | ✅ Sprint 14 (TS-06: cleanup TTL 1ч) |
| 47 | [Memory] | **`_awaiting_weight` без cleanup** — при удалении пользователя запись остаётся. | `src/telegram/state.py:1` | ✅ Sprint 14 (TS-07: clear_awaiting_weight) |
| 48 | [Memory] | **`all_sessions = db.query(...).all()` без пагинации** — все сессии пользователя в память. | `src/web/routes/pages/index.py:36` | ✅ Sprint 20b |
| 49 | [Memory] | **N+1: загружаются ВСЕ `begin_ts` и `DeletedTraining`** — OOM при тысячах тренировок. | `src/services/sync/activities.py:85-86` | ✅ Sprint 20b |

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
| 56 | [DRY] | **`user.name or user.telegram_username or "Бегун"`** повторяется в api/routes/auth.py как минимум 3 раза. | `src/api/routes/auth.py:54,100,173` | ✅ Fixed 03.08.2026 (_display_name helper) |
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
| 76 | [Config] | **Поле `upload_dir` в settings не используется** — `startup.py` хардкодит `"uploads"`. | `src/startup.py:72` | ✅ Сверка 03.08.2026 (нет поля upload_dir; хардкод норма) |

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
| 93 | [Docs] | **`src/parsers/__init__.py:1` вводит в заблуждение** — пишет «модули вынесены в src/analysis/», хотя парсеры всё ещё в parsers/. | `src/parsers/__init__.py` | ✅ Сверка 03.08.2026 (docstring актуален) |
| 94 | [Docs] | **`CHANGELOG.md` — 1613 строк без оглавления**, нет стандартного формата дат, дублирующиеся записи. | `CHANGELOG.md` | ⬜ P2 |

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
| 100 | [Bug] | **`suspect_flags` ставится ТОЛЬКО когда `cleaning_log` пуст** — инвертированная логика. | `src/analysis/__init__.py:235-236` | ✅ Сверка 03.08.2026 (`__init__.py:216-221`) |
| 101 | [Bug] | **`format_pace` может выдать `6:60`** — `int()` truncation вместо `round()`. | `src/analysis/utils.py:19` | ✅ Сверка 03.08.2026 (`utils.py:46-58` round+guard) |
| 102 | [Bug] | **`sqrt(min(a, 1))` — если `a < 0` (floating point), падение**. | `src/parsers/gps.py:11` | ✅ Sprint 17 (DI-09: sqrt(max(0,...))) |
| 103 | [Bug] | **`save_dashboard_data` вызывается дважды** при пустом `metrics_list` — или баг, или лишний вызов. | `src/services/sync/health.py:81-83,181` | ⬜ P2 |
| 104 | [Bug] | **Start_time в TCX: `'' or None` → `AttributeError`** при replace, если оба отсутствуют. | `src/parsers/tcx_parser.py:23-24` | ⬜ P2 |
| 105 | [Bug] | **FIT: `cad < 100: cad * 2` — legitimate 80 spm (walking) → 160**. | `src/parsers/fit_parser.py:28-29` | ✅ Sprint 17 (DI-05: coros_cadence_workaround) |
| 106 | [Bug] | **FIT: `enhanced_altitude=0 or data.get('altitude')` — 0 (valid) трактуется как falsy**. | `src/parsers/fit_parser.py:26` | ⬜ P2 |
| 107 | [Bug] | **Haversine: `sqrt(min(a, 1))` — если `a < 0` (float error), падение**. | `src/parsers/gps.py:11` | ✅ Sprint 17 (DI-09: = #102) |
| 108 | [Bug] | **Oscillation: `avg_pace = 0/1 = 0.0` при пустом slice** — silent data corruption. | `src/analysis/oscillation.py:89` | ✅ Сверка 03.08.2026 (`oscillation.py:114-132` fallback) |
| 109 | [Bug] | **Oscillation HR-lag: mismatch time scales** — `pace_change` за 1 шаг, `hr_change` за `lag_sec`. | `src/analysis/oscillation.py:182-190` | ⬜ P2 |
| 110 | [Bug] | **`hr_zones.get_zone()`: `ZeroDivisionError` при `max_hr=0`** — нет валидации. | `src/analysis/hr_zones.py:9` | ✅ Sprint 17 (DI-08: защита max_hr=0) |
| 111 | [Bug] | **Сегментация O(n^2)** — while loop по trackpoints для rolling window при равных dist. | `src/analysis/segment.py:103-104` | ⬜ P2 |
| 112 | [Bug] | **Сегментация: `max_credible_upper=15.0` хардкодом** — не из конфига. | `src/analysis/segment.py:111` | ⬜ P2 |
| 113 | [Bug] | **Сегментация: `count_off_osc = len(osc) < num_kms * 0.5` — предел 50-150% слишком широк**. | `src/analysis/segment.py:370-371` | ⬜ P2 |
| 114 | [Bug] | **Sync audit: `log_sync_completed` вызывается внутри per-cred цикла, передаёт cumulative totals** — искажение per-brand статистики. | `src/telegram/sync_runner.py:84-90` | ⬜ P2 |
| 115 | [Bug] | **`cmd_delete_me` — немедленное удаление без подтверждения**. | `src/telegram/handlers/account.py:28-33` | ✅ Сверка 03.08.2026 (=#215, два шага) |
| 116 | [Bug] | **Пароль показывается в plaintext в Telegram** — self-deleting, но может засветиться в нотификациях. | `src/telegram/handlers/account.py:121-127` | ⬜ P2 |
| 117 | [Bug] | **`handle_weight_message` — catch-all для всех не-командных сообщений** — любой текст в неудачный момент попытается стать weight. | `src/telegram/main.py:68` | ⬜ P2 |
| 118 | [Bug] | **Weight state не сбрасывается при ошибке** — пользователь застревает в режиме ввода веса. | `src/telegram/handlers/weight.py:98-101` | ✅ Sprint 15 |
| 119 | [Bug] | **`/logs` endpoint без аутентификации** + path traversal (хотя `os.path.join` немного защищает). | `src/web/routes/logs.py:10` | ⬜ P2 |
| 120 | [Bug] | **`/logs` уровень детекции по подстроке** — слово `"WARNING"` в сообщении даёт неверный CSS. | `src/web/routes/logs.py:40-41` | ⬜ P2 |
| 121 | [Bug] | **`/health` всегда 200, даже при `degraded`** — маскирует проблемы от load balancer. | `src/api/routes/health.py:92` | ⬜ P2 |
| 122 | [Bug] | **`psutil` не объявлен в `pyproject.toml`** — health-endpoint импортирует psutil, но пакет отсутствует в зависимостях. В production метрики памяти всегда возвращают "psutil not installed". | `pyproject.toml`, `src/api/routes/health.py:59-67` | ✅ Сверка 03.08.2026 (=#177, psutil в pyproject) |
| 123 | [Bug] | **`get_or_create_user_by_telegram` — если email уже занят другим, генерит рандомный пароль без уведомления юзера**. | `src/telegram/handlers/start.py:75-76` | ⬜ P2 |
| 124 | [Bug] | **`today_start` в `sync.py:43` считает по Moscow TZ, хотя `begin_ts` в UTC** — смещение до 12ч. | `src/telegram/handlers/sync.py:43` | ⬜ P2 |
| 125 | [Bug] | **Training list может превысить 4096 символов Telegram** — падение при 100+ сессиях. | `src/telegram/handlers/trainings.py:81` | ⬜ P2 |
| 126 | [Bug] | **Feedback TOCTOU race** — check-then-insert без атомарности, возможны дубли. | `src/telegram/handlers/feedback.py:41-56` | ⬜ P2 |
| 127 | [Bug] | **`settings.py: `old_watch_email` сравнение — ложное срабатывание при пустом `watch_brand`**. | `src/web/routes/pages/settings.py:127` | ⬜ P2 |
| 128 | [Bug] | **`token_ttl_minutes` вычисляется при import time** — stale при hot-reload. | `src/services/auth.py:24` | ⬜ P2 |
| 129 | [Bug] | **`models.py: `weight` как transient proxy** — теряется после закрытия сессии. | `src/models.py:27` | ✅ Сверка 03.08.2026 (models.py — чистый shim) |
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
| 137 | [Cleanup] | **`telegram_notify.py: httpx.Client()` на каждый вызов** — должен быть shared client. | `src/services/telegram_notify.py:27` | ✅ Fixed 03.08.2026 (shared httpx client) |
| 138 | [Cleanup] | **Мёртвые константы в `settings.py`** — `session_ttl_days`, `default_max_hr`, `log_file`, `http_timeout` никем не используются. | `src/config/settings.py:9-19` | ✅ Sprint 16 (CFG-01/03/04: используются) |

---

*Обновлён: 21.07.2026 — Sprint 13-20 синхронизация завершена; #45,48,49 ← Sprint 20b ✅; #177-183 ← Pre-Sprint 21 ✅; #189-199 ← Docs audit ✅; #211-217 ← Sprint 24 ✅*

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
| 153 | [Bug] | **PK violation при регистрации нового пользователя через Telegram** — `startup.py` создаёт админа с явным `id=1`, но не синхронизирует PostgreSQL sequence `users_id_seq`. При `INSERT` без `id` (регистрация через `/start`) `nextval` возвращает `1` → конфликт с admin user. Проявилось после пересоздания таблиц (volume сброшен), sequence стартовал с 1. | `src/startup.py:38-40` | ✅ Сверка 03.08.2026 (=#218, `startup.py:60`) |
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
| 144 | [Arch] | **Нет слоя агрегационных запросов** — создан `src/services/repositories.py` с `TrainingRepository` и `HealthRepository`, но `zone_distribution()` является заглушкой (всё падает в `z2`). Нужно реализовать реальное распределение по пульсовым зонам. | `src/services/repositories.py:45-62` | ✅ Сверка 03.08.2026 (=#182, реализовано) |

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
| 177 | [Bug] | **`psutil` не объявлен в `pyproject.toml`** — health-endpoint импортирует psutil, но пакет отсутствует в зависимостях. В production метрики памяти всегда возвращают "psutil not installed". | `pyproject.toml`, `src/api/routes/health.py:59-67` | ✅ Pre-Sprint 21 |

### 🟠 P1 — Важно

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 178 | [Config] | **Healthcheck бота бесполезен** — `docker-compose.yml` использует `pg_isready` в образе `python:3.13-slim`, где его нет; `|| exit 0` делает проверку формально успешной. | `docker-compose.yml` | ✅ Pre-Sprint 21 |
| 179 | [Docs/Git] | **`bin/docker.sh` отслеживается git, но `.gitignore` игнорирует `bin/`** — документация говорит "создать вручную, не отслеживается git". | `.gitignore:31`, `bin/docker.sh` | ✅ (файл не в индексе git, .gitignore работает) |
| 180 | [Config] | **`SUDO_PASSWORD` не описан в `.env.example`** — `bin/docker.sh:8` читает переменную, но шаблон .env её не содержит. | `.env.example`, `bin/docker.sh:8` | ✅ Сверка 03.08.2026 (.env.example содержит) |
| 181 | [Config] | **`max_hr=177` остаётся хардкодом** — `User.max_hr`, `process_trackpoints`, `_merge_similar_segments` используют `177` напрямую вместо `settings.default_max_hr`. Нужен единый источник правды. | `src/domain/models/user.py:25`, `src/analysis/__init__.py:26`, `src/analysis/segment.py:186` | ✅ Pre-Sprint 21 |
| 182 | [Bug] | **`zone_distribution()` в `repositories.py` — заглушка** — всё время записывается в `z2`, реальное распределение по пульсовым зонам не считается. | `src/services/repositories.py:45-62` | ✅ Pre-Sprint 21 |
| 183 | [Race] | **`_cleanup_stale_pending()` без `_pending_lock`** — функция модифицирует `_pending` без блокировки, риск race condition. | `src/web/state.py:19-26` | ✅ Pre-Sprint 21 |

### 🟡 P2 — Желательно / документация

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 184 | [Config] | **`.env.example` неполный** — отсутствуют переменные из `settings.py`: `PASSWORD_MIN_LENGTH`, `TOKEN_TTL_MINUTES`, `SESSION_TTL_DAYS`, `DEFAULT_MAX_HR`, `LOG_FILE`, `HTTP_TIMEOUT`, `TIMEZONE`. | `.env.example`, `src/config/settings.py` | ✅ Сверка 03.08.2026 (.env.example содержит) |
| 185 | [Cleanup] | **Неиспользуемые зависимости** — `tzlocal` в основных; `pytest-asyncio`, `freezegun`, `factory-boy` в dev. | `pyproject.toml` | ✅ Сверка 03.08.2026 (deps вычищены) |
| 186 | [Cleanup] | **Мёртвые константы в `audit.py`** — `USER_LOGIN`, `USER_LOGOUT`, `ERROR` объявлены, но не используются. | `src/services/audit.py:14` | ✅ Сверка 03.08.2026 (удалены/ERROR используется) |
| 187 | [Log] | **`audit.py` использует `logging.getLogger("app")`** вместо `get_logger` из `src.utils.logger`. | `src/services/audit.py:93` | ✅ Сверка 03.08.2026 (get_logger, `audit.py:26`) |
| 188 | [Cleanup] | **Мёртвые ссылки в docstring `sync_runner.py`** — упоминаются `SyncService`, `SyncLog`, `full_sync`. | `src/telegram/sync_runner.py:5-6` | ✅ Сверка 03.08.2026 (docstring чист) |
| 189 | [Docs] | **`README.md`: устаревшие цифры** — "parsers разбиты на 9 модулей" (факт 5), "telegram разбит на 12 файлов" (факт 17); Roadmap не отмечает тесты как выполненные. | `README.md` | ✅ Docs audit |
| 190 | [Docs] | **`README.md`: неверная команда для логов** — `logs/app_$(date +%F).log`, реальные файлы `logs/app.log.YYYY-MM-DD`. | `README.md:656-659` | ✅ Docs audit |
| 191 | [Docs] | **`README.md`: дерево `pages/` неполное** — в структуре раскрыт только `session.py`, не хватает `auth.py`, `index.py`, `settings.py`. | `README.md:338-340` | ✅ Docs audit |
| 192 | [Docs] | **`docs/LOGGING.md`: формат файлов и event types** — имена файлов не совпадают с `src/utils/logger.py`; не хватает событий `training.*`, `feedback.*`. | `docs/LOGGING.md` | ✅ Docs audit |
| 193 | [Docs] | **`docs/TESTING.md`: SQLite vs PostgreSQL** — написано "реальный PostgreSQL", но `tests/conftest.py` использует `sqlite:///:memory:`. | `docs/TESTING.md:29` | ✅ Docs audit |
| 194 | [Docs] | **`docs/TESTING.md`: пример `conftest.py` устарел** — `scope="session"` и `init_db`, реально `scope="function"` и `SessionLocal`. | `docs/TESTING.md:64-80` | ✅ Docs audit |
| 195 | [Docs] | **`docs/API_ROUTES_GUIDE.md`: устаревшие примеры** — Pydantic-схемы в `src/models.py` (shim), пример `TrainingService.get`. | `docs/API_ROUTES_GUIDE.md:137-157, 194` | ✅ Docs audit |
| 196 | [Docs] | **`docs/CODE_GUIDELINES.md`: устаревший пример `TrainingService.get`** | `docs/CODE_GUIDELINES.md:393-403` | ✅ Docs audit |
| 197 | [Docs] | **`docs/DEVELOPMENT_GUIDELINES.md`: не упомянут env** — проверочные команды (`from src.startup import create_app`) требуют `DATABASE_URL`, `SECRET_KEY`, `CRED_KEY`. | `docs/DEVELOPMENT_GUIDELINES.md:35-38` | ✅ Docs audit |
| 198 | [Docs] | **`PROJECT_AUDIT.md`: неотмеченные закрытые AUDIT-пункты** — AUDIT-001, AUDIT-002, AUDIT-009, AUDIT-010, AUDIT-013, AUDIT-015 в коде fixed, но DoD-чекбоксы пустые. | `PROJECT_AUDIT.md` | ✅ Docs audit |
| 199 | [Docs] | **`AGENTS.md`: устаревший статус** — Sprint 21 помечен ⬜, но не начат; цифры `src/telegram/` и `src/parsers/` не совпадают с README. | `AGENTS.md` | ✅ Docs audit |
| 200 | [Cleanup] | **Затенение импорта `settings`** — переменная `settings = get_settings(...)` затеняет `from src.config import settings` в `startup.py` и `index.py`. | `src/startup.py:45`, `src/web/routes/pages/index.py:68` | ✅ Fixed 03.08.2026 (user_settings rename) |
| 201 | [Cleanup] | **Magic numbers в фильтре графика** — `3.0 < pace_val < 10.0` в `analysis/utils.py`. | `src/analysis/utils.py:261` | ✅ Fixed 03.08.2026 (CHART_*_PACE константы) |

---

## 🔴 P0 — Исправление модуля классификации тренировок (Sprint 22)

### Корневая причина: `_adaptive_pace_gap` схлопывается до 0.3 для монотонных тренировок

Тренировка #30 ("Москва Бег", 8.157 км) классифицирована как `interval` (11 осцилляций), хотя является монотонной. Причина: `data_gap` (p75-p25) ≈ 0.05 для монотонного бега → `effective_gap = max(0.3, min(1.0, 0.05)) = 0.3` → порог 7:12/км → GPS-шум = "work" фазы → 11 ложных осцилляций.

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 202 | [Bug] | **`_adaptive_pace_gap` схлопывается до 0.3** — для монотонных тренировок `data_gap < 0.5`, adaptive gap = 0.3 → гиперчувствительный детектор осцилляций. Исправление: `data_gap < MIN_EFFECTIVE_PACE_GAP` → вернуть `user_gap`. | `src/analysis/oscillation.py:37-49` | ✅ Sprint 22 |
| 203 | [Bug] | **`_calc_phase_distance` использует `end_idx-1` вместо `end_idx`** — exclusive boundary, неправильная дистанция фазы. 2 failing tests. | `src/analysis/oscillation.py:12-21` | ✅ Sprint 22 |
| 204 | [Bug] | **`classify.py`: нет типа `easy` (Легкая пробежка)** — монотонная Z2 тренировка на 6:00/км классифицируется как `tempo` (catch-all). Нужен отдельный тип для лёгких пробежек. | `src/analysis/classify.py` | ✅ Sprint 22 |
| 205 | [Bug] | **`classify.py`: `var_count >= 3 → interval`** — вторичный сигнал не должен один определять интервалы. Нужно требовать oscillation_count ≥ 2 + (hr_correlated OR avg_hr ≥ Z3). | `src/analysis/classify.py:54-58` | ✅ Sprint 22 |
| 206 | [Bug] | **`classify.py`: `long` требует ВСЕ Z4+ ≤5мин** — один короткий Z4+ участок на 2.5ч long run ломает классификацию. Исправление: z4_time_pct < 15%. | `src/analysis/classify.py:67-69` | ✅ Sprint 22 |
| 207 | [Bug] | **`classify.py`: `recovery` определяется ТОЛЬКО по avg_hr** — темповая Z3 без Z4+ тоже попадает в recovery. Исправление: + z4_time_pct < 5% + avg_pace > 6.0. | `src/analysis/classify.py:70-72` | ✅ Sprint 22 |
| 208 | [Arch] | **Magic numbers в classify.py** — пороги 0.75, 0.70, 60%, 15%, 5%, 3мин, 6.0 не в constants.py. Вынести все пороги классификации. | `src/analysis/classify.py`, `src/config/constants.py` | ✅ Sprint 22 |
| 209 | [Arch] | **Тип `easy` не добавлен в UI + reanalyze** — при добавлении типа нужно обновить TRAINING_TYPES_RU, session.html dropdown, index.py labels, uploads.py labels, reanalyze.py allowed types. | `src/web/state.py`, `src/web/templates/session.html`, `src/web/routes/pages/index.py`, `src/web/routes/uploads.py`, `src/services/reanalyze.py` | ✅ Sprint 22 |
| 210 | [Arch] | **`src/analysis/` отсутствует в Docker rebuild таблице** — AGENTS.md не содержит `src/analysis/` в таблице пересборки. Добавить: `src/analysis/` → `app`. | `AGENTS.md` | ✅ Sprint 22 |

---

*Обновлён: 19.07.2026 — #202-210 ✅ Sprint 22; #211-217 Sprint 24 Data Protection; #218 PK sequence fix*

---

## 🔴 P0 — Критично

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 218 | [Bug] | **`users_id_seq` не синхронизирован** — `setval` вызывается только при создании admin (внутри `if not admin_user`). Если admin уже существует, sequence остаётся на 1 → `UniqueViolation` при регистрации нового пользователя. Вынести `setval` за блок `if not admin_user`. | `src/startup.py:64` | ✅ Сверка 03.08.2026 (`startup.py:60` безусловный setval) |

---

## 🔴 P0 — Data Protection (Sprint 24)

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 211 | [Data] | **README.md: секция «Очистка БД»** (стр.674-684) содержит `docker volume rm running-coach_pgdata` —诱导 к потере данных при следовании инструкции. Удалить секцию, заменить на предупреждение. | `README.md:674-684` | ✅ Sprint 24 |
| 212 | [Data] | **bin/docker.sh: защита от `-v`** — если передан флаг `-v`/`--volumes`, требовать ввод `CONFIRM` перед выполнением. Иначе — abort. | `bin/docker.sh` | ✅ Sprint 24 |
| 213 | [Data] | **bin/backup_db.sh (новый)** — pg_dump из контейнера db в `backups/YYYY-MM-DD_HH-MMSS.sql.gz`, автоматическая ротация (хранить последние 7 бэкапов). | `bin/backup_db.sh` | ✅ Sprint 24 |
| 214 | [Data] | **AGENTS.md правило #9: BACKUP BEFORE DEPLOY** — перед любым `docker compose build/up` → сначала `bin/backup_db.sh`. Никогда `down -v`, никогда `volume rm`. | `AGENTS.md` | ✅ Sprint 24 |
| 215 | [Data] | **`/delete_me` без подтверждения** — мгновенное удаление ВСЕХ данных. Два шага: `/delete_me` → предупреждение → `/delete_me_confirm`. Таймаут 5 мин. | `src/telegram/handlers/account.py` | ✅ Sprint 24 |
| 216 | [Data] | **ON DELETE CASCADE на TrainingSession** — если User удалён, каскадно удаляются ВСЕ тренировки. Заменить на RESTRICT. Миграция Alembic. | `src/domain/models/training.py:17` | ✅ Sprint 24 |
| 217 | [Data] | **startup.py: safety check** — после init_db() проверить user_count. Если 0 → WARNING в лог «Database has 0 users — possible volume loss». | `src/startup.py` | ✅ Sprint 24 |

---

## 📌 Находки деплоя коуча (23.08.2026)

| # | Тип | Описание | Файлы | Статус |
|---|-----|----------|-------|--------|
| 240 | [Docs] | `docker compose start` НЕ пересоздаёт контейнер из нового образа — бот остаётся на старом коде (поймано 23.08). | `CLAUDE.md`, `AGENTS.md`, `docs/coach/DEV_PLAN.md` | ✅ C9 23.08.2026 (предупреждение в CLAUDE.md §7, AGENTS.md §8, DEV_PLAN C3; CHECKLIST_MIGRATION.md уже был корректен — там `up -d`) |
| 241 | [Coach] | Переезд с моста на личный API-ключ. | `.env`, `bin/coach_llm_bridge.py` | ⏸ **Не планируется** (решение владельца 25.08.2026: корпоративная подписка, мост — постоянный режим). Переезд при желании = `ANTHROPIC_API_KEY` в `.env` — код готов (`get_llm()`: ключ → мост → Null) |
| 242 | [Coach] | **Гайды методики в режиме моста**: `search_guides` простаивает (tool-цикл неактивен), проза методики до модели не доезжает (только key_rules_digest). Инлайнить топ-чанки релевантных guides в extras разбора (по типу тренировки/флагам) и недельного отчёта — переформулировано 25.08.2026 (было «проверить search_guides при переезде на ключ»). | `src/coach/orchestrator.py`, `src/coach/knowledge/loader.py` | ✅ E3+E2 25.08.2026: чанки методики инлайном (`method_guides`) в разбор и недельный отчёт; WEEKLY_PROMPT опирается на plan-гайды |
| 243 | [Coach] | Правило P4 (план/цель): нет `race_date` и шаблонов планов — завести поля цели с датой и генерацию плана (DEV_PLAN §2, C8+). | `src/domain/models/user.py`, `src/coach/` | ⬜ |
| 244 | [Coach] | Правило P5 (persональные уроки): вернуть `lessons`-продюсер, когда накопится фидбек (RPE/боль); предпочтения — в профильный блок промпта. | `src/coach/` | ⬜ |
| 245 | [Coach] | Офлайн-дистилляция книг (Лидьярд/Фицджеральд/Дэниелс) в guides/*.md — скрипт в `bin/`, когда владелец добавит файлы книг; формат чанков уже совместим с loader. | `bin/`, `src/coach/knowledge/` | ✅ E2 25.08.2026: Фицджеральд+Дэниелс → 8 гайдов (методика 40–46, планы 60/61); Ноукс (дайджест Smart Reading) пропущен. FB2-экстрактор чинён (`<body>` без base64-картинок), retry/чекпойнт в distill_books.py |
| 246 | [Coach] | Вернуть персонализацию (EWMA-калибровка UserModel, PredictionLog residuals), когда feedback coverage вырастет (сейчас копится через боль/RPE). | `src/coach/` | 🟡 02.09.2026: продюсер пишет residuals (prediction_log.py, идемпотентно) — «только пишем»; потребитель (EWMA-коррекция прогнозов) — после M3.2, иначе residuals до/после смены якоря зон несравнимы |
| 247 | [Coach] | Numeric-consistency checker: проза LLM не должна противоречить числам карточки (сейчас — только правило промпта, остаточный риск в ADR). | `src/coach/numeric_check.py` | 🟡 v1 ✅ 29.08.2026: детект+лог+meta.numeric_mismatch, текст не режем; обрезание прозы и weekly_plan-проза — после недели наблюдений |
| 248 | [Arch] | `training_type_override` не слит с `training_type` в web/`/stats` (коуч решает сам через `effective_training_type`). Слить в остальном приложении. | `src/web/`, `src/telegram/handlers/stats.py` | ⬜ |
| 249 | [Config] | Привести recovery-шкалу к Coros §12 (20/70/90): сейчас `RECOVERY_PCT_MODERATE=30` — исторический порог display-слоя. | `src/coach/config.py`, `src/services/recovery_view.py` | ⬜ |
| 250 | [Docs] | В BACKLOG дублируется номер 139 (две разные записи). Не перенумеровывать (ссылки в коммитах); при следующей чистке пометить вторую как 139-bis. | `BACKLOG.md` | ⬜ |
| 251 | [Coach] | `turns_today` считает ВСЕ assistant-строки, включая fallback-карточки (`meta.fallback`) — детерминированные разборы бэкфилла жгут дневной LLM-бюджет 40 и могут заблокировать утренний вердикт. Не считать fallback-строки. | `src/services/repositories_coach.py` | ✅ 29.08.2026 (счёт в Python без meta.fallback) |
| 252 | [Bug] | `_merge_similar_segments` теряет `temperature`/`weather_code` сегментов при слиянии (ключи есть до merge, после — нет). | `src/analysis/segment.py` | ⬜ |
| 253 | [Идея] | Переключить `TrainingSession.elevation_gain/loss` на сглаженный расчёт: `calc_elevation` — naive-сумма дельт, завышает набор на GPS/баро-шуме. Сглаженный расчёт появится в D2 (`analysis/gap.py`) — переиспользовать. **Требует решения владельца** (изменит числа в UI). 01.09.2026: альтернативный эталон — `total_ascent/descent` из session-сообщения FIT (F1 парсер v2, #285). | `src/analysis/utils.py` | ⬜ (01.09: сглаженные высоты уже используются в `gap.downhill_block` — осталось переключить `TrainingSession.elevation_*`) |
| 254 | [Coach] | Пороги сна в `signals`/P1 (safety-граница «недосып → осторожнее») — после накопления данных сна из D8. | `src/coach/config.py`, `src/coach/rules/p1_safety.py` | ✅ 02.09.2026 (правило 15 p1_safety: <6 ч без интенсива, <5 ч max_zone=2+40 мин; v1 — абсолютные пороги, скриншот за сегодня; личная медиана — после накопления) |
| 255 | [Data] | `precipitation` скачивается из Open-Meteo и выбрасывается (`weather.py` использует только temps/codes). Сохранять и отдавать в разбор (дождь/снег — фактор темпа/пульса). | `src/parsers/weather.py`, `src/analysis/__init__.py` | ⬜ |
| 256 | [Coach] | `InsightRepository.release/reclaim_stale_running` — read-modify-write без атомарного предиката: теоретическая гонка reclaim-джобы с живым исполнителем (двойной перевод в pending → лишний повторный разбор, не потеря данных). Находка db-safety-ревью D1. | `src/services/repositories_insights.py` | ✅ 29.08.2026 (атомарные UPDATE с предикатом status='running') |
| 257 | [Идея] | **Сон из Coros**: три штатных endpoint'а отдают только sleep-HRV (разведка D8, 25.08.2026). У приложения Coros наверняка есть отдельный sleep-endpoint (неофициальный API) — найти (сниффинг трафика приложения) и добавить длительность/фазы/оценку сна в DailyMetrics. До тех пор разбор опирается на HRV/RHR/recovery. | `src/watch/coros.py`, `src/services/sync/health.py` | ✅ 30.08.2026 — вместо перехвата: скриншот сна → vision-мост (/vision) → DailyMetrics (см. #257-shot) |
| 258 | [Coach] | История чата провоцирует мимикрию LLM: `recent_messages` не фильтрует по kind (morning/review/weekly вперемешку с чатом, окно 8 сообщений ≈ 4 обмена) и в историю идёт финальный составной текст (карточка+вопрос), а не `turn.message` — модель копирует форму. Рассмотреть: хранить прозу отдельно от карточки (meta) и/или kind-фильтр окна. Находка инцидента 26.08.2026 (дубли карточки/вопроса). | `src/services/repositories_coach.py`, `src/coach/turn_context.py` | ✅ 29.08.2026 (оба: kinds chat/morning/review + meta.prose + метки синтетических промптов) |
| 259 | [Analytics] | Наклон OLS-линии HR↔GAP-темп сильно занижен (attenuation: шум км-точек по x, межсессионные условия — жара/усталость/дрейф): у активного пользователя b=−2.4 при эмпирических ~−8 bpm за мин/км. На инверсию больше не опираемся (26.08: `pace_at_hr_band` — эмпирическая медиана полосы), но `hr_vs_baseline`/`deviation_flag` пользуются этой линией — ожидаемый HR и z-скоры смещены. Рассмотреть: сессионные средние вместо км-точек, Deming/ортогональная регрессия или поправка на дрейф. | `src/analysis/hr_baseline.py` | ⬜ (01.09: хвостовые км-точки <500 м исключены из baseline (#283/F0) — влияние на наклон не перемерено) |
| 260 | [Coach] | `render.py` конвертирует время только через `settings.timezone`, игнорируя `user.timezone`/`session.timezone` — для мульти-юзера в другом поясе снова UTC-подобный сдвиг. Перевести на `src/utils/timeutils.local_dt` (инцидент 26.08.2026: бот показывал UTC; telegram-слой поправлен, коуч — нет). Родственные: #124 (today_start), #220 (weekly_volume бакеты по UTC). | `src/coach/render.py:73-75` | ✅ 26.08.2026 (`render_prescription(user=...)` → `local_dt`) |
| 261 | [Arch] | `telegram/main.py` ставит `Defaults(tzinfo=settings.timezone)` — расписание утро/вечер одно на всех, не per-user (`user.timezone`). Для мульти-юзера в другом поясе сообщения приходят по чужому времени. | `src/telegram/main.py:50` | ⬜ |
| 262 | [Bug] | **Полуночное окно 00:00–03:00 МСК: дедуп карточки и planned_workout-контекст слепнут.** `clamp` пишет `when = datetime.now(UTC).date()` (ещё вчера), а `_unchanged_today` и `_build_extras` фильтруют `for_date >= date.today()` (локальная, уже сегодня) → назначение «теряется»: карточка дублируется, LLM не видит planned_workout. Ловится тестами `test_influence.py::test_planned_workout_reaches_context`, `test_orchestrator.py::test_chat_unchanged_proposal_renders_reminder_not_card` (падают только в этом окне). Родственные: #124, #220, #260. Обнаружено 27.08.2026 ~00:20 МСК. Дополнение 29.08.2026: якорь `for_days_ahead` (LLM считает от локального «Сейчас», clamp — от UTC `now.date()`) в том же окне даёт сдвиг целевого дня на −1 — чинить вместе. | `src/coach/safety.py` (`when=now.date()`), `src/coach/orchestrator.py` (`_unchanged_today`, `_build_extras`) | ✅ 29.08.2026 (`finalize(now=user_now(user))` — единый локальный якорь; фильтры planned/дедуп согласованы; UTC-бакеты weekly_volume — отдельно #220) |
| 263 | [Coach] | **Расширить выборку км-точек темповыми сегментами** — `_collect_window_points` берёт только steady-типы (easy/long/recovery), на темповом диапазоне точек в полосе ±0.25 мин/км часто <5 → прогноз «пульс на темпе» (`expected_hr_at_pace`) будет часто None («мало данных»). Кандидаты: км-точки tempo/interval-сессий из ровных сегментов. | `src/services/workout_insights.py:_collect_window_points` | ⬜ |
| 264 | [Coach] | **Ориентир темпа/дистанции в карточке пропадает для recovery/Z1 и Z3+** (инцидент 27.08.2026: восстановительный бег без строки ориентира — владелец выбирает по ней маршрут). Причина: `pace_at_hr_band` требует ≥5 км-точек в односторонней полосе `[потолок−10, потолок]`, а пульс сосредоточен в узком коридоре (для Z1 потолок 125 → 2 точки; Z2 → 24, работает). Решение — ступенчатая деградация A (узкая полоса) → B (широкая ±25 + локальная поправка наклоном, гейт Δ≤15) → C (медиана `avg_pace` сессий типа) → D, с `quality` в `predicted` и честной пометкой «прикидка» в карточке. **Деградированные оценки не должны попадать в safety-clamp** (`_pace_clamp_context` — только уровень A). Полное задание с диагностикой, формулами, проверкой на живых данных и тестами: `docs/coach/TASK_pace_estimate_fallback.md`. Родственные: #259 (занижённый наклон OLS), #263. | `src/analysis/hr_baseline.py`, `src/services/workout_insights.py`, `src/coach/prescriber.py`, `src/coach/render.py` | ⬜ (01.09: появилась нормативная ступень от `ltsp` в `segments.py` — переиспользовать как C′ в `predict_volume`, именование `quality`→`pace_source`; детали — в шапке ТЗ); карточка недели печатает ~темп/≈км из прогноза ✅ 02.09.2026 |
| 265 | [Coach] | **`daily_metrics_morning` в разборе берётся по UTC-дате тренировки** — `get_workout_detail` вызывает `metrics_for_date(..., session.begin_ts.date())`: для поздневечерней пробежки (после 00:00 UTC-следующего-дня по локали) подтянется утро не того дня. Найдено при фиксе «утренней тренировки» 28.08.2026 — не чинено «заодно»; использовать `session_local_dt(...).date()`. | `src/coach/tools/history_tools.py:~107` | ✅ 29.08.2026 |
| 266 | [Arch] | **`orchestrator.py` перевалил за 400 строк** (~425 после фикса времени 28.08.2026) — вынести `_build_extras` (и, возможно, `_unchanged_today`) в отдельный модуль. | `src/coach/orchestrator.py` | ✅ 29.08.2026 — `build_extras`/`unchanged_today`/`history` → `src/coach/turn_context.py`; orchestrator ~370 строк |
| 270 | [Arch] | **`src/services/workout_insights.py` = 409 строк** (>400, после M2.2 30.08.2026) — вынести резолверы БД-входов (`_plan_for_session`/`_rpe_history`/`_user_max_hr`) или сборку метрик в отдельный модуль. Мелочь, не срочно. | `src/services/workout_insights.py` | ✅ 01.09.2026 (F3: baseline → `insights_baseline.py`, кросс-чеки → `analysis/data_checks.py`; 324 строки) |
| 267 | [Coach] | **`evening_check_needed` / `planned_workout.for_date` — на серверной/UTC-дате**, не на поясе пользователя (вне LLM-промпта, низкий риск; та же семья, что #262). Перевести на `user_now(user).date()` вместе с #262. | `src/coach/orchestrator.py` (`_unchanged_today`, `_build_extras`, `evening_check_needed`) | ✅ 29.08.2026 (build_extras + evening_check_needed на user_now) |
| 268 | [Coach] | **Детерминированный анализ тренировок — расширение метрик (M1–M3).** Аудит 29.08: из 10 ключевых параметров разбора считаются 3, приближённо 2, отсутствуют 5; LLM оценивает вычислимое «на глаз». Руководство с формулами, порогами, флагами и порядком внедрения — `docs/coach/METRICS_GUIDE.md`: M1 — time-in-zones точно + дисциплина лёгкого дня, стабильность темпа/HR, чистый HR-drift, баллы Дэниелса, потолки качества, доля длительной, каденс, RPE-триангуляция, разминка; M2 — восстановление между интервалами, план vs факт (`linked_session_id`); §6 — унификация флагов (`decoupling_high` vs `hr_drift_high`); M3 — якорь ПАНО/VDOT (решение владельца). Родственные: #259, #263, #264, #265. | `docs/coach/METRICS_GUIDE.md`, `src/services/workout_insights.py`, `src/analysis/` | 🟡 почти закрыт: M1+§6 ✅ 29.08, M2.2 ✅ 29.08, M2.1 (HRR) ✅ 01.09 (F3), M3.1 (LTHR/LTSP) ✅ 01.09 (F4), M4 ✅ 01.09 (F5/F6, §11); осталось M3.2 (полевой тест ПАНО — за владельцем) и хвосты §7 (#289) |
| 269 | [Coach] | **Недельный персистентный план** (решения владельца 29.08.2026: вс 19:00 после отчёта, запись сразу, утро подтверждает). `planning.py` — детерминированные числа недели (target_km: прогрессия ≤10% / deload 75% по мезоциклу 3:1, счётчик в `params_json.week_plan`, потолки качества/длительной); `weekly_plan.py` — LLM распределяет неделю (`CoachTurn.weekly_plan`, каждый день через clamp) → строки `status='planned'`; утро — `confirmed` (UPDATE) / `adjusted`; отчёт сверяет неделю (`week_plan_review`); `/plan` + regex-триггер. Фундамент #243. | `src/coach/planning.py`, `src/coach/weekly_plan.py`, DEV_PLAN §12 | ✅ 29.08.2026 (обкатка: первый цикл вс→вс) |

## 🟠 Отложенные находки ревью (03.08.2026 — подготовка к аналитике)

MAJOR/тюнинг — «тихо-неверно», но не блокеры; править точечно при работе над нужным skill/этапом (не «заодно»).

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 219 | [Analytics] | `load_ratio` исключает дни отдыха (`training_load IS NOT NULL`) → ACWR смещён; `ratio=0.0` неотличим от «нет хронических данных». Рефактор при реализации `skills/load.py`. | `src/services/repositories.py` (load_ratio) | ✅ C1 23.08.2026 (`CoachRepository.acwr`: дни отдыха = 0, мало данных → `ratio=None`; `load_ratio` удалён) |
| 220 | [Analytics] | `weekly_volume` бакетит недели по UTC, игнорируя `TrainingSession.timezone` — off-by-one для не-UTC. | `src/services/repositories.py` (weekly_volume) | ⬜ |
| 221 | [Analytics] | `compute_slope` индекс-based (0,1,2…), игнорирует календарные разрывы → величина наклона неверна (знак корректен). Взвесить по датам при количественном использовании. | `src/services/analytics_helpers.py` | ⬜ |
| 222 | [Classification] | Тюнинг порогов `classify.py` (tempo — catch-all) требует размеченной выборки тренировок; без неё менять пороги рискованно. Собрать labeled data → пересмотреть. | `src/analysis/classify.py` | ⬜ |
| 223 | [Arch] | Планировщик стартует per-worker; синглтон только в пределах процесса → дубли синков при `--workers>1`. Advisory-lock / leader election перед масштабированием. | `src/scheduler.py`, `src/startup.py` | ⬜ |
| 224 | [Arch] | Нет watchdog у потока планировщика: неперехваченное исключение вне внутренних try/except убивает `_loop` навсегда до рестарта. | `src/scheduler.py` | ⬜ |

---

## 🟢 Прод-деплой / ops (03.08.2026)

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 225 | [Ops] | **Healthcheck бота был ложно-unhealthy** — `ps aux \| grep` в `docker-compose.yml`, но в образе `python-slim` нет `ps` (#178 был неполным фиксом). Заменено на `grep -q run_telegram_bot /proc/1/cmdline`. Бот работал, ломалась только проверка. | `docker-compose.yml` (bot healthcheck) | ✅ 03.08.2026 |

---

## 🔴 Аудит фундамента 05.08.2026 — план ремедиации (этапы 1–6)

Полный аудит критических промахов перед модулем коуча. Этап 0 (рантайм-фиксы: `/stats` бота,
reanalyze, `performance` Float) выполнен 05.08.2026 — см. CHANGELOG. Порядок этапов важен:
1 (PG-тесты) до 3/4 (миграции проверяемы); 3 до 4 (backfill FIT матчится по external_id);
**3, 4, 5 — гейт перед Этапом 1 коуча**. Детальный план — `/home/nimda/.claude/plans/iterative-weaving-scone.md`.

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 226 | [Tests] | **Этап 1: PG-режим тестов** (⚠️ одобрено пользователем 05.08.2026, уточняет §6 CLAUDE.md). Opt-in через отдельную `TEST_PG_URL` (НЕ `DATABASE_URL`) + guard «только localhost/CI», иначе как сейчас SQLite. Схема на PG — через `alembic upgrade head` (ловит дрейф моделей/миграций), для SQLite — `PRAGMA foreign_keys=ON`. CI: оба прогона. После внедрения обновить §6 CLAUDE.md. | `tests/conftest.py`, `.github/workflows/ci.yml` | ✅ 05.08.2026 (TEST_PG_URL + alembic-схема + FK pragma; CI два прогона) |
| 227 | [Sync] | **Этап 2: надёжный авто-sync.** Сейчас при исключении `sync/health.py:188-194` и `sync/activities.py:243-249` возвращают `0` (=успех) → `last_*_sync_at` двигается → пропущенные тренировки теряются НАВСЕГДА (буфер всего 2ч). Контракт: ошибка → `-1`, таймстемп не двигать. Плюс: счётчики сбоев в `WatchCredential` (синкают 2 процесса — app и bot, in-memory нельзя) + telegram-notify после 3 подряд; экспоненциальный backoff; использовать мёртвый кэш токена (`watch.py:17-18`, сейчас re-login каждый синк — риск бана неофициального API); throttle между страницами `list_activities`. | `src/services/sync/{health,activities,orchestrator,utils}.py`, `src/watch/coros.py` | ✅ 05.08.2026 (-1 при ошибке, счётчики+notify, backoff, кэш токена, throttle) |
| 228 | [Data] | **Этап 3: внешний ID активности + честный дедуп** (гейт коуча). Coros `labelId` выбрасывается (`coros.py:119`); дедуп — посекундное равенство `start_time` API и `begin_ts` первого FIT-трекпоинта (`activities.py:88-105`) — два разных источника времени, UNIQUE в БД нет вообще. Добавить `external_activity_id`+`source_brand`+`file_sha256` (и в `DeletedTraining`), частичные UNIQUE-индексы `WHERE ... IS NOT NULL`, дедуп ручных загрузок по SHA256, fallback-окно ±120с только для legacy NULL. Backfill-скрипт `bin/backfill_external_ids.py` с `--dry-run` (бэкап + показать отчёт перед `--apply`). | `src/domain/models/training.py`, `src/services/sync/activities.py`, `src/web/routes/uploads.py` | ✅ 05.08.2026 (ext id + частичные UNIQUE + dedup.py + SHA256; backfill-скрипт готов — запустить на проде с --dry-run) |
| 229 | [Data] | **Этап 4: хранение сырых FIT/TCX** (гейт коуча). Сейчас FIT удаляется после парсинга (`activities.py:46`), `trackpoints_json` — 7 полей УЖЕ после `clean_trackpoints` → улучшить GPS-очистку или добыть новые метрики (мощность, running dynamics) невозможно, история Coros API конечна — **backfill запустить как можно раньше**. Хранить `uploads/raw/<user_id>/<sha256>.<ext>` + `raw_file_path` в БД; ⚠️ volume `./uploads` смонтировать и в контейнер `bot` (он тоже синкает — `sync_runner.py:72`); `reanalyze` — от сырья с fallback на `trackpoints_json`; включить `uploads/` в бэкап. | `docker-compose.yml`, `src/services/sync/activities.py`, `src/services/reanalyze.py` | ✅ 05.08.2026 (raw_files.py + reanalyze от сырья + volume bot; backfill-скрипт готов — запустить на проде раньше) |
| 230 | [Coach] | **Этап 5: единый источник порогов** (гейт коуча, можно параллельно). Пороги readiness/RHR/tired захардкожены inline в `recovery_view.py:44-64,137,155-201` и дублируются в `coach/config.py` + `docs/coros_health_metrics.md` — три источника правды. Вынести именованные пороги в `coach/config.py`, `recovery_view` импортирует оттуда; **удалить `sleep_quality: 0.15` из `READINESS_WEIGHTS`** (данных сна в `DailyMetrics` нет — вес по несуществующей метрике) и перенормировать к 1.0; анти-дрейф-тест `sum(weights)==1.0` + сверка порогов. | `src/coach/config.py`, `src/services/recovery_view.py` | ✅ 05.08.2026 (пороги в coach/config.py, sleep_quality удалён, анти-дрейф-тесты) |
| 231 | [Arch] | **Этап 6: владение БД-сессией** (не блокирует коуча, вести фоном, по одному под-шагу за коммит). ~30 `SessionLocal()` внутри сервисов при `Depends(get_db)` в вебе → нет unit-of-work, detached-объекты из `user_service` (риск `DetachedInstanceError` при росте домена), `get_db` определён дважды (`domain/models/base.py:94` и `api/deps.py:26`). План: канонический `get_db` в `api/deps`; `db: Session` обязательным параметром в `user_service`/`repositories`/sync; `SessionLocal()` — только в композиционных корнях (зафиксировать CI-grep'ом). ⚠️ §5: смена сигнатур сервисов — предупреждать. | `src/services/user_service.py`, `src/services/repositories.py`, `src/api/deps.py` | ✅ 05.08.2026 (get_db один, db параметром, SessionLocal только в корнях + тест-гвард) |
| 232 | [Data] | **Repair `performance`** — значения, сохранённые до фикса Integer→Float (05.08.2026), округлены необратимо. Скрипт: перезапросить Coros за доступное окно истории и UPDATE существующих строк (текущий sync пропускает существующие даты — само не починится). Чем раньше — тем больше вернём. | `bin/` (новый скрипт), `src/services/sync/health.py` | ⬜ |
| 233 | [Tests] | `tests/test_health.py:7` — `os.environ.setdefault("SECRET_KEY", ...)`: CI grep-гвард по паттерну `os.environ.setdefault` может его зацепить (это не DATABASE_URL, но паттерн совпадает). Заменить на явное присваивание. Найдено db-safety-ревью 05.08.2026. | `tests/test_health.py:7` | ⬜ |
| 234 | [Ops] | **Деплой миграций с ALTER — останавливать bot заранее.** При деплое 05.08.2026 первая попытка `alembic upgrade` (ALTER TYPE на daily_metrics) конкурировала с транзакциями бота → прерванная попытка оставила колонку без штампа версии → crash-loop app на DuplicateColumn. Восстановлено: stop app+bot → DROP пустой фантомной колонки → чистый upgrade. Добавить в чеклист деплоя: `docker compose stop bot` перед миграциями с ALTER/DDL. | `docs/CHECKLIST_MIGRATION.md` | ⬜ |
| 235 | [Ops] | **Ошибка Alembic на старте app гаснет молча** — при DuplicateColumn в crash-loop не было ни трейсбека в stdout, ни `logger.exception` в logs/app.log (uvicorn exit code 3 без вывода). Разобраться, куда уходит лог `on_startup` до инициализации логгера, и сделать ошибку миграции громкой. | `src/startup.py:34-41` | ⬜ |
| 236 | [Bug] | **`/delete_me`: `user.telegram_chat_id = None` пишется в detached-объект** (`get_user` возвращает пользователя из закрытой сессии) → отвязка chat_id не персистится; данные удаляются, но аккаунт остаётся привязанным к Telegram. Тот же класс бага, что и вес (исправлен 05.08.2026 через weight_service). Починить через session-bound user в сессии хендлера. | `src/telegram/handlers/account.py:60` | ⬜ |
| 237 | [Идея] | **Авто-reanalyze после авто-поднятия max_hr** — тренировки батча проанализированы со старым max_hr (зоны слегка завышены). `reanalyze_training` умеет пересчёт от сырья (дёшево), но добавляет латентность/failure-mode в sync. Пользователь решил 06.08.2026: в v1 не пересчитывать (погрешность от нескольких bpm мала, пересчёт доступен кнопкой). | `src/services/hr_max.py`, `src/services/reanalyze.py` | ⬜ |
| 238 | [Идея] | **Эвристика «ранний пик на низком темпе = глюк датчика»** для адаптивного max_hr: пик в первые минуты пробежки при темпе ниже исторического easy — вопросы к датчику (cadence-lock оптики даёт УСТОЙЧИВЫЙ ложный пульс, медиана его не ловит). v1 закрывает это правилом повторяемости (≥3 превышений за 30д); вернуться, если появятся ложные предупреждения. | `src/services/hr_max.py`, `src/analysis/utils.py` | ⬜ |
| 239 | [Фикс] | **Валидация ручного ввода max_hr в POST /settings** — сейчас форма принимает любое int; `ValidationError("max_hr", "must be between 100 and 220")` объявлен в `src/exceptions.py:52`, но никем не поднимается. Использовать `MAX_HR_CAP`/floor 100 из `config/constants.py` (те же границы, что и у кнопки `maxhr:set`). | `src/web/routes/pages/settings.py:75` | ⬜ |
| 271 | [Фикс] | **Markdown-разметка разбора иногда не парсится Telegram** — `telegram.utils | Markdown parse failed (can't find end of the entity …) — resending plain` (инцидент 30.08, разбор пробежки). Сейчас деградирует в plain-text (доставка не теряется), но текст едет без форматирования. Разобраться, что генерит незакрытую сущность (вероятно спецсимвол в числах/юните разбора), и экранировать при сборке сообщения. Низкий приоритет. | `src/telegram/utils.py` | ⬜ |
| 272 | [Coach] | **Экспорт структурированной тренировки в часы Coros** — чтобы ИИ-тренер загружал тренировку (сегменты с пульс/темп-целями) прямо на часы, а не только текстом в карточке. Изучить Coros training/workout API. Пока — карточка по сегментам (M2.1) + ручной ввод/бег по часам. | `src/coach/segments.py`, sync-слой | ⬜ Будущее (запрос владельца 01.09.2026) |
| 273 | [Coach] | **Нормативный темп по зонам (VDOT/ПАНО/LTHR) — M3** — сейчас темп сегментов берётся из личной истории (на высоком пульсе часто пусто → «мало данных»). Задействовать уже синкаемый `lthr` (`DailyMetrics`) / VDOT, чтобы давать темп ускорений детерминированно. 01.09.2026: расписано как **F4/M3.1** (METRICS_GUIDE §8, DEV_PLAN §9 F-серия); `ltsp` (пороговый темп) тоже уже синкается. | `src/coach/config.py`, `src/coach/segments.py`, `docs/coach/DEV_PLAN.md` (F4) | ✅ 01.09.2026 (F4/M3.1: pace_source=threshold от ltsp) |
| 274 | [Чистка] | **Мёртвые константы GPS-очистки** — `MAX_CREDIBLE_PACE`/`MAX_GPS_JUMP_M`/`MIN_DISTANCE_FOR_VALID_SEGMENT_M` в `config/constants.py:6,14-15` нигде не импортируются: реальные значения захардкожены дефолтами сигнатур (`gps.py:14`, `analysis/__init__.py`, парсеры) и per-user полями. Свести к одному источнику (нарушение golden rule №1). Найдено при работе над GPS-квалиметрией 01.09.2026. | `src/config/constants.py`, `src/parsers/gps.py` | ⬜ (01.09: дубль растёт — 3.0 захардкожен и в `tests/test_gps_quality.py`; той же породы `max_age_days=45` в `latest_lthr/latest_ltsp`) |
| 275 | [Coach] | **Персональная длина шага по истории** — fallback-ступень оценки дистанции при GPS-сбое: если чистых окон в самой тренировке мало (`quality="rough"`, дефолтный шаг 1.0 м), брать медианную длину шага пользователя из прошлых чистых тренировок на близком каденсе/пульсе. Сейчас есть калибровка только внутри тренировки (`gps_quality.py`). 01.09.2026: FIT пишет `step_length` per-record и `avg_step_length`/`total_strides` в session (покрытие 99.8%) — после F1 (#285) калибровка не нужна: брать шаг с часов напрямую. | `src/analysis/gps_quality.py` | ⬜ (01.09: сырьё готово — F1 даёт `sl` per-record и `device_summary.avg_step_length_mm`/`total_strides`; осталось подключить в gps_quality вместо дефолта 1.0 м) |
| 276 | [Coach] | **Калибровка easy-порога классификации** — №42 (лёгкий бег, avg HR 140 при max_hr 180 = 78%) классифицируется «tempo»: `EASY_MAX_HR_PCT=0.75` строже фактического лёгкого диапазона пользователя. Рассмотреть персональный порог или пересмотр константы. Замечено при разборе GPS-кейса 01.09.2026. | `src/config/constants.py:60`, `src/analysis/classify.py` | ✅ 01.09.2026 (F4: recovery/easy-гейты от LTHR — 0.81/0.89·lthr; EASY_MAX_HR_PCT — только fallback) |
| 277 | [Фикс] | **«Тихий» перекос avg_pace при пересборке дистанции** (аудит `docs/AUDIT_averaging_2026-09-01.md` §3.1) — быстрые дельты выбрасываются из дистанции, но их ВРЕМЯ остаётся → темп медленнее реальности. Кейс №37: часы 7.61 → БД 8.06 мин/км (+0.45) при 5.6% вырезанного, молча (ниже порога gps_unreliable 20%). Фикс: копить dropped-время рядом с dropped-дистанцией и исключать его из avg_pace (duration_minutes оставить elapsed). | `src/analysis/__init__.py:76-95` | ✅ 01.09.2026 (F0, insights v5) |
| 278 | [Фикс] | **Сводный GAP смещён вверх**: среднее темпов взвешено самим темпом = Σp²/Σp (контргармоническое; 4:00+6:00 → 5.2 вместо 5:00). Идёт в LLM (`gap_avg_min_km`/`avg_pace_min_km`). Фикс: время- или дистанция-взвешенное среднее (Σt/Σd). Аудит §3.2. | `src/analysis/gap.py:143-147` | ✅ 01.09.2026 (F0, insights v5) |
| 279 | [Фикс] | **Разрывы записи в time-in-zones**: дельта паузы целиком уходит в зону последнего HR (обе реализации); HR-дропаут не разрывает Z4-отрезок → интервалы склеиваются → ложный `interval_segment_too_long`; знаменатели `classify` (elapsed с дырами) и `session_metrics` (HR-покрытое) расходятся. Фикс: cap дельты по образцу `DRIFT_MAX_SAMPLE_GAP_SEC` + разрыв Z4-отрезка на дропауте. Аудит §3.3. 01.09.2026: после F1 (#285) паузы известны ТОЧНО из timer-событий FIT — эвристика останется fallback'ом (часть F0/F2). | `src/analysis/segment.py:78-81`, `src/analysis/session_metrics.py:56-61` | ✅ 01.09.2026 (F0: cap разрывов записи + разрыв Z4; timer-паузы точные — в device_summary) |
| 280 | [Фикс] | **Сырой max HR в UI**: `max_heart_rate = max(hr)` без фильтра — спайк датчика (cadence-lock) попадает в UI/Telegram, хотя `hr_peak_smoothed` уже считается (кормит только адаптивный max_hr). Показывать сглаженный пик, сырой хранить рядом. Санити-диапазона/скорости изменения HR нет нигде. Аудит §3.4. | `src/analysis/__init__.py:104` | ✅ 01.09.2026 (F0, insights v5) |
| 281 | [Фикс] | **Двойное усреднение зон**: `zone_distribution` (скилл 80/20) и `history_tools` кладут всю длительность сегмента в зону его avg_hr → расходится с посекундным `computed.time_in_zones`; recovery-кусок интервальной маркируется «hard z4». Перевести на посекундные зоны. Аудит §3.5, §2. | `src/services/repositories.py:88-98`, `src/coach/tools/history_tools.py:86-89` | ✅ 01.09.2026 (F0, insights v5) |
| 282 | [Фикс] | **cad==0 в средних каденса**: `avg_cadence` и сегментные средние включают нулевой каденс (стояние) → UI-каденс ниже `cadence_block` (там 0 исключён). Единый контракт: исключать 0, взвешивать временем. Аудит §3.6. | `src/analysis/__init__.py:219`, `src/analysis/segment_km.py:75` | ✅ 01.09.2026 (F0, insights v5) |
| 283 | [Фикс] | **Хвостовой неполный км (200–1000 м) как полный**: per_km не помечает длину → `quality_volume` считает его за 1.0 км, `hr_baseline.km_points` даёт полный вес шумной точке (вероятный вклад в заниженный наклон базовой линии — #259); последние 0–200 м отбрасываются вовсе. Фикс: нести `km_len_m` в per_km, взвешивать/фильтровать по нему. Аудит §3.7. | `src/analysis/gap.py:131-137`, `src/analysis/hr_baseline.py:27-35` | ✅ 01.09.2026 (F0, insights v5) |
| 284 | [Чистка] | **Пакет находок аудита усреднений** (низкий приоритет, полный список — `docs/AUDIT_averaging_2026-09-01.md` §3.8): лаг заднего окна rolling pace (~23 с, затухание пиков интервалов на графике); клампы графика отбрасывают точки без индикации + наивный даунсемпл; хардкод 5.0 в `interpolate_paces`; окна по точкам вместо времени (smart-recording ×5); elapsed vs moving несогласованность (moving-pace нет как понятия); смешение временных баз в `_ef`; GPS-мусор при HR≥130 не чистится; off-by-one/мёртвые ветки `oscillation.py`; несогласованная атрибуция HR к дельте; порог `_adaptive_min_diff` от сырого ряда; мёртвый код (`compute_ewma`, `compute_moving_average`, `CALIBRATION_EWMA_ALPHA`, метка `hr_pace_mismatch`); O(n²) в `build_hr_pace_series`. | см. аудит | 🟡 частично 01.09 (F0/F2: elapsed/moving и хвостовой км закрыты); остались лаг rolling pace ~23 c, клампы графика, хардкод 5.0 в interpolate_paces, окна по точкам, мёртвый EWMA-код |
| 285 | [Data] | **Парсер FIT v2 (F1)** — эмпирика 01.09.2026 (40 raw): парсер берёт 7 полей из 18 каналов record и игнорирует ВСЕ 328 lap-сообщений, timer-события и 26 из 27 полей session. COROS PACE 4 отдаёт power/stance_time/vertical_oscillation/step_length (покрытие 99.7–99.9%) — допущение METRICS_GUIDE §10 «часы не отдают» было ложным (исправлено). Извлекать: лапы → `laps_json` (ручные лапы = ground truth интервалов для F3/HRR), timer-паузы, session-эталоны → `device_summary`, каналы динамики → опциональные ключи трекпоинтов. Additive-миграция §5/§7 + db-safety-reviewer; история перечитывается reanalyze. Аналитика по мощности — сознательно отложена (§10). | `src/parsers/fit_parser.py`, `src/domain/models/training.py`, DEV_PLAN §9 F1 | ✅ 01.09.2026 (F1: extract_fit_activity, миграция u4v5w6x7y8z9) |
| 286 | [Coach] | **Moving-time (F2)** — паузы из timer-событий FIT (fallback — gap-эвристика), `avg_pace` от moving-времени, кросс-чек с session-эталоном часов (>5% → флаг качества). Закрывает elapsed/moving-несогласованность из аудита (#284) честно, данными вместо эвристик. Зависит от #285. | `src/analysis/`, DEV_PLAN §9 F2 | 🟡 01.09.2026: кросс-чек с эталоном часов ✅ (device_mismatch→suspect_data); avg_pace от timer-пауз — не внедрён (паузы <30 c проскакивают, точные паузы лежат в device_summary.pauses) |
| 287 | [Coach] | **M4 — недельная структура и мониторинг по литературе (F5/F6)** — METRICS_GUIDE §11: ≤3 качественных/нед + лёгкие дни между ними + восстановление после гонки 1 день/3 км (`hard_days_too_close`, `post_race_recovery_violated`); downhill-нагрузка на колено (`downhill_load_high` → P1); детренированность после пауз ≥5 дней (VDOT-декай, `detraining_expected`); session-RPE (RPE×мин) + сводный индекс самооценки из уже собираемого (новых вопросов пользователю НЕ добавлять). Все флаги — через §6/§7 (safety, не проза). | `docs/coach/METRICS_GUIDE.md` §11, `src/analysis/week_structure.py`, `src/coach/rules/p1_safety.py` | ✅ 01.09.2026 (F5/F6: week_structure.py, downhill_block, session_rpe, wellness_trend, p1 правила 12–14; insights v7) |
| 288 | [Чистка] | **Minors db-safety-ревью F0–F2 (01.09.2026)**: (а) кэш-путь reanalyze считает avg_pace полным временем (не знает выброшенных дельт) — legacy-сессии без сырья сохранят чуть «медленный» темп; (б) `_lap_row` отбрасывает лапы без distance/timer (только elapsed) — перед F3 проверить на реальном интервальном FIT, не теряются ли паузо-круги 0 м; (в) `zone_distribution`/`history_tools` читают time_in_zones из computed_json без проверки schema_version (v4-строки до lazy-пересчёта — устаревшие числа, не потеря); (г) рост trackpoints_json на +5 ключей/точку (~300–500 КБ на длинную) — наблюдать за бэкапами. | `src/services/reanalyze.py`, `src/parsers/fit_parser.py` | ⬜ низкий; п.(б) снят F3 — лапы проверены на №42 (16 лапов) и 10×1000 |
| 289 | [Coach] | **Дозамкнуть §7-хвосты METRICS_GUIDE на safety** — флаги считаются, но ограничений не дают: `easy_run_too_hard` ×2/7дн → сигнал в `evaluate_safety`; `quality_volume_exceeded`/`long_run_share_high` → вход skill `load`; `downhill_load_high` → P1-сигнал (колено); `detraining_expected` → поправка ожиданий `hr_vs_baseline` + потолок объёма первой трети возврата (⅓ пика); туда же #254 (недосып→осторожнее — те же рельсы signals→p1). | `src/coach/state.py`, `src/coach/rules/p1_safety.py`, `src/coach/skills/load.py` | ⬜ |
| 290 | [Analysis] | **Классификатор ставит `tempo` лёгким пробежкам у границы Z2/Z3**: 31.08 (avg HR 137, 38 мин) и 01.09 (avg HR 140, 46 мин, план — лёгкий со страйдами) при потолке Z2 = 138 → LLM в чате 02.09 пересказал «два насыщенных дня подряд (вторник-темповый и понедельничный)». Смотреть гейт `is_quality_session`/порог классификатора относительно LTHR, страйды не должны тянуть тип. | `src/analysis/`, `src/services/insights_baseline.py` | ⬜ |
| 291 | [Coach] | **LLM обращается в женском роде** («доберёшься сама», coach_messages id 125, 02.09): в `turn_context.profile` нет имени/пола подопечного. Добавить поле профиля (имя/обращение) или правило промпта. | `src/coach/turn_context.py`, `src/coach/llm/prompts.py` | ⬜ |
| 292 | [Coach] | **`confirm_or_adjust_morning` подтверждает не ту строку**: утро 02.09 пометило `confirmed` строку `planned` id 31 (tempo), хотя план дня накануне заменён строкой `proposed` id 34 (easy) — `PLAN_STATUSES` исключает `proposed`, а `unchanged_today` сравнивает с любой последней строкой даты. План-vs-факт недели (`week_plan_review`) увидит «темповую выполнена». Решить: включать `proposed` на ту же дату в выбор plan_row или помечать вытесненные строки. | `src/coach/planning.py` | ⬜ |
| 293 | [Coach] | **`/plan` среди недели — семантика «остаток недели» не определена**: `week_targets.week_start` = текущий понедельник, а `for_days_ahead` 1..7 от сегодня уезжают в следующую неделю; заголовок карточки/`target_km`/потолки считаются на всю неделю без вычета уже пробеганных дней; строки-«хвосты» всплывают на следующей неделе без меты (`week_view` их не показывает до понедельника). Решить: клиппинг до воскресенья + вычет факта, либо честный «план на 7 дней вперёд». | `src/coach/planning.py`, `src/coach/weekly_plan.py`, `src/coach/render.py` | ✅ 02.09.2026 — «остаток текущей недели» (`planning_window.py`, `remaining_*`, день 0 → adjusted, карточка с фактом прошедших дней) |
| 294 | [Coach] | **Окно доступности не персистится**: «могу бегать пн–чт» живёт только в истории чата (8 ходов) — на следующем `/plan` модель его уже не увидит. Хранить в `UserModel.params_json.week_plan.availability` (merge-паттерн `advance_mesocycle`), отдавать в `week_targets`/PLAN_PROMPT, задавать из чата (`log_suggestion`-подобный тап) или командой. | `src/coach/planning.py`, `src/coach/llm/prompts.py` | ⬜ |
| 295 | [Coach] | **План хранит `max_zone`, а не уд/мин** — потолок пульса карточки считается при рендере из текущего якоря зон; смена якоря (max_hr → LTHR, F4 01.09) молча меняет числа будущих дней (Z2: 144 → 138), владелец читает это как «план изменили». Сегменты уже хранят `hr_ceiling`. Рассмотреть фиксацию `hr_ceiling` в `target_json` при `finalize` + правило обновления (утреннее подтверждение re-clamp'ит) и явную пометку «зоны пересчитаны от ПАНО». | `src/coach/prescriber.py`, `src/coach/render.py` | ⬜ |

## 🟡 Исследование «пульс ↔ рельеф/температура» (02.09.2026, 39 тренировок прода)
Вывод: GAP снимает основную часть эффекта уклона (R² 0.54→0.74), остаток ~0.8 уд/мин на 1 %;
тягуны на маршрутах (2–3.5 %, 150–350 м) дают +2–3 уд/мин — детектор подъёмов не окупится.
Сделано: температурная поправка ожидания `hr_vs_baseline` + фраза в REVIEW_PROMPT. Хвосты:
- **#294 Спуски у Minetti «слишком лёгкие».** Остаточный эффект уклона поверх GAP положительный —
  как у Strava (HR-модель 2017: минимум фактора 0.88 при −9 %, у Minetti 0.5 при −18 %; при −3 %
  Minetti 0.85 vs ~0.95). Рассмотреть нижнее ограничение `gap_factor` (~0.9 на −3…−10 %); трогает
  GAP, дрейф, базовую линию → пересчёт insights, отдельная задача.
- **#295 Температура датчика часов как второй источник.** `device_summary.avg_temperature_c`
  (FIT session) объясняет пульс лучше Open-Meteo (R² 0.37 vs 0.24; +0.9 уд/мин/°C, солнце/тень),
  но выше воздуха в среднем на 3.3 °C. Сейчас не читается никем. Кандидат на фолбэк/поправку.
- **#297 Аналитика пульса/темпа при отрицательных температурах — после 31.12.2026.**
  Пока ни одной пробежки в мороз нет (данные 13.05–02.09.2026, 10–30 °C), поэтому сдвиг
  `expected_hr_shift_bpm` зажат в 10–30 °C (`HEAT_SHIFT_TEMP_MIN/MAX_C`) и ниже +10 °C равен −2.
  Когда накопятся зимние тренировки (ориентир — 8–10 пробежек при ≤ 0 °C, в т.ч. −10…−20 °C),
  повторить исследование 02.09.2026 (`HR ~ GAP-скорость + время + уклон`, 30-с окна, лаг 30 с,
  HR на равном GAP-темпе vs температура) и решить: продлить линейную формулу вниз, задать
  отдельный наклон для мороза (одежда, снег, холодовой стресс могут поднимать пульс) или
  оставить кламп. Заодно сверить Open-Meteo с датчиком часов (#295) на морозе.
- **#296 Температура фиксируется на старте.** Для тренировок 60+ мин брать среднее по часовым
  значениям Open-Meteo за время бега (данные уже запрашиваются на весь день, `weather.py`).
