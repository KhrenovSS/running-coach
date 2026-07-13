# Changelog — AI Running Coach

All notable changes to this project are tracked here.

## [13.07.2026] — Новый алгоритм детекции интервалов (base_pace + pace_gap)

### Changed
- **`src/analysis/oscillation.py`** — полностью переписан алгоритм `detect_pace_oscillations()`:
  - Старый: пики/впадины относительно среднего (mean ± amplitude/2)
  - Новый: `base_pace = mean(paces)`, `threshold = base_pace - pace_gap`; темп < threshold → work-фаза
  - Удалены `_find_peaks()` и `_find_troughs()` — больше не нужны
  - Work-фаза = любой участок где темп ≥ pace_gap быстрее среднего темпа пробежки
  - Recovery = темп вернулся к среднему (включая разминку/заминку)
- **`src/config/constants.py`** — `DEFAULT_OSCILLATION_AMPLITUDE` → `DEFAULT_PACE_THRESHOLD = 1.0` (мин/км), `DEFAULT_MIN_PHASE_DURATION_SEC` → 15 (сек)
- **`src/models.py`** — User: `interval_oscillation_amplitude` → `interval_pace_threshold` (Float)
- **`src/analysis/__init__.py`** — параметры: `interval_oscillation_amplitude` → `pace_gap`
- **`src/analysis/segment.py`** — `segment_by_pace()`: `min_amplitude` → `pace_gap`
- **`src/services/reanalyze.py`** — передаёт `pace_gap` вместо `amp`
- **`src/web/templates/settings.html`** — поле «порог ускорения»: ввод в секундах (60=1:00, 90=1:30, 120=2:00), min=30, max=180
- **`src/web/routes/pages/settings.py`** — GET: конвертация min→sec для шаблона; POST: sec→min перед сохранением

### Added
- **Alembic миграция `e5f6a7b8c9d0`** — rename `interval_oscillation_amplitude` → `interval_pace_threshold`, обновление данных (0.3→1.0, 10→15)

### Verified
- Все импорты в Docker OK
- Alembic миграция `e5f6a7b8c9d0` применена успешно
- Тест на синтетических данных: 3 work→recovery цикла корректно определены
- App запускается без ошибок

## [13.07.2026] — Модуль анализа: осцилляции темпа, интервал-детекция, reanalyze

### Added
- **`src/analysis/`** — новый пакет анализа тренировок (6 файлов):
  - `__init__.py` — оркестратор `process_trackpoints()` с пайплайном: GPS → кумулятивная дистанция → HR зоны → сегментация → классификация → осцилляции → погода
  - `oscillation.py` — детекция work→recovery циклов по базовому темпу (base_pace = средний темп пробежки) и HR-lag корреляция
  - `classify.py` — классификация с поддержкой `oscillation_count` + `hr_correlated` для интервалов
  - `segment.py` — сегментация по темпу с fallback на осцилляции
  - `hr_zones.py` — пульсовые зоны (перенесено из parsers/)
  - `utils.py` — утилиты: `format_pace`, `format_duration`, `haversine_m`, `calc_elevation`, `find_timezone` (перенесено из parsers/)
- **`src/services/reanalyze.py`** — сервис пересчёта тренировок из сохранённых трекпоинтов с поддержкой override типа
- **Alembic миграция `d1e2f3a4b5c6`** — 6 новых колонок:
  - `training_sessions.training_type_override` (VARCHAR 50, nullable) — ручная установка типа
  - `training_sessions.trackpoints_json` (JSON, nullable) — сырые трекпоинты для пересчёта
  - `users.interval_oscillation_amplitude` (FLOAT, nullable)
  - `users.interval_min_phase_duration` (INTEGER, nullable)
  - `users.interval_hr_lag_sec` (INTEGER, nullable)
  - `users.interval_min_oscillations` (INTEGER, nullable)
- **Эндпоинт `POST /session/{id}/reanalyze`** — пересчёт тренировки с возможностью смены типа
- **Dropdown типа тренировки** в `session.html` — выбор интервальная/темповая/long/recovery + кнопка «Пересчитать»
- **Настройки интервалов** в `settings.html` — амплитуда осцилляций, мин. длительность фазы, лаг пульса, мин. число осцилляций
- **`trackpoints_json`** сохраняется при загрузке TCX/FIT и синхронизации с часов

### Changed
- **`src/parsers/`** — удалены `common.py`, `segmentation.py`, `classification.py`, `hr_zones.py`, `utils.py`; логика вынесена в `src/analysis/`
- **`src/parsers/__init__.py`** — очищен от циклического импорта `src.analysis`
- **`src/parsers/tcx_parser.py`** — импорт `process_trackpoints` из `src.analysis`
- **`src/parsers/fit_parser.py`** — импорт `process_trackpoints` из `src.analysis`
- **`src/web/routes/uploads.py`** — сохранение `trackpoints_json` при загрузке (upload + confirm + deleted)
- **`src/services/sync_service.py`** — `trackpoints_json` проходит через `TrainingSession(**data)`
- **`src/web/routes/pages/session.py`** — добавлен `POST /session/{id}/reanalyze` эндпоинт
- **`src/web/routes/pages/settings.py`** — GET/POST handler: новые поля interval threshold
- **`src/models.py`** — `TrainingSession`: `training_type_override`, `trackpoints_json`; `User`: 4 interval threshold поля
- **`src/config/constants.py`** — 4 константы: `DEFAULT_PACE_THRESHOLD`, `DEFAULT_MIN_PHASE_DURATION_SEC`, `DEFAULT_HR_LAG_SEC`, `DEFAULT_MIN_OSCILLATIONS`

### Verified
- Все импорты в Docker: analysis, tcx, fit, reanalyze, session_reanalyze — OK
- Alembic миграция `d1e2f3a4b5c6` применена успешно
- Колонки `trackpoints_json`, `training_type_override` в `training_sessions` — OK
- App запускается без ошибок, health sync работает

## [13.07.2026] — Фаза D: документация

### Added
- **`BACKLOG.md`** — парковка TODO/идей/вопросов с тегами `[Идея]` `[Фикс]` `[Вопрос]`. 16 пунктов: FIXME из кода + пункты из аудита.
- **`docs/CHECKLIST_NEW_PROVIDER.md`** — пошаговый чеклист добавления нового бренда часов: клиент (ABC), регистрация в `factory.py`, конфигурация, исключения, smoke-тест, интеграция.

### Changed
- **`AGENTS.md`**: добавлен раздел «Дисциплина работы ИИ-агента» (6 пунктов):
  1. Потолок ~400 строк/файл (обоснование AI-поведения)
  2. Backlog-дисциплина (заметил мелочь → BACKLOG.md)
  3. Секреты (нет ключа → остановись и спроси)
  4. Проверка спринта — behavioral test, не `py_compile`
  5. Таблица Docker rebuild (что изменено → что пересобрать)
  6. Протокол конца сессии (commit → чекбоксы → отчёт)
- **`AGENTS.md`**: обновлена структура файлов (pages/ пакет, watch_credentials.py, training_service.py, async_utils.py)
- **`AGENTS.md`**: добавлена ссылка на `docs/CHECKLIST_NEW_PROVIDER.md` в таблицу документации
- **`PROJECT_AUDIT.md`**: AUDIT-011 → ✅ (выполнено в Фазе A), Sprint 9 reopen (AUDIT-015), спринты 13-15/7/аналитика заморожены
- **`README.md`**: обновлено дерево файлов (pages/ пакет, watch_credentials.py, training_service.py, async_utils.py, CHECKLIST_NEW_PROVIDER.md)
- **`README.md`**: мульти-бренд в секциях «Настройки», «Интеграция с часами», «Telegram-бот»
- **`README.md`**: убрана секция «Технический долг» → ссылка на `PROJECT_AUDIT.md`
- **`README.md`**: обновлена секция Roadmap (product features, без дублирования спринт-плана)
- **`README.md`**: обновлена дата

## [13.07.2026] — Фаза C: cleanup и унификация

### Changed
- **`src/parsers/weather.py`**: миграция с `requests` на `httpx` (sync API). `import requests` → `import httpx`; `requests.get(...)` → `httpx.get(...)`; `requests.exceptions.RequestException` → `httpx.HTTPError`.
- **`pyproject.toml`**: удалены мёртвые зависимости `"APScheduler==3.11.3"` и `"requests==2.34.2"` — планировщик свой (threading.Thread), HTTP-клиент — httpx.
- **`src/config/constants.py`**: удалены мёртвые функции `calculate_hr_zones()` и `get_hr_zone()` + 10 констант `Z*_PCT` (стр. 5-14). Единый источник HR-zone логики — `src/parsers/hr_zones.py`.
- **`src/exceptions.py`**: `CorosAPIError` → `WatchAPIError` (brand-agnostic, конструктор: message, brand, status, response_text). Добавлен `WatchAuthError` (message, brand).
- **`src/watch/coros.py`**: удалены локальные `class CorosAPIError(Exception)` и `class CorosAuthError(Exception)`. Импорт `WatchAPIError, WatchAuthError` из `src.exceptions`. Все 12 `raise` обновлены с `brand="coros"`.
- **`src/config/settings.py`**: удалено мёртвое поле `db_path = "running_coach.db"` (SQLite удалён в Sprint 4.5).
- **`src/services/async_utils.py`** (новый файл): `run_async_in_thread(coro)` — единый helper для запуска корутин из синхронных потоков.
- **`src/services/sync_service.py`**: удалён локальный `_run_async()`. `asyncio.run(...)` в `auto_sync_health()` и `auto_sync_activities()` заменён на `run_async_in_thread(...)`. Убраны `import asyncio` изнутри функций.
- **`src/telegram/sync_runner.py`**: удалён локальный `_run_async()`. Заменён на импорт `run_async_in_thread` из `async_utils`. Убран `import asyncio`.
- **`src/models.py`**: SQLite-ветка `get_engine()` помечена bilingual-комментарием "test-only".

### Verified
- `grep -rn "import requests" src/` → 0
- `grep -rn "APScheduler\|apscheduler" src/` → 0
- `grep -rn "CorosAPIError\|CorosAuthError" src/` → 0
- `grep -rn "calculate_hr_zones\|get_hr_zone" src/` → 0
- `grep -rn "db_path" src/` → 0
- `grep -rn "asyncio.run(" src/services/` → 0
- `grep -rn "Z1_MIN_PCT" src/` → 0
- Все изменённые файлы проходят `py_compile`

### Notes
- **Docker**: пересобрать `app` и `bot` (изменились weather.py, exceptions.py, coros.py, sync_service.py, sync_runner.py, pyproject.toml).
- **AUDIT-008**: паттерн async-from-thread унифицирован — один helper `run_async_in_thread` в `async_utils.py`.
- **AUDIT-011**: COROS_SYNC_* константы уже были удалены в Фазе A (audit.py).

---

## [13.07.2026] — Фаза B: тонкие роуты, мульти-бренд settings, единый sync entry point

### Added
- **`src/services/watch_credentials.py`** — `upsert_watch_credential(db, user_id, brand, email, password, activity_sync_interval, health_sync_interval)`: инкапсулирует шифрование пароля и логику upsert/удаления WatchCredential.
- **`src/services/training_service.py`** — `delete_training(db, user_id, session_id)` и `upsert_feedback(db, user_id, session_id, rating)`: бизнес-логика удаления тренировок и оценки, вынесенная из роутов.
- **`src/web/routes/pages/`** — пакет (замена монолитного `pages.py`):
  - `__init__.py` — сборка `router` через `include_router`
  - `auth.py` (48 строк) — `/login`, `/register`
  - `index.py` (184) — `render_page` + `/`
  - `session.py` (177) — `/session/{id}`, `/session/{id}/delete`, `/session/{id}/feedback` (тонкие роуты → `training_service`)
  - `settings.py` (118) — `/settings` GET+POST (через `upsert_watch_credential`)
- **`sync_service.run_sync_for_user(user_id, brand, sync_type, progress, pending)`** — единая точка входа для web-синхронизации (AUDIT-006).

### Changed
- **`src/web/routes/sync.py`** (444 → 93 строки): роуты делегируют в `run_sync_for_user`. Передаёт `pending=_pending` для activity-синхронизации (AUDIT-009).
- **`src/web/routes/pages/settings.py`**: хардкод `coros_email`/`coros_password` → `watch_brand`/`watch_email`/`watch_password`; перебор всех активных кредов пользователя (B.1).
- **`src/web/templates/settings.html`**: `{% for cred in watch_creds %}` — мульти-бренд форма.
- **`sync_activities_for_user`**: добавлен параметр `pending`; удалённые тренировки парсятся (FIT) и кэшируются в `pending` для `confirm_deleted`; общий хелпер `_download_parse` — устраняет дублирование download+parse.

### Fixed
- **NameError в `settings_save`**: `encrypt()` вызывался без импорта (после рефакторинга) → заменён на `upsert_watch_credential`.
- **Регрессия pending-deleted**: web-sync не кэшировал удалённые тренировки в `_pending` → переимпорт. Теперь `sync.py` передаёт `pending=_pending`.
- **`confirm_deleted`**: `Path('').unlink()` падал с `IsADirectoryError` → guard на пустой `path`.

### Verified
- `python -c "from src.web.routes.pages import router"` — OK
- `python -c "from src.startup import create_app"` — OK
- `grep -rn "encrypt(" src/web/routes/` → 0
- `grep -rn "WatchCredential(" src/web/routes/` → 0
- `grep -rn "DeletedTraining(" src/web/routes/` → 0
- `wc -l src/web/routes/sync.py` = 93 < 200
- `wc -l src/web/routes/pages/*.py` max 184 < 250

### Notes
- **AUDIT-006 Telegram TODO**: `sync_runner.py` вызывает `sync_activities_for_user`/`sync_health_for_user` напрямую, а не `run_sync_for_user` (обоснованно: все бренды + сводный отчёт). Миграция на `run_sync_for_user_all_brands(chat_id)` — отдельная задача (TODO в коде).
- **Docker**: после применения — пересобрать `app` и `bot`.

## [03.07.2026] — Сегментация: fix change-point detection + Docker rebuild + tcx_parser import

### Changed
- **`src/parsers/segmentation.py`**: исправлен алгоритм change-point detection:
  - Улучшена фильтрация шума в `_find_change_points()` — peak detection требует `>= prev` + `> next` (а не строгое `>`), чтобы находить границы на плато diff-сигнала
  - `_compute_per_point_pace()` — rolling window 50м для сглаженного темпа, consecutive deltas для статистики сегментов
  - `_merge_short_segments()` — удаление границ, создающих сегменты < 200м
  - `_km_segment_fallback()` — если change-point detection не дал результатов (запасной km-алгоритм)
  - `_compute_km_variability()` — старый km-алгоритм сохранён для `var_count` (классификация)
- **`src/parsers/tcx_parser.py`**: `weather_icon` импортировался из `common.py` (где был удалён). Фикс: `from .weather import weather_icon`
- **`src/parsers/common.py`**: вызов `segment_by_km()` → `segment_by_pace()`

### Fixed
- **Docker**: app-контейнер не перезапускался после сборки — `./bin/docker.sh build app` создавал новый образ, но `docker compose up -d` не вызывался. Контейнер 43 секунды работал на старом образе. Исправлено: принудительный `recreate` через `docker compose up -d`.
- **ImportError app crash**: после рестарта app падал с `ImportError: cannot import name 'weather_icon' from 'src.parsers.common'` — исправлен импорт в tcx_parser.py, контейнер пересобран.

### Verified
- **Синтетический тест**: трек 1км@5:00 + 10×(200м@3:30 + 600м@5:30) + 1км@5:30 → **21 сегмент**, var_count=8, тип=interval
- **Контейнер**: `docker exec` подтверждает новые файлы `segmentation.py`, `gps.py`, `weather.py`, `hr_zones.py`, `classification.py`, `utils.py`
- **App стартует**: `docker logs` — сервер запущен, миграции ok

### Todo (следующая сессия)
- **Применить к реальной тренировке (session id=67)**: старая сегментация (5 сегментов) не обновится автоматически — нужно удалить сессию из БД и перезагрузить TCX через веб
- **Sprint 10**: тесты (минимум 20) с реальными TCX/FIT-файлами
- **Sprint 11**: разбивка models.py + sync_service.py на пакеты
- **Sprint 12**: чистка роутов (sync.py, pages.py)
- **Sprint 13-15**: Фазы 3-5 (новая функциональность)

## [03.07.2026] — Sprint 9: Telegram-bot разбит на пакет src/telegram/

### Changed
- **`src/telegram_bot.py`** (1142 строк) удалён, разбит на пакет `src/telegram/` (12 файлов):
  - `main.py` — `run_bot`, Application сборка
  - `config.py` — константы состояний (EMAIL, PASSWORD, NEW_PASSWORD)
  - `state.py` — `_awaiting_weight`
  - `utils.py` — `get_user()`, `_get_web_app_url()`
  - `sync_runner.py` — `run_sync_in_thread()` (выделен из inline-кода)
  - `handlers/start.py` — регистрация, диалоги
  - `handlers/sync.py` — /sync
  - `handlers/stats.py` — /stats, StatsPages, stats_callback
  - `handlers/trainings.py` — /trainings, trainings_callback
  - `handlers/weight.py` — /weight, handle_weight_message
  - `handlers/account.py` — /delete_me, /login_info, /reset_password
  - `handlers/feedback.py` — feedback_callback
  - `jobs/weight.py` — daily_weight_job
  - `jobs/recovery.py` — daily_recovery_check_job
- **`run_telegram_bot.py`**: импорт изменён с `src.telegram_bot` на `src.telegram`

## [03.07.2026] — Sprint 8: Парсеры разбиты, logger shim удалён

### Changed
- **`src/parsers/common.py`** (690→241 строки): разбит на 6 модулей:
  - `gps.py` — `haversine_m()`, `clean_trackpoints()`
  - `weather.py` — `WMO_ICONS`, `fetch_weather()`, `get_weather_code_at_time()`, `get_temp_at_time()`, `weather_icon()`
  - `hr_zones.py` — `get_zone()`, `get_band()`
  - `segmentation.py` — `build_time_in_zones()`, `segment_by_km()`
  - `classification.py` — `classify_training()`
  - `utils.py` — `format_pace()`, `format_duration()`, `calc_elevation()`, `find_timezone()`
- **`src/logger.py`** удалён; 11 файлов переведены на `from src.utils.logger import get_logger`
- **`src/parsers/__init__.py`** реэкспортирует `process_trackpoints()` для обратной совместимости
- Обновлены импорты в `pages.py`, `uploads.py`, `sync.py`

## [03.07.2026] — План: Фаза 5 — факторы самочувствия после тренировки

### Added (plan)
- **Фаза 5** зафиксирована в `AGENTS.md` и `README.md`: после оценки тяжести (0–10) добавить multi-select факторов (ноги, дыхание, пульс, жара, недосып, стресс, другое) с адаптивными подсказками и хранением для аналитики. Полный детальный план реализации — в `AGENTS.md` → раздел «Фаза 5».

## [03.07.2026] — Оценка тренировки через веб-форму (session detail page)

### Added
- **`src/web/routes/pages.py`**: новый endpoint `POST /session/{session_id}/feedback` — Upsert оценки (0–10) с аудитом.
- **`src/web/templates/session.html`**: безусловный блок оценки в карточке + форма `<select>` для создания/изменения оценки.

### Changed
- **`src/web/routes/pages.py`**: `session_detail()` теперь передаёт `rating` (int или None) и `session_id` в шаблон.
- **AGENTS.md** — обновлён статус.

## [03.07.2026] — Sprint 6: Per-user sync intervals (brand-agnostic)

### Added
- **Sprint 6.3** `src/config/constants.py` — константы: `MIN_ACTIVITY_SYNC_INTERVAL_MIN (15)`, `MIN_HEALTH_SYNC_INTERVAL_MIN (30)`, `MAX_SYNC_INTERVAL_MIN (1440)`, `DEFAULT_ACTIVITY_SYNC_INTERVAL_MIN (60)`, `DEFAULT_HEALTH_SYNC_INTERVAL_MIN (480)`.
- **Sprint 6.4** `src/services/sync_service.py` — per-user интервалы: `get_activity_interval_seconds()`, `get_health_interval_seconds()`, `_is_sync_due()`.
- **Sprint 6.4** `src/scheduler.py` — tick-based планировщик (`SYNC_TICK_INTERVAL = 300`), каждая функция сама решает, какие credentials готовы.
- **Sprint 6.5–6.6** `src/web/routes/pages.py` + `src/web/templates/settings.html` — UI-поля `coros_activity_sync_interval` / `coros_health_sync_interval` с клипингом min/max.
- **Sprint 6.7** `src/web/routes/pages.py` + `src/web/templates/index.html` — баннер для новых пользователей (есть WatchCredential, но 0 тренировок).
- **Sprint 6.9** `src/telegram_bot.py` — обновлено сообщение после сохранения: «Бренд Coros подключён! Открой веб-интерфейс и нажми «Синхронизация».

### Changed
- **`src/services/sync_service.py`** — `auto_sync_health()` и `auto_sync_activities()` фильтруют credentials по per-user интервалам, а не по глобальным.
- **`src/scheduler.py`** — убран импорт `os.getenv("COROS_HEALTH_SYNC_INTERVAL")` и `os.getenv("COROS_ACTIVITY_SYNC_INTERVAL")`.
- **`src/web/routes/settings.py`** — сохранение настроек теперь включает `activity_sync_interval` / `health_sync_interval` в аудит-лог.
- **TECH_DEBT.md** — Sprint 6 помечен как выполненный.
- **AGENTS.md** — обновлён план работ (Sprint 6 ✅).

## [03.07.2026] — Фаза 3Б: inline-клавиатура оценки 0-10 + отображение в веб

### Added
- **Фаза 3Б.1** `src/services/sync_service.py` — per-training уведомления: каждая новая тренировка при автосинке отправляется отдельным сообщением с inline_keyboard `0–10` (триггер: инлайн-клавиатура 0-10 для оценки тяжести).
- **Фаза 3Б.2** `src/web/routes/uploads.py` — три вызова `telegram_notify()` (upload, confirm, confirm_deleted) дополнены `reply_markup` с inline-клавиатурой.
- **Фаза 3Б.3** `src/web/routes/pages.py` — `render_page()` загружает `TrainingFeedback` для всех тренировок на странице; `session_detail()` читает оценку и передаёт `rating_display` в шаблон.
- **Фаза 3Б.4** `src/web/templates/session.html` — блок `⭐ Оценка: X/10` на странице детального просмотра.
- **Фаза 3Б.5** `src/web/templates/index.html` — колонка `Оценка` в таблице тренировок на главной.

### Changed
- **TECH_DEBT.md** — Фаза 3Б перенесена перед Sprint 6, помечена как выполненная.
- **AGENTS.md** — обновлён план работ (Фаза 3Б ✅, Sprint 6 следующий).

## [02.07.2026] — Исправлен баг save_dashboard_data + уведомления Telegram при веб-загрузке

### Fixed
- **`src/services/sync_service.py:51`**: `save_dashboard_data()` вызывала async `client.get_dashboard()` без `await` → `'coroutine' object has no attribute 'get'`. Данные восстановления (recovery%, HRV, RHR) никогда не сохранялись. Функция сделана `async`, добавлен `await`.

### Added
- **`src/web/routes/uploads.py`**: при загрузке TCX/FIT через веб теперь отправляется уведомление в Telegram с датой, дистанцией, типом тренировки и именем файла. Также добавлены уведомления для `/upload/confirm` и `/upload/confirm_deleted`.
- **`src/telegram_bot.py`**: в карточку новой тренировки добавлены дата и время тренировки (`▫️ 02.07.2026 в 09:00`).
- **`src/services/sync_service.py`**: в уведомление автосинка добавлена метка времени синхронизации.
- **TECH_DEBT.md**: добавлен 🔴 16 (баг save_dashboard_data) и Фаза 3Б (inline-клавиатура оценки + отображение в веб).

### Infrastructure
- **Убиты старые процессы**: 2 локальных uvicorn (порты 8005, 8006) на старом монолитном `main.py` остановлены.
- **Docker**: пересобраны и перезапущены `app` и `bot`. Текущие контейнеры: `app` (uvecorn, порт 8000), `bot` (polling), `db` (postgres:16-alpine, healthy).

---

### Fixed
- **`src/services/sync_service.py`**: при автосинхронизации тренировок не отправлялось уведомление в Telegram. Добавлен вызов `telegram_notify()` после успешной синхронизации новых активностей.

## [02.07.2026] — Добавлено подробное логирование синхронизации + исправлен баг NameError в settings

### Added
- **`src/services/sync_service.py`**: подробное логирование каждого шага синхронизации:
  - `auto_sync_health()` / `auto_sync_activities()` — логируется количество обработанных credentials, результат по каждому (synced/empty/failed), итоговый счётчик
  - `sync_health_for_user()` — логируется число записей от API, сколько добавлено/пропущено, заполнение аналитики
  - `sync_activities_for_user()` — логируется `last_activity_sync_at`, `since`, число активностей от API, сколько пропущено (уже существует/удалено), сколько синхронизировано
  - `_make_client()` — логируется ошибка аутентификации с указанием brand и user_id
  - При пустом списке `WatchCredential` — логируется что нет учётных данных

### Fixed
- **`src/web/routes/pages.py:7`**: `NameError: name 'WatchCredential' is not defined` при открытии `/settings`. Модель `WatchCredential` не была импортирована в глобальных импортах, хотя использовалась в `settings_page()`. Добавлена в `from src.models import ... WatchCredential`.

## [02.07.2026] — Добавлена Фаза 4 в план работ: выбор бренда часов при регистрации

### Added
- **TECH_DEBT.md, AGENTS.md, README.md**: добавлена «Фаза 4 — Выбор бренда часов при регистрации (Multi-brand onboarding)» в план работ. При `/start` спрашивать бренд, для не-Coros — заглушка «не реализовано».

---

## [02.07.2026] — Шаг 3: Sprint 4.5 Фаза 7 — проверка миграций, alembic downgrade/upgrade

### Fixed
- **`watch_credentials` / `source_brand`**: исправлено частичное применение миграции `b6c7d8e9f0a1` (таблица была создана, alembic_version не обновлён). Ручное восстановление: `UPDATE alembic_version`, добавлена колонка `source_brand` в `daily_metrics`.
- **Telegram-бот**: контейнер `bot` пересобран — использовал старый код с `users.coros_email`, который удалён миграцией. Бот падал при любом запросе. Теперь работает.

### Changed
- **Docker образ `app`**: пересобран, миграции включены. Контейнер перезапущен.
- **Docker образ `bot`**: пересобран под актуальный код.

### Infrastructure
- **Alembic downgrade/upgrade**: `downgrade -1` + `upgrade head` — чистый цикл без ошибок.
- **Health check**: `GET /health/` — `database.status=ok`, `migrations.status=ok`, `current_revision=c9d8e7f6a0b2`.
- **Все контейнеры Up** (db, app, bot).

---

## [02.07.2026] — Шаг 2: Уменьшен интервал автосинхронизации тренировок 60→30 мин

### Changed
- **`src/services/sync_service.py:27`**: `activity_sync_interval` по умолчанию — 1800с (30 мин) вместо 3600с (60 мин). Тренировки теперь синхронизируются в 2 раза чаще.

---

## [02.07.2026] — Шаг 1: Исправлен баг потери тренировок при задержке Coros API

### Fixed
- **`src/services/sync_service.py:212`**: добавлен lookback-буфер 2ч (`since = last_activity_sync_at - timedelta(hours=2)`) — активности, которые Coros обработал с задержкой, больше не теряются навсегда.
- **`src/telegram_bot.py:460`**: тот же фикс для синхронизации через Telegram-бота.

### Security
- **Health sync**: проверено — не подвержен багу (окно 120 дней, фильтр по дате).

---

## [02.07.2026] — Обнаружен критический баг: потеря тренировок при задержке Coros API

### Added
- **TECH_DEBT.md**: добавлен раздел «🐛 Критический баг — Потеря тренировок при задержке Coros API» с описанием, анализом, примером и планом исправления. Исправить перед Фаза 2.
- **AGENTS.md**: баг добавлен в «Известные проблемы» и «Следующие шаги» (п.2).

### Security
- **Анализ здоровья**: проверено, что health sync НЕ подвержен этому багу — использует окно 120 дней и фильтр по `entry_date in existing_dates`.

---

## [02.07.2026] — Актуализация AGENTS.md и README.md для следующей сессии

### Changed
- **AGENTS.md**: удалены устаревшие почасовые записи (20-25.06.2026 — перенесены в CHANGELOG.md). Исправлена нумерация в «Что сделано за сессию». Из «Известные проблемы» убрано «Docker требует sudo» (решено bin/docker.sh). «Следующие шаги» — Фаза 1 помечена выполненной. Сокращён объём для минимизации токенов при старте новой сессии.
- **README.md**: структура проекта приведена к актуальной (добавлены `bin/`, `src/watch/`, `src/services/sync_service.py`; удалены `coros_client.py`, `coros_sync_auto.py`, `web/routes/coros.py`). Схема `users` — удалены `coros_email`, `coros_password`, `last_coros_sync`. Список миграций дополнен `b6c7d8e9f0a1` и `c9d8e7f6a0b2`. Roadmap — Фаза 1 помечена ✅. Техдолг — Coros-клиент помечен как решённый. `Очистка БД` — заменена на `./bin/docker.sh`.

---

## [02.07.2026] — Фаза 1: п.12+14.9 — удалены старые поля Coros из User, очищена документация

### Security
- **`.env`**: права доступа изменены на `600` (только владелец). Добавлен `SUDO_PASSWORD` для docker-команд. `.env` в `.gitignore` — не коммитится.
- **`bin/docker.sh`**: защищённый скрипт-обёртка для `docker compose` с `sudo`. Права `700`. Пароль читается из `.env`, не передаётся в аргументах и не сохраняется в истории. `bin/` добавлен в `.gitignore`.
- **AGENTS.md, README.md**: все `sudo docker compose ...` команды заменены на `./bin/docker.sh ...`

### Removed
- **`User.coros_email`, `User.coros_password`, `User.last_coros_sync`** — удалены из модели `User`. Все данные теперь хранятся только в `WatchCredential`.
- **Alembic migration** `c9d8e7f6a0b2` — DROP колонок `coros_email`, `coros_password`, `last_coros_sync` из `users`.
- **Устаревшие упоминания `coros_client.py`** удалены из `AGENTS.md`, `README.md`, `docs/ARCHITECTURE.md` (файл был удалён в Sprint 4).

### Changed
- **`src/telegram_bot.py`**: `start()` — email читается из `WatchCredential` вместо `user.coros_email`. `get_password()` — удалена запись в `user.coros_email`/`user.coros_password`. `cmd_sync()` — проверка `has_cred` через `WatchCredential`. `delete_me()` — удалена очистка `user.coros_email`/`coros_password` (WatchCredential уже удаляется).
- **`src/web/routes/pages.py`**: `settings_save()` — `old_coros_email` читается из `WatchCredential`, удалена запись в `user.coros_email`/`user.coros_password`.

### Tech Debt
- **TECH_DEBT.md**: п.12+14.9 помечен как выполненный. AGENTS.md: чекбоксы Фазы 1 обновлены.

---

## [02.07.2026] — Планирование дальнейших работ (Фазы 1–3 + модуль аналитики)

### Added
- **AGENTS.md**: обновлён раздел «Текущее состояние» — добавлен детальный план работ:
  - Фаза 1: остатки Sprint 4 (п.12+14.9 — удаление старых полей `User`) + Sprint 4.5 проверки
  - Фаза 2: Sprint 6 — per-user частота синхронизации (бренд-независимая), баннер новичкам
  - Фаза 3: фильтр по типу тренировки, общая дистанция/время за неделю/месяц
  - Затем: модуль аналитики (8 этапов из `decision_module_design.md`) и Sprint 7 (Admin panel)
- **TECH_DEBT.md**: добавлен раздел «Обновлённый план дальнейших работ» с детальными чекбоксами по фазам. Версия обновлена до 1.3.
- **TECH_DEBT.md**: Sprint 4.5 Фаза 7 — невыполненные пункты помечены с указанием фазы выполнения

### Changed
- **AGENTS.md**: секция «Следующие шаги» переписана в порядок выполнения по фазам
- **TECH_DEBT.md**: добавлен раздел «Обновлённый план дальнейших работ» (Фазы 1–3 → модуль аналитики → Sprint 7), невыполненные пункты Sprint 4.5 Фазы 7 помечены фазами
- **README.md**: Roadmap обновлён — добавлены Фазы 1–3 перед модулем аналитики

### Added
- **`src/watch/`** — новый пакет мульти-брендовой абстракции часов:
  - `base.py`: `BaseWatchClient(ABC)` с протоколом `authenticate`, `list_activities`, `download_activity`, `get_daily_metrics`, `get_dashboard`, `get_analytics`
  - `coros.py`: `CorosWatchClient(BaseWatchClient)` на `httpx.AsyncClient` вместо синхронного `requests`
  - `factory.py`: реестр брендов (`register`, `get_watch_client`, `list_brands`)
- **`WatchCredential`** — новая модель в `src/models.py` (таблица `watch_credentials`): `brand`, `encrypted_user`, `encrypted_password`, `access_token`, `token_expires_at`, `last_activity_sync_at`, `last_health_sync_at`, `activity_sync_interval`, `health_sync_interval`, `is_active`
- **`DailyMetrics.source_brand`** — колонка для указания источника метрик (e.g. 'coros')
- **`src/services/sync_service.py`** — brand-agnostic сервис синхронизации (заменяет `coros_sync_auto.py`): `sync_health_for_user`, `sync_activities_for_user`, `auto_sync_health`, `auto_sync_activities`
- **`src/web/routes/sync.py`** — brand-agnostic роуты: `POST /sync/{brand}/run`, `POST /sync/{brand}/health`, `GET /sync/status/{id}` + обратная совместимость `/coros/sync`
- **Alembic migration** `b6c7d8e9f0a1` — создание `watch_credentials`, добавление `source_brand` в `daily_metrics`, миграция существующих coros учётных данных
- **AuditService** — brand-agnostic методы: `log_sync_started(brand)`, `log_sync_completed(brand)`, `log_sync_failed(brand)`
- **CRED_KEY fallback** — `crypto.py` поддерживает `CRED_KEY` как основной и `COROS_CRED_KEY` как deprecated fallback с warning

### Changed
- **`src/web/routes/__init__.py`** — подключение `sync_router` вместо `coros_router`
- **`src/scheduler.py`** — brand-agnostic, импортирует из `sync_service` вместо `coros_sync_auto`
- **`src/web/routes/pages.py`** — чтение coros email из `WatchCredential` в настройках, сохранение и в `WatchCredential`
- **`src/telegram_bot.py`** — импорт `CorosWatchClient` вместо `CorosClient`, использование `asyncio.run()` для async-вызовов, сохранение кредов в `WatchCredential`

### Removed
- **`src/coros_client.py`** — старый синхронный CorosClient (весь функционал перенесён в `src/watch/coros.py`)
- **`src/services/coros_sync_auto.py`** — заменён на `src/services/sync_service.py`
- **`src/web/routes/coros.py`** — заменён на `src/web/routes/sync.py`

---

## [02.07.2026] — Hotfix: UnboundLocalError в pages.py (Python 3.13+)

### Fixed
- **`src/web/routes/pages.py`**: `UnboundLocalError: cannot access local variable 'timezone'` — внутренний `from datetime import datetime, timezone` (строка 119) затенял module-level `timezone` (строка 22). Python 3.13+ считает `timezone` локальной переменной с начала функции `render_page()`, но на строке 73 она ещё не инициализирована. Исправлено: убран `timezone` из внутреннего импорта, оставлен только `from datetime import datetime`.

## [02.07.2026] — Sprint 4.5 завершён: PostgreSQL-only + TIMESTAMPTZ

### Changed
- **Полный отказ от SQLite** для разработки/продакшена — `DATABASE_URL` обязателен, engine создаётся лениво
- **All 14 DateTime columns → TIMESTAMPTZ** (Alembic `5e287a9fc289`) — `AT TIME ZONE 'UTC'` для существующих данных
- **14 columns**: users (created_at, registered_at, last_coros_sync, last_health_sync_at), training_sessions (begin_ts), deleted_trainings (begin_ts, deleted_at), daily_metrics (synced_at), weight_measurements (measured_at), training_feedback (created_at), audit_events (created_at), auth_tokens (created_at, expires_at, used_at)
- **`utcnow()`** возвращает aware `datetime.now(timezone.utc)`
- **All `.replace(tzinfo=None)` removed** (grep → 0 matches) — 10 files: auth.py, audit.py, telegram_bot.py, pages.py, coros_sync_auto.py, tcx_parser.py, coros_client.py, common.py, deps.py
- **`local_dt()`** simplified: `dt.astimezone(tz)` with naive fallback
- **`common.py`**: `start_time_utc` normalized to aware UTC at function entry
- **Port 5432 exposed** on db container for local dev access
- **Lazy engine** in models.py: `get_engine()` / `SessionLocal` — engine created on first access

### Removed
- SQLite engine branch, WAL pragmas, `check_same_thread`, auto-fallback
- `_RENDER_AS_BATCH` from alembic/env.py
- `sqlalchemy.url` from alembic.ini
- All `render_as_batch` calls

### Verified
- `grep "replace(tzinfo=None)" src/` → 0 matches
- Docker 3/3 containers Up and healthy
- Audit events stored with `+00` timezone
- All training sessions preserved with correct UTC values
- Tests pass (3/3) with in-memory SQLite

## [02.07.2026] — Sprint 4, п.8: стандартизация времени (UTC)

### Added
- **User.timezone** — колонка `VARCHAR(50)`, IANA-таймзона пользователя (напр. "Europe/Moscow")
- **TrainingSession.timezone** — колонка с часовым поясом конкретной тренировки
- **`src/deps.py:local_dt()`** — хелпер для конвертации naive UTC → naive local time при отображении
- **Alembic migrations** — `3205fe660d47` (user.timezone), `4201426df9cc` (training_sessions.timezone), `a1b2c3d4e5f6` (data migration old begin_ts)

### Changed
- **Все `datetime.utcnow()` заменены** на `datetime.now(timezone.utc).replace(tzinfo=None)` — в auth.py, audit.py, telegram_bot.py, pages.py, tcx_parser.py, coros_sync_auto.py, coros_client.py
- **Все `datetime.now()` (наивные) заменены** — в coros_sync_auto.py, pages.py
- **`datetime.fromtimestamp(ts)` → `datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)`** — coros_client.py (исправлена ошибка с системным часовым поясом)
- **Парсер `common.py`**: `begin_ts` теперь сохраняется как naive UTC (вместо naive local). Время погоды вычисляется через `begin_local` (aware local time)
- **Парсер `common.py`**: возвращает `'timezone'` в словаре результата для сохранения в БД
- **Callers (uploads.py, coros.py, coros_sync_auto.py, telegram_bot.py)**: сохраняют `timezone` из результата парсера в `TrainingSession.timezone` и в `User.timezone`
- **Отображение дат** на index и session_detail страницах: конвертация UTC → local время через `ZoneInfo`

### Fixed
- **`coros_client.py`**: `datetime.fromtimestamp()` без timezone использовал системный часовой пояс вместо UTC

### Added (п.8.4)
- **Data migration** `a1b2c3d4e5f6`: конвертирует старые naive-local `begin_ts` → naive UTC (fallback Europe/Moscow), проставляет `timezone` в training_sessions и users
- **pyproject.toml**: добавлен `jinja2==3.1.5` в зависимости (требовался `Jinja2Templates` но не был явно указан)

## [02.07.2026] — Hotfix: daily weight reminder timezone (п.15)

### Fixed
- **daily weight reminder** — PTB `JobQueue` работал в UTC, `run_daily(hour=9)`
  срабатывал в 12:00 MSK вместо 9:00. Исправлено: `Defaults(tzinfo=ZoneInfo("Europe/Moscow"))`
  в `Application.builder()`.
- **catch-up query** — глобальная проверка веса без `user_id` заменена на безусловный
  `run_once` (т.к. `daily_weight_job` сам проверяет who has/hasn't weighed).
- **docker-compose.yml** — добавлен `TZ: Europe/Moscow` для сервисов `app` и `bot`.

### Changed
- **TECH_DEBT.md**: п.15 вынесен из Спринта 4 в отдельный «Шаг 0 — быстрые исправления»
  перед Спринтом 4.
- **TECH_DEBT.md**: п.12+14 объединены (Coros-клиент пишется на httpx сразу как
  `CorosWatchClient(BaseWatchClient)`, без промежуточного шага).
- **TECH_DEBT.md**: Спринт 7 помечен как отложенный.

## [02.07.2026] — Планирование мульти-брендовой архитектуры

### Added
- **TECH_DEBT.md**: Спринт 4 расширен — п.14 (мульти-брендовая архитектура) и п.15 (исправление daily weight reminder — часовой пояс бота)
- **TECH_DEBT.md**: добавлен детальный план Спринта 4 (п.8 время UTC, п.12 httpx Coros-клиент, п.14 мульти-бренд, п.15 weight reminder)
- **AGENTS.md**: золотое правило №10 — «Мульти-брендовость закладывать сразу»

### Changed
- **TECH_DEBT.md**: Спринт 6 переименован в «per-user частота синхронизации (бренд-независимая)» — учитывает мульти-брендовую архитектуру из Спринта 4
- **AGENTS.md**: обновлены «Следующие шаги» (Sprint 4 → мульти-бренд), структура файлов (добавлен `src/watch/`), «Текущее состояние» (пометки о грядущих изменениях в Спринте 4)
- **README.md**: Roadmap — Sprint 4 включает мульти-брендовую архитектуру

## [02.07.2026] — Sprint 3, шаг 6: финальная уборка, main.py 7 строк

### Changed
- **main.py**: 2776 → 7 строк (99.7% сокращение)
- **Sprint 3 завершён**: `main.py` декомпозирован на пакеты `src/services/`, `src/web/routes/`, `src/config/settings.py`, `src/scheduler.py`, `src/startup.py`
- **AGENTS.md**: обновлена секция «Текущее состояние»

## [02.07.2026] — Sprint 3, шаг 5: pydantic-settings вместо dataclass CONFIG

### Added
- **`src/config/settings.py`**: `Settings(BaseSettings)` — env-конфигурируемые настройки (auth, paths, hr zones, timing)
- **`pydantic-settings==2.14.2`** в `pyproject.toml`

### Changed
- **`src/config/__init__.py`**: экспортирует `settings` из `settings.py` + все константы из `constants.py`
- **`src/config/constants.py`**: dataclass `CONFIG` заменён на плоские module-level константы (HR зоны, API endpoints, пороги); утилиты `calculate_hr_zones()`, `get_hr_zone()` обновлены
- **5 файлов** обновлены: `from src.config import CONFIG` → `from src.config import settings`, `CONFIG.AUTH.PASSWORD_MIN_LENGTH` → `settings.password_min_length`, `CONFIG.AUTH.TOKEN_TTL_MINUTES` → `settings.token_ttl_minutes`, `CONFIG.LOG_FILE` → `settings.log_file`
- **`src/crypto.py`**: вместо автогенерации ключа — `RuntimeError` если `COROS_CRED_KEY` не задан

### Removed
- **Dataclass-иерархия CONFIG** (~160 строк) — заменена на `pydantic-settings` + плоские константы

## [02.07.2026] — Sprint 3, шаг 4: scheduler и startup выделены, main.py 7 строк

### Added
- **`src/scheduler.py`**: `AutoSyncScheduler` — класс-одиночка с фоновым циклом автосинхронизации (health + activity), jitter, graceful error handling
- **`src/startup.py`**: `create_app()` — фабрика приложения: middleware, роуты, startup-событие (init_db, alembic, весы, аудит, scheduler)

### Changed
- **main.py**: 118 → 7 строк (только `from src.startup import create_app` + `app = create_app()` + `if __name__ == "__main__"`)
- **startup-логика** перенесена из декоратора `@app.on_event("startup")` в `src.startup.on_startup()`

### Removed
- **~111 строк** из main.py (startup + _start_auto_sync + _AUTO_SYNC_LOCK)

## [02.07.2026] — Sprint 3, шаг 3: роуты вынесены в src/web/routes/

### Added
- **`src/web/state.py`**: глобальное состояние (`_pending`, `_sync_tasks`, `_sync_tasks_lock`, `_AUTO_SYNC_LOCK`, `TRAINING_TYPES_RU`, `PENDING_DIR`)
- **`src/deps.py`**: общие зависимости (`templates = Jinja2Templates(directory="src/web/templates")`)
- **`src/web/routes/__init__.py`**: сборка 4 sub-routers в `web_router`
- **`src/web/routes/pages.py`**: 7 роутов (login, register, index, session_detail, settings_page, session_delete, settings_save) + `render_page()` + `_AUTH_ERRORS`
- **`src/web/routes/uploads.py`**: 3 роута (upload_files, confirm_upload, confirm_deleted)
- **`src/web/routes/coros.py`**: 3 роута (coros_sync, coros_sync_status, coros_sync_health)
- **`src/web/routes/logs.py`**: 1 роут (view_logs)

### Changed
- **main.py**: все роуты удалены, заменены на `app.include_router(web_router)`. `templates` вынесен в `src.deps`. main.py: 1338 → 118 строк.
- **Импорты**: все роуты импортируют `templates` из `src.deps`, глобальное состояние из `src.web.state`

### Removed
- **~1220 строк** из main.py (13 декораторов роутов, render_page(), _AUTH_ERRORS, глобальные переменные)

## [02.07.2026] — Sprint 3, шаг 2: сервисы выделены в src/services/

### Added
- **`src/services/telegram_notify.py`**: `telegram_notify()` — отправка уведомлений через Telegram (выделена из main.py)
- **`src/services/stats.py`**: `fmt_duration()`, `calc_stats()`, `zone_ranges()`, `render_zone_bars()`, `render_type_row()`, `build_nav_html()`, `MONTHS_RU`, `MONTHS_RU_SHORT`, `ZONE_COLORS` — вспомогательные функции статистики и отображения
- **`src/services/recovery_view.py`**: `hrv_status()`, `tired_label()`, `readiness_label()`, `load_label()` — классификация метрик здоровья
- **`src/services/coros_sync_auto.py`**: `_auto_sync_status`, `_auto_sync_status_lock`, `health_sync_interval`, `activity_sync_interval`, `update_last_health_sync()`, `save_dashboard_data()`, `auto_sync_health()`, `auto_sync_health_inner()`, `auto_sync_activities()`, `auto_sync_activities_inner()` — фоновая автосинхронизация Coros

### Changed
- **main.py**: все выделенные функции и глобальные переменные заменены на импорты из `src.services.*`
- **Убраны префиксы `_`** у публичных функций: `_telegram_notify` → `telegram_notify`, `_hrv_status` → `hrv_status`, `_tired_label` → `tired_label`, `_readiness_label` → `readiness_label`, `_load_label` → `load_label`, `_update_last_health_sync` → `update_last_health_sync`, `_save_dashboard_data` → `save_dashboard_data`, `_auto_sync_health` → `auto_sync_health`, `_auto_sync_activities` → `auto_sync_activities`
- **Глобалы автосинхронизации**: `_HEALTH_SYNC_INTERVAL` → `health_sync_interval`, `_ACTIVITY_SYNC_INTERVAL` → `activity_sync_interval`, `_AUTO_SYNC_STATUS_LOCK` → `_auto_sync_status_lock`

### Removed
- **~670 строк** из main.py (было ~2010 → ~1340 строк) — 22 функции/переменные вынесены в сервисные модули

## [02.07.2026] — Sprint 3, шаг 1: Jinja2-шаблоны

### Added
- **`src/web/templates/`**: директория Jinja2-шаблонов (base.html, index.html, login.html, register.html, session.html, settings.html)
- **`templates = Jinja2Templates(directory)`**: инициализация Jinja2Templates в main.py
- **Chart.js**: CDN-скрипт в base.html (был дублирован в MAIN_HTML и SESSION_HTML)

### Changed
- **Главная страница `GET /`**: вместо `render_page()` → `MAIN_HTML.format()` использует `templates.TemplateResponse(request, "index.html", ctx)`
- **Страница тренировки `GET /session/{id}`**: вместо `SESSION_HTML.format()` использует `templates.TemplateResponse(request, "session.html", ...)`
- **Страница настроек `GET /settings`**: вместо `SETTINGS_PAGE.format()` использует `templates.TemplateResponse(request, "settings.html", ...)`
- **Страница входа `GET /login`**: вместо inline HTML-строки использует `templates.TemplateResponse(request, "login.html", ...)`
- **Страница регистрации `GET /register`**: вместо inline HTML-строки использует `templates.TemplateResponse(request, "register.html", ...)`

### Removed
- **`MAIN_HTML`**: inline-шаблон главной страницы (~520 строк) — заменён на `src/web/templates/index.html`
- **`SESSION_HTML`**: inline-шаблон страницы тренировки (~110 строк) — заменён на `src/web/templates/session.html`
- **`SETTINGS_PAGE`**: inline-шаблон страницы настроек (~55 строк) — заменён на `src/web/templates/settings.html`
- **Удалено ~700 строк** inline HTML из main.py (было 2776 → ~2010 строк)

### Fixed
- **`login_page`**: восстановлена строка `err_msg = _AUTH_ERRORS.get(error, "")` (случайно удалена при замене HTMLResponse)
- **`TemplateResponse` positional args**: исправлен вызов с `(name, context)` на `(request, name, context)` (Starlette API)

## [01.07.2026] (вечер)

### Added
- **Sprint 6 (план) в `TECH_DEBT.md`**: настраиваемая частота синхронизации Coros per-user (10 задач 6.1–6.10). Первая синхронизация — ручная, последующие — автоматические по индивидуальному интервалу. Мин. 15 мин (тренировки) / 30 мин (здоровье), по умолчанию 60 мин / 8 часов. Логирование новых vs. unchanged записей здоровья для оптимизации частоты.
- **Sprint 7 (план) в `TECH_DEBT.md`**: панель администрирования (10 задач 7.1–7.10). Дашборд, управление пользователями, просмотр аудита, принудительный sync. Использует существующие `AuditEvent`, `is_active`, `get_current_user`. Добавит `role` колонку и `get_admin_user` dependency. Дизайн: встроенная HTML-страница `/admin`, не отдельный фронтенд.
- **Пользователь зарегистрирован**: user id=1, email=khrenov.ss@gmail.com, Coros привязан. 0 тренировок (первая синхронизация — вручную через 🔄 Coros Sync).

### Changed
- **`TECH_DEBT.md`**: версия 1.2, добавлены детальные планы Sprint 6 и Sprint 7
- **`AGENTS.md`**: добавлен раздел «Администрирование» — указание учитывать будущую админку при проектировании кода (per-user isolation, AuditService, БД для глобального состояния)
- **`README.md`**: Roadmap обновлён — Sprint 7 добавлен, «7 спринтов»

## [01.07.2026]

### Added
- **PostgreSQL + Docker (3 контейнера)**:
  - `Dockerfile` — Python 3.13-slim, установка зависимостей, копирование кода
  - `docker-compose.yml` — 3 сервиса: `db` (postgres:16-alpine), `app` (uvicorn), `bot` (run_telegram_bot.py)
  - Healthcheck на db, `depends_on: condition: service_healthy`, `restart: on-failure`
  - Volumes: `pgdata` (named volume), `uploads/`, `logs/` (bind mounts)
  - `.dockerignore` — исключение `.venv/`, `__pycache__/`, `.git/`, `*.db*`, `logs/`, `uploads/`, `.env`
  - `psycopg2-binary==2.9.10` и `alembic==1.18.5` добавлены в `pyproject.toml`
  - `POSTGRES_PASSWORD` в `.env` / `.env.example`

### Changed
- **`src/models.py`**: engine database-agnostic — PostgreSQL (`pool_size=10, max_overflow=20`) или SQLite (`check_same_thread`, `PRAGMA WAL`) в зависимости от `DATABASE_URL`
- **`alembic/env.py`**: `DATABASE_URL` читается из env, `render_as_batch` только для SQLite
- **Alembic миграции**: 4 старых миграции заменены одним fresh baseline (`f75d2362cf9f`) — database-agnostic, без `AUTOINCREMENT`
- **`main.py`**: `PENDING_DIR` configurable через env (по умолчанию `/tmp/running_coach_uploads`)
- **`src/crypto.py`**: предупреждение если `COROS_CRED_KEY` не задан (важно для Docker)
- **`pyproject.toml`**: добавлен `version = "2.0.0"` (требуется для pip install в Docker)
- **Systemd-юниты удалены**: `running-coach.service` и `running-coach-bot.service` — теперь Docker управляет запуском

### Added (ранее в этот день)
- **Email+password аутентификация (полноценная)**:
  - Колонки `email` и `password_hash` в таблице `users` (миграция `eb448386be71`)
  - `bcrypt` для хеширования паролей (`hash_password()`, `verify_password()`, `authenticate_user()` в `src/services/auth.py`)
  - Страница `/login` — вход по email+паролю, HTML-форма
  - Страница `/register` — регистрация по одноразовому токену из Telegram (/start), установка email+пароля
  - POST `/auth/login` и POST `/auth/register` — обработка форм
  - Команды Telegram-бота: `/login_info` (показать email), `/reset_password` (сменить пароль — бот показывает 2 сек и удаляет)
  - `AuthConfig` в `CONFIG`: `TOKEN_TTL_MINUTES=30`, `PASSWORD_MIN_LENGTH=6`, `SESSION_TTL_DAYS=7`
  - Неавторизованные пользователи автоматически перенаправляются на `/login` (303 redirect)
  - `http_exception_handler` в middleware теперь возвращает `RedirectResponse` для 3xx статус-кодов

### Changed
- **Telegram-бот вынесен в отдельный systemd-юнит** (`running-coach-bot.service`): больше не запускается как `subprocess.Popen` из `main.py`. Бот работает независимо, автоматически перезапускается при падении (`Restart=on-failure`). Убран `_start_telegram_bot()` из `main.py`.
- **Расписание опроса веса**: теперь в 9:00, 12:00, 15:00, 18:00 (вместо одного в 9:00). При старте бота после 9:00 — немедленное напоминание, если вес ещё не введён.
- **`_generate_login_link`**: если у пользователя нет `password_hash` — ссылка ведёт на `/register`, иначе на `/auth/telegram` (быстрый вход)
- **TTL токена**: 5 мин → 30 мин (из `CONFIG.AUTH.TOKEN_TTL_MINUTES`)
- **Logout**: теперь редиректит на `/login` вместо `/`

### Fixed
- **Ежедневный опрос веса не находил пользователя**: `is_active` в БД был `NULL` (None), а не `True`, из-за чего фильтр `is_active == True` исключал единственного пользователя.
- **`run_once` не срабатывал с числовым `when`**: переведён на `datetime.utcnow() + timedelta()`.
- **`last_coros_sync` оставался `NULL` когда все активности уже импортированы**: ранний `return` при `new_acts = []` никогда не обновлял `last_coros_sync`, поэтому каждый цикл автосинхронизации запрашивал все активности с `since=None`. Исправлено: перед ранним возвратом `last_coros_sync` обновляется до последней активности из ответа API — и в автосинке, и в ручной синхронизации.
- **Telegram-бот не отвечал на `/start`**: stdout/stderr бота уходили в `/dev/null` через `subprocess.DEVNULL` — любые ошибки были невидимы. Исправлено: убраны `stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL`
- **Markdown в сообщении `/start` ломал парсер Telegram**: эмодзи `🔗` внутри `[text](url)` в legacy Markdown вызывал `BadRequest: Can't parse entities`. Переведено на plain text (Telegram сам делает URL кликабельными)
- **HTML parse_mode не работал**: `<a href="...">` c `parse_mode="HTML"` не отрисовывался как ссылка в Telegram (возможно, из-за `localhost` в URL). Заменено на plain text
- **AuditService.log_coros_sync_completed() TypeError**: сигнатура изменилась на `(user_id, found, processed)`, но вызовы в `main.py` и `telegram_bot.py` передавали только keyword-аргументы. Сделано `found=0, processed=0` для обратной совместимости, пока не будут передаваться реальные значения
- **`_send_message()` и `_telegram_notify()` падали на Markdown 400**: при ошибке парсинга Markdown сообщение не доставлялось. Добавлен fallback — повторная отправка без `parse_mode` при статусе 400

### Changed
- **`WEB_APP_URL`**: `http://localhost:8000` → `http://192.168.1.101:8000` для доступа с телефона и других устройств в локальной сети

## [30.06.2026]

### Added
- **Logging and audit system (Level 2 observability)**:
  - `src/utils/logger.py` — structured logging with daily rotation, JSON/text formats
  - `src/services/audit.py` — `AuditService` writing to DB (`audit_events`) and `logs/audit_*.log`
  - `src/api/middleware.py` — centralized error handlers + request logging with timing
  - `src/api/routes/health.py` — health check endpoint at `/health/`
  - `src/exceptions.py` — typed application exceptions (`AppError`, `NotFoundError`, `CorosAPIError`, etc.)
  - `src/config/constants.py` — centralized `CONFIG` for constants
  - Alembic migration `eb50c256201f_add_audit_events_table.py` creating `audit_events` table
- **Audit event coverage**:
  - `app.startup` logged on server startup
  - `training.uploaded` for TCX/FIT uploads, Coros activity sync, and re-import of deleted trainings
  - `training.deleted` when deleting a training session
  - `settings.changed` for `/settings`, Telegram `/start`, and Telegram `/delete_me`
  - `coros.sync.started/completed/failed` for web and Telegram sync paths
  - `telegram.sent/failed` for Telegram notifications from bot, daily prompts, recovery reminders, and `_telegram_notify`
- **`.env.example`** with logging variables: `LOG_LEVEL`, `LOG_FORMAT`, `LOGS_DIR`, `SLOW_REQUEST_MS`
- **Documentation**: `docs/LOGGING.md`, updated `AGENTS.md` with logging/audit file structure

### Changed
- `src/logger.py` is now a backward-compatible re-export of `src.utils.logger`
- `/logs` web UI now reads from rotated `logs/app_YYYY-MM-DD.log` with fallback to legacy `app.log`
- `src/api/__init__.py` simplified to re-export `register_middleware` and `get_db`

### Fixed
- Duplicate middleware code removed from `src/api/__init__.py` (now lives in `src/api/middleware.py`)

## [30.06.2026]

### Added
- **Telegram-аутентификация для веб-интерфейса**:
  - `src/services/auth.py` — генерация и верификация одноразовых токенов входа
  - `src/api/routes/auth.py` — `/auth/telegram?token=...` для входа, `/auth/logout` для выхода
  - `src/api/deps.py` — `get_current_user` зависимость из session-cookie
  - `SessionMiddleware` в `src/api/middleware.py` с `SECRET_KEY` из `.env`
  - `AuthToken` модель и Alembic-миграция `69f28e182276`
  - Telegram-бот при `/start` и после регистрации отправляет ссылку «Открыть веб-интерфейс»
- **Многопользовательская автосинхронизация Coros** — `_auto_sync_health()` и `_auto_sync_activities()` теперь обходят всех активных пользователей с учётными данными Coros
- **`itsdangerous` и `WEB_APP_URL`** в `.env.example` для session-cookie и ссылок из бота

### Changed
- Убран `current_user_id = 1`; все веб-endpoints используют `current_user: User = Depends(get_current_user)`
- `_update_last_health_sync()`, `_save_dashboard_data()`, `_auto_sync_health_inner()`, `_auto_sync_activities_inner()` теперь принимают `user_id`
- Web UI: добавлен блок пользователя с именем и ссылкой «Выйти» на главной, странице тренировки и настройках

### Fixed
- `get_current_user` и автосинхронизация теперь корректно обрабатывают пользователей с `is_active=NULL` (legacy rows)
- **Автосинк-уведомление о новой тренировке**: `_telegram_notify` после смены сигнатуры вызывался без `user_id` → `TypeError` → тренировка сохранялась, но `last_coros_sync` не обновлялся и Telegram-уведомление не уходило. Исправлен вызов в `_auto_sync_activities_inner`, уведомление обёрнуто в try/except

## [30.06.2026]

### Added
- **`sleep_hrv_interval_list`** (TEXT, JSON) — колонка DailyMetrics для Coros-интервалов HRV (минимальное, низкое, норма start, норма end). Сохраняется из `summaryInfo.sleepHrvData.lastSleepHrvIntervalList` в `_save_dashboard_data()`
- **Миграция**: `ALTER TABLE daily_metrics ADD COLUMN sleep_hrv_interval_list TEXT`

### Changed
- **`_hrv_status()`**: добавлен параметр `intervals=[min, low, normal_start, normal_end]`. Если передан — классификация по Coros-зонам: <min → 🔴, <normal_start → 🟡, normal_start…normal_end → 🟢, >normal_end → 🟣. Если intervals нет — fallback на SD-based классификацию (как было)
- **`render_page()` и `view_training()`**: передают `sleep_hrv_interval_list` (парсинг JSON) в `_hrv_status()`
- **`import json`** вынесен на уровень модуля (был локально в трёх функциях)

### Fixed
- **Dashboard recovery_pct не сохранялся**: `_save_dashboard_data()` искал поля на верхнем уровне, но Coros API возвращает их внутри `summaryInfo`. Исправлено — извлекаем `recoveryPct`, `rhr`, `sleepHrvData` из `dashboard.summaryInfo`
- **Пустые поля восстановления на главной странице**: при отсутствии данных из daily metrics (часы не синхронизированы) `recovery_pct`, `rhr`, `avg_sleep_hrv` теперь заполняются из dashboard API
- **Нагрузка/База (load_impact)**: удалена из блока восстановления, т.к. dashboard API не возвращает этот показатель. Дисплей "Нагрузка: / База: 57" заменён на чистый блок без пустого поля

### Added
- **`pyproject.toml`** — манифест зависимостей проекта (зафиксированы версии всех пакетов)
- **dev-зависимости**: pytest, pytest-asyncio, freezegun, factory-boy
- **tests/** — папка с тестами, `conftest.py` (in-memory SQLite), `pytest.ini`
- **Базовые тесты моделей**: User, TrainingSession, DailyMetrics (3 теста проходят)
- **`User.last_health_sync_at`** — колонка для отслеживания времени последней попытки синхронизации здоровья (используется в recovery check для выбора сообщения)
- **`_update_last_health_sync()`** — сохраняет время синхронизации здоровья в БД из auto sync

### Changed
- **Health sync (`_auto_sync_health_inner`)**: возвращает количество новых записей (0 = пустой ответ, -1 = нет учётных данных). Статус "ok" с пометкой "🟡" при пустом ответе
- **Activity sync (`_auto_sync_activities_inner`)**: возвращает количество новых активностей — статус различает "нет новых" и "синхронизировано N"
- **Web UI**: в `title` блока автосинхронизации показывается полное сообщение статуса (наведение мыши показывает детали)
- **Telegram bot `_sync_for_user`**: при пустом ответе Coros health добавляет предупреждение; сохраняет `last_health_sync_at`
- **Telegram bot `daily_recovery_check_job`**: сообщение зависит от `last_health_sync_at` — если sync был недавно, советует проверить синхронизацию часов; если нет — предлагает /sync

### Fixed
- **Цикл "use /sync" → "no new data"**: recovery check теперь различает "sync не запускался" и "sync прошёл, но данных нет"
- **Чистка `except: pass`** — заменены 11 bare `except: pass` на явные типы с логгированием:

## [30.06.2026]

### Added
- **Dashboard API (`get_dashboard()`)**: теперь вызывается при авто- и ручной синхронизации. Сохраняет recovery%, load_impact, intensity_trend в DailyMetrics
- **Новые колонки DailyMetrics**: `recovery_pct` (INTEGER), `form_score`, `load_impact`, `intensity_trend` (FLOAT) + миграция при старте
- **`_save_dashboard_data()`** — helper для сохранения dashboard данных (создаёт запись today если нет)

### Changed
- **`_readiness_label()`**: приоритет recovery_pct → ATI/CTI ratio → performance. Recovery ≥70% → 🟢, ≥30% → 🟡, <30% → 🔴
- **Web UI блок «Восстановление»**: добавлены поля «Восстановление: 100%», «Нагрузка: 50 / База: 58»
- **Детальный просмотр тренировки**: добавлены «Восстановление» и «Базовая форма» в recovery-блоке
- **Порядок сохранения dashboard**: теперь вызывается ПОСЛЕ обработки daily metrics (чтобы today-запись существовала)
- **Bot sync**: dashboard сохраняется в обоих путях (пустой и непустой ответ metrics)

### Fixed
- **«Требуется отдых» на -1**: readiness больше не использует performance как основной источник — данные Coros dashboard (recovery%) имеют приоритет
- **Dashboard не сохранялся при пустом metrics_list**: исправлено — `_save_dashboard_data` вызывается даже если get_daily_metrics вернул []
  - `main.py`: Telegram notify (httpx.HTTPError), миграции (SAOperationalError), startup (Exception с логом)
  - `src/telegram_bot.py`: delete message (Exception), os.unlink (OSError)
  - `src/crypto.py`: запись ключа в .env (OSError/PermissionError)
  - `src/parsers/common.py`: запрос погоды (RequestException/ValueError)
  - Добавлен логгер `src/parsers/common.py` (раньше не было)

## [30.06.2026]

### Added
- **Анализ проекта и аудит технического долга (Project analysis and tech debt audit)**:
  - Проведён комплексный анализ кодовой базы и архитектуры проекта (29.06.2026)
  - Анализ выполнен моделью **Cloud Opus 4.8**
  - Обнаружен и задокументирован технический долг, блокирующий дальнейшее развитие
  - Создан `TECH_DEBT.md` — подробное руководство по исправлению 13 проблем с приоритетами 🔴🟠🟡
  - Создан `decision_module_design.md` — архитектура модуля аналитики и рекомендаций (8 этапов)
  - Решение: перед разработкой модуля аналитики необходимо устранить техдолг (4 спринта)
  - Рекомендация: начинать со Спринта 1 (pyproject.toml, тесты, WAL, чистка except)

### Added (Спринт 2 — продолжение)
- **Alembic baseline**: миграция `c3f51ae84837` — индексы `ix_*_user_id` на 3 таблицах + `uq_user_date`. ALTER TABLE блок удалён из `startup()`, заменён на `alembic upgrade head`
- **Миграция `0bba2c2badec`**: удалена таблица `user_settings` (DROP TABLE)
- **Модель `UserSettings` удалена** — все обращения перенесены на `User`:
  - `get_settings()` — читает из `User` (id=1), прокси `.weight` → `weight_kg`
  - `coros_sync` — `UserSettings` → `User`
  - `coros_sync_health` — `UserSettings` → `User`
  - `_auto_sync_health_inner` — `UserSettings` → `User`
  - `_auto_sync_activities_inner` — `UserSettings` → `User`
  - Telegram bot регистрация и синхронизация — `UserSettings` → `User`
- **`SAOperationalError`** импорт удалён из main.py (больше не используется)

### Fixed
- **`_hrv_status()`**: классификация по Coros-зонам (интервалы `[5,30,38,56]`). HRV=38 → 🟢 Норма (было 🟡 Пониженная)
- **`_save_dashboard_data()`**: чтение из `dashboard.summaryInfo` вместо верхнего уровня; только NULL-поля перезаписываются
- **Чистка `startup()`**: удалён мёртвый код миграции из `user_settings`
- **Синхронизация тренировок падала с `Internal Server Error`**: в `coros_sync()` отсутствовал `from src.models import User` — `NameError` при запросе `/coros/sync`. Фронтенд получал plain text "Internal Server Error" вместо JSON, JS падал с `Unexpected token 'I'`. Импорт добавлен

### Changed (Спринт 2.2 — get_db via Depends)
- **`get_db()`** зависимость добавлена в `src/models.py` (yield-генератор с `db.close()` в finally)
- **9 эндпоинтов** переведены на `db: Session = Depends(get_db)` вместо `db = SessionLocal()` + `try/finally db.close()`:
  - `index`, `upload_files`, `confirm_upload`, `confirm_deleted`, `session_detail`, `session_delete`, `settings_save`, `coros_sync`, `coros_sync_health`
- **`render_page(db, ...)`** — теперь принимает `db` параметром (раньше создавал свой)
- Non-endpoint функции (`startup`, `_run()` замыкания в фоновых потоках, `_auto_sync_*_inner`, `_update_last_health_sync`) оставлены на `SessionLocal()` — Depends недоступен вне request scope
- Удалены лишние `try/finally db.close()` блоки — закрытие сессии теперь управляется Depends

## [29.06.2026]

### Added
- **Проверка данных о сне (Recovery data check)** — `daily_recovery_check_job()`:
  - Старт в 10:00, проверка наличия `DailyMetrics` за последние 12 часов
  - Если данные есть → следующая проверка в 18:00
  - Если данных нет → проверка каждые 2 часа (12:00, 14:00, 16:00, 18:00)
  - Ночью (0:00–8:00) и после 20:00 — не отправляет уведомления
  - При отсутствии данных отправляет напоминание через Telegram: "🌙 Нет данных о восстановлении — используй /sync"
- **Система оценки тренировок (Training feedback 0–10)** — пользователь оценивает каждую тренировку от 0 до 10 по шкале сложности:
  - Модель `TrainingFeedback` в БД: `session_id`, `user_id`, `rating` (0–10), `notes`, `created_at`
  - При автоматической синхронизации Coros и ручном `/sync`: после импорта новых тренировок бот отправляет уведомление с деталями тренировки и кнопками оценки 0–10 (два ряда: 0-5 и 6-10)
  - Оценка сохраняется через callback `feedback:{session_id}:{rating}`, каждую тренировку можно оценить только один раз
  - Эмодзи для оценок: 0=😴, 1=😌, 2=🙂, 3=😐, 4=😅, 5=💪, 6=😤, 7=🥵, 8=😵, 9=💀, 10=⚰️
- **Автоматические уведомления Telegram** при автосинхронизации:
  - При обнаружении новых тренировок пользователь получает уведомление в Telegram с деталями тренировки и кнопками оценки
  - Аналогично при ручной синхронизации через `/sync`
- **Ежедневный опрос веса (Daily weight reminder)**:
  - Запуск в 9:00 каждый день через `APScheduler`
  - Отправляет сообщение: "📊 Утренний вес? (введите число или /skip)"
  - Ответ сохраняется в `WeightMeasurement`, пропуск возможен через `/skip`
  - Ручной ввод через команду `/weight <kg>`
- **Безопасность сообщений с паролем** — сообщение с паролем Coros автоматически удаляется через 2 секунды после отправки (защита от скриншотов, forward, сохранения в истории)
- **Telegram-бот** (`src/telegram_bot.py`):
  - `/start` — диалог регистрации: сбор Coros email + пароль, сохранение в `User` модель (шифрование)
  - `/sync` — синхронизация тренировок и метрик здоровья для пользователя
  - `/stats` — общая статистика (тренировки, дистанция, время, здоровье)
  - `/trainings` — последние 5 тренировок
  - `/delete_me` — удаление всех данных пользователя
  - Фоновый поток при старте сервера (запускается в `startup()`)
  - Работает через `python-telegram-bot` v22, токен из `.env` (`TELEGRAM_BOT_TOKEN`)
- **Очистка БД**: удалены все тренировки (26), метрики (48), замеры веса, Coros credentials — пользователь начинает с нуля

### Fixed
- **Дублирующий `reply_markup`** в `_sync_for_user()` (строка 362) — убран второй `reply_markup={"inline_keyboard": rows}`, уведомления о новых тренировках доходят корректно
- **user_id во всех запросах БД**: upload, confirm_upload, confirm_deleted, session_detail, session_delete, settings_save, coros_sync, coros_sync_health, _auto_sync_* — везде добавлен `.filter(Table.user_id == _current_user_id)`
- **settings_save** теперь сохраняет настройки также в модель `User`
- **Создание записей**: добавлен `user_id=_current_user_id` при создании DailyMetrics, WeightMeasurement, DeletedTraining, TrainingSession
- **Исправлены ошибки отступов** в session_delete и coros_sync_health (синтаксис Python)

### Added
- **Документация метрик здоровья Coros** в `docs/coros_health_metrics.md` — теоретическая база для будущего модуля анализа и рекомендаций (HRV, RHR, tiredness, readiness, нагрузка, ATI/CTI, stamina)
- **Осмысленное отображение метрик здоровья** — вместо сухих чисел:
  - `HRV: 38.0` → `Нервная система: 🟢 Норма (38)`
  - `RHR: 57` → `Пульс покоя: 57 уд/мин`
  - `Усталость: -8` → `Усталость: 🟢 Низкая / 🟡 Умеренная / 🔴 Высокая`
  - `Готовность: -1` → `Состояние: 🟢 Готов к тренировкам / 🟡 Умеренная готовность / 🔴 Требуется отдых`
  - `Нагрузка: 245` → `Нагрузка: Высокая (лёгкая / средняя / высокая)`
- **Эндпоинт `/analyse/query`** в `coros_client.py` — получение 12-недельной аналитики (VO₂max, LTHR, LTSP, stamina trend)
- **Новые поля `ltsp` и `stamina_level_7d`** в модели `DailyMetrics` — темп лактатного порога и 7-дневный тренд выносливости
- **Автомиграция** для новых колонок `daily_metrics`
- **Мерж аналитики в health sync** — при синхронизации данные из `/analyse/query` дозаполняются в записи daily_metrics (22 записи обновлено)
- **Автоматическая фоновая синхронизация Coros** — сервер сам проверяет новые данные без нажатия кнопок:
  - Health sync: раз в ~60 мин (env `COROS_HEALTH_SYNC_INTERVAL`, ±20% jitter)
  - Activity sync: раз в ~180 мин (env `COROS_ACTIVITY_SYNC_INTERVAL`, ±20% jitter)
  - Запускается при старте сервера через daemon-thread в `_auto_sync_health()` / `_auto_sync_activities()`
  - Graceful error handling: ошибки API не роняют планировщик
  - Логирование в `app.log` с префиксом `Автосинхронизация`
- **Доработка автосинхронизации**:
  - `_auto_sync_activities` использует `since=us.last_coros_sync` — только новые активности
  - Пропуск ранее удалённых тренировок при автосинхронизации (только ручной импорт)
  - Статус-бар на главной: health + activities, время последней/следующей синхронизации
  - Трекинг статуса в `_auto_sync_status` с обработкой ошибок (ok/syncing/error)

### Changed
- **Интервалы автосинхронизации** — приоритеты переставлены:
  - Health: 6 ч (данные сна/восстановления не меняются в течение дня)
  - Activities: 1 ч (тренировка может появиться в любое время)
  - Настраиваются через `COROS_HEALTH_SYNC_INTERVAL` / `COROS_ACTIVITY_SYNC_INTERVAL`

### Changed
- **График на главной странице**: только пульс покоя (RHR), 30 дней данных, хронологический порядок (слева направо). HRV убран с графика.
- **Документация `coros_health_metrics.md`**: добавлена таблица статуса доступности каждой метрики (✅ из API / 🧮 расчёт / ❌ недоступно)

### Fixed
- **user_id во всех запросах БД**: upload, confirm_upload, confirm_deleted, session_detail, session_delete, settings_save, coros_sync, coros_sync_health, _auto_sync_* — везде добавлен `.filter(Table.user_id == _current_user_id)`
- **settings_save** теперь сохраняет настройки также в модель `User`
- **Создание записей**: добавлен `user_id=_current_user_id` при создании DailyMetrics, WeightMeasurement, DeletedTraining, TrainingSession
- **Исправлены ошибки отступов** в session_delete и coros_sync_health (синтаксис Python)

### Fixed
- **Coros health sync: даты в формате YYYYMMDD и тип int** — API `/analyse/dayDetail/query` принимает даты без дефисов (`20260601`), поле `happenDay` приходит как `int`, а не `str`. Исправлено: формат дат в `strftime("%Y%m%d")`, преобразование `happenDay` в строку перед парсингом.

### Added
- **Ежедневные метрики здоровья из Coros (Coros daily health metrics — sleep, HRV, recovery)**
  - Новые эндпоинты в `coros_client.py`: `get_dashboard()` (HRV за 7 дней) и `get_daily_metrics(start_day, end_day)` (дневные метрики за период) через Training Hub API (`/dashboard/query`, `/analyse/dayDetail/query`)
  - Новая модель `DailyMetrics` в БД — хранит: HRV, RHR, уровень усталости, тренировочную нагрузку, готовность, VO₂max, LTHR, stamina
  - Автомиграция: таблица `daily_metrics` создаётся при старте сервера
  - Фоновый эндпоинт `POST /coros/sync/health` — синхронизирует метрики за последние 180 дней инкрементально (только новые даты)
  - Кнопка «❤️ Health Sync» на главной странице (фиолетовая, рядом с Coros Sync)
  - Карточка «Восстановление» на главной — показывает последние HRV, RHR, усталость, готовность с кликабельным графиком HRV за 7 дней
  - Блок «Восстановление перед тренировкой» на странице детального просмотра тренировки — HRV, пульс покоя, усталость, готовность, нагрузка на день тренировки
  - HRV и RHR графики на одной шкале (Chart.js, фиолетовый/красный)

## [28.06.2026]

### Changed
- **Навигация по годам/месяцам на главной странице**: добавлены ряды переключателей годов и месяцев (только года/месяцы с данными). При выборе месяца показываются все тренировки за этот период. По умолчанию — последний месяц с данными.
- **Убрана колонка «Сегм.»** из таблицы тренировок на главной — количество сегментов теперь видно только внутри карточки тренировки. Тип тренировки (интервальная/темповая) остаётся в таблице.

### Added
- **Интеграция Coros (Coros Training Hub sync)**
  - Новый модуль `src/coros_client.py` — клиент для неофициального Coros API (аутентификация, список активностей, загрузка FIT)
  - Кнопка «🔄 Coros Sync» на главной странице — запускает синхронизацию новых беговых тренировок
  - Поля `coros_email` / `coros_password` / `last_coros_sync` в настройках пользователя
  - Автомиграция БД: колонки добавляются при старте сервера
  - Синхронизация скачивает FIT-файлы, парсит их через существующий FIT-парсер и сохраняет в БД
  - Поддерживаются только беговые активности (RUNNING, TRAIL_RUNNING)
  - **Ручная загрузка TCX/FIT больше не нужна** — после привязки аккаунта Coros все тренировки подтягиваются автоматически одной кнопкой «🔄 Coros Sync»

### Fixed
- **Сохранение `last_coros_sync`**: обновление `max_act_ts` теперь происходит и для уже импортированных активностей (до `continue` в блоке `already_imported`), а не только для новых. Без этого `last_coros_sync` оставался `None`, и при каждом нажатии кнопки синхронизации повторно скачивались все 26 активностей.
- **Детекция дубликатов**: заменено точное сравнение `begin_ts` на временное окно (±120 секунд), чтобы избежать проблем с часовыми поясами (БД хранит локальное MSK время, Coros отдаёт UTC).
- **FIT-парсер для Coros**: заменён `fitparse` на `fitdecode` — Coros Pace 4 генерирует FIT с `invalid field size 1 for type 'uint32'`, который `fitparse` не переваривает, а `fitdecode` обрабатывает с предупреждением.
- **Таймауты запросов**: добавлен параметр `timeout=15` во все HTTP-вызовы Coros API, чтобы сервер не зависал при недоступности облака Coros.
- **UI-таймаут**: добавлен `AbortController` с 30-секундным таймаутом на клиентский fetch, чтобы страница не висела вечно.
- **UI-статус**: добавлен `statusDiv` с сообщениями («Подключение к Coros...», «✅ Синхронизировано: N», «❌ Ошибка»), чтобы пользователь видел, что происходит при нажатии кнопки синхронизации.
- **Починена кнопка Coros Sync**: функция `syncCoros` была объявлена внутри обработчика `fileInput.change` и не была доступна из `onclick` — переведена на `addEventListener` в глобальной области.
- **Синхронизация в фоне + real-time прогресс**: POST `/coros/sync` запускает синхронизацию в фоновом потоке и сразу возвращает `task_id`. Клиент опрашивает `GET /coros/sync/status/{task_id}` каждые 800 мс и отображает текущий шаг, прогресс-бар и количество обработанных активностей.
- **Убран `since` из запроса к Coros**: `list_activities` теперь всегда загружает все активности (с пагинацией). Удалённые из БД тренировки снова загружаются при следующей синхронизации.
- **Ответ синхронизации**: вместо `total` теперь `total_found` (сколько найдено на Coros) и `processed` (сколько обработано).
- **Система логирования**: новый модуль `src/logger.py` — ротация логов в `app.log` (5 файлов × 1 МБ). Добавлен endpoint `/logs?lines=N` для просмотра лога в браузере. Логируются все ключевые операции (sync, upload, ошибки).
- **Убраны alert/confirm диалоги**: при синхронизации и загрузке файлов больше не показываются модальные окна. Проблемные тренировки (с очисткой GPS, <1 км) сохраняются сразу, без подтверждения. Удалён `/upload/confirm` из JS-кода.
- **Шифрование пароля Coros**: добавлен модуль `src/crypto.py` — пароль Coros шифруется Fernet-ключом из `.env` (`COROS_CRED_KEY`) перед сохранением в БД. На странице настроек вместо пароля отображается плейсхолдер (`********`). Для старых записей с открытым паролем сохраняется обратная совместимость (fallback на plaintext при неудачной расшифровке).
- **Отслеживание удалённых тренировок (Deleted training tracking)**:
  - Новая модель `DeletedTraining` в БД — хранит метаданные (дата, дистанция, темп, пульс, тип, длительность, калории, каденс, VO₂max, эффект) перед удалением
  - Автомиграция: таблица `deleted_trainings` создаётся при старте сервера
  - При удалении тренировки метаданные сохраняются в `DeletedTraining` до подтверждения пользователя
  - При ручной загрузке (`/upload`): если тренировка была ранее удалена, сервер возвращает детали (`deleted_match`) и временный ID (`temp_id`), не сохраняя данные сразу
  - Новый endpoint `POST /upload/confirm_deleted` — принудительное сохранение ранее удалённой тренировки с удалением записи из `DeletedTraining`
  - UI: модальное окно подтверждения с деталями тренировки (дата, дистанция, темп, длительность, тип, пульс, калории) и кнопками «Импортировать» / «Пропустить»
  - Coros sync: при обнаружении ранее удалённой тренировки данные сохраняются в `_pending`, синхронизация продолжается, а после завершения показывается модал подтверждения (как при ручной загрузке)

## [28.06.2026]

### Added
- **Каденс (Cadence)**
  - Парсинг `RunCadence` из секции `Extensions/TPX` в TCX-файлах (Garmin и другие часы, поддерживающие этот тэг)
  - Средний каденс за тренировку отображается на главной странице в колонке «Каденс» и в карточке тренировки
  - Каденс по сегментам отображается в детальном просмотре тренировки в таблице отрезков
  - Данные сохраняются в модель `TrainingSession` (`avg_cadence`) и в каждый сегмент (`segments_json[].avg_cadence`)
  - Автомиграция БД: колонка `avg_cadence` добавляется при старте сервера
- **FIT-парсер (FIT parser)**
  - Новый парсер бинарного формата `.fit` (стандарт Garmin/FIT, используется Coros, Garmin, Polar, Suunto)
  - Содержит все метрики: дистанция, пульс, каденс, темп, высота, GPS
  - Каденс в FIT (spm) доступен «из коробки», в отличие от TCX от Coros
  - Загрузка `.fit` файлов через тот же интерфейс — кнопка «Загрузить TCX/FIT»
  - Парсинг session-сообщений: **Training Effect** (аэробный/анаэробный), **VO₂max**, **калории**
- **Рефакторинг: общая логика обработки (Refactoring: shared processing pipeline)**
  - Выделен `src/parsers/common.py` — общие функции: очистка трекпоинтов, сегментация, классификация, погода
  - `tcx_parser.py` и `fit_parser.py` только парсят формат и вызывают `process_trackpoints()` из common

### Fixed
- **Каденс Coros (RPM → SPM)**: авто-удвоение каденса <100 spm для Coros (хранит в RPM)
- **Часовой пояс**: явное указание UTC перед конвертацией в локальное время; fallback на `Europe/Moscow` если GPS не определён
- **Существующие тренировки**: исправлено время в БД (+3ч для UTC-записей)

### Changed
- **Отображение метрик в детальном просмотре**: добавлены подписи под каждым показателем (Дистанция, Общее время, Пульс, Каденс, Подъем, Спуск, Калории) — формат: метка сверху, значение крупно, единица снизу
- **Подъем/Спуск**: раздельные карточки вместо `↑x / ↓y` в одной
- **Единицы**: `bpm` → `уд/мин`, `spm` → `Каденс`, `м` жирным шрифтом
- **Погода**: перенесена под дату как фоновая информация (не в ряду метрик)
- **Training Effect / VO₂max**: удалены из парсера и отображения (не экспортируются Coros в FIT)
- **Главная таблица**: колонки переименованы (Метрики → Энергозатраты, ккал; Длит. → Длительность); калории — крайняя правая колонка; выравнивание по центру
- **Набор/спуск в таблице**: отображается как `↑x / ↓y` (восстановлен прежний формат)
- **Детальная карточка**: подписи меток (Дистанция, Пульс и т.д.) жирные, единицы измерения (км, уд/мин, м, ккал) тоже жирные; стрелки ↑/↓ убраны из значений подъёма/спуска

## [27.06.2026]

### Added
- **Прогресс-бар загрузки (Upload progress bar)**
  - Файлы отправляются по одному с отображением реального прогресса: «Обработано X из Y (Z%)»
  - Зелёная полоса прогресса обновляется после каждого файла
  - Проблемные файлы накапливаются и показываются одним confirm-диалогом в конце
- **Детекция ошибочных точек (Bogus point detection + cleaning)**
  - Функция `clean_trackpoints()` — удаляет GPS-скачки и нереальный темп, логирует удалённые участки в `cleaning_log`
  - Пересчёт накопленной дистанции после очистки: phantom-дельты с нереальным темпом отбрасываются
  - `cleaning_log` (JSON) в модели `TrainingSession`
  - Настройки детекции в `/settings`: `max_credible_pace`, `max_gps_jump_m`, `min_hr_for_fast_pace`
  - ✂️ бейдж на главной и детальный лог на странице тренировки
- **Подтверждение сомнительных тренировок (Confirm dialog for problematic uploads)**
  - Если после очистки осталось <1 км или тренировка `invalid` — сервер возвращает JSON, браузер показывает `confirm()`
  - Пользователь решает: добавить или отбросить
- **Файл CHANGELOG.md** — история изменений проекта
- **Файл AGENTS.md** — контекст для ИИ-агента (план, архитектура, стиль, workflow)

### Fixed
- **Пересчёт дистанции после очистки**: теперь `total_distance_km`, сегменты и темп используют только корректные дельты между оставшимися точками
- **JS-синтаксис**: `\n` в Python f-строке не экранировался, что ломало confirm-диалог — .catch() редиректил на главную без сохранения

## [21.06.2026] — Погода, высота, графики

### Added
- **Высота (Elevation)**: парсинг `AltitudeMeters`, расчёт набора/спуска в сегменты и суммарно
- **Часовой пояс**: определение через `timezonefinder` по первой GPS-координате, конвертация UTC → локальное время
- **Погода (Open-Meteo)**: температура и WMO-иконка по GPS-координатам и дате; кэширование в памяти
- **Иконка погоды**: вместо текста «Темп.» колонка «Погода» с иконкой (☀️⛅☁️🌫️🌦️🌧️❄️🌨️⛈️)
- **WMO weathercode**: сохраняется в модель и сегменты
- **График пульса/темпа**: Chart.js с двойной осью, скользящее окно 10 сек
- **Индикатор загрузки**: overlay со спиннером при выборе TCX
- **Полноэкранный режим**: убрано max-width на страницах списка и деталей
- **Автомиграция БД**: ALTER TABLE при старте для новых колонок
- **Settings**: max_hr, max_credible_pace, max_gps_jump_m, min_hr_for_fast_pace

### Changed
- Комментарии во всех файлах переведены на двуязычный формат (RU/EN)

## [20.06.2026] — Сегментация и классификация

### Added
- **Сегментация**: км-блоки по умолчанию, сплит только для интервальной
- **Классификация**: подсчёт вариативных км (200м бины для сглаживания GPS-шума)
  - 3+ вариативных км → Интервальная
  - 1–2 → Темповая
  - 0 → Long/Recovery по ЧСС и длительности
- **Пульсовые зоны Z1–Z5** с расчётом времени в каждой
- **format_duration** (мм:сс) для длительности сегментов
- **Минимум 200м** для дробления сегмента

### Fixed
- Дистанция округляется до 1 знака
- Пороги пульсовых зон обновлены по таблице пользователя

## [10.06.2026 .. 18.06.2026] — Первая версия

### Added
- Окружение: FastAPI + SQLite + SQLAlchemy
- Базовая модель TrainingSession
- Парсинг TCX (дистанция, пульс, время, GPS)
- Базовая классификация тренировок
- Агрегация статистики (неделя/месяц)
- Вес пользователя (график и таблица)
- README со скриншотами
- GitHub-репозиторий
