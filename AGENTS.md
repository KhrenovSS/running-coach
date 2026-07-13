# Контекст проекта Running Coach

## Суть
Персональный AI-тренер для бега. Парсит TCX-файлы (любые часы: Garmin, Coros, Polar, Suunto), анализирует тренировки, определяет тип (интервальная/темповая/long/recovery), разбивает на сегменты, считает пульсовые зоны, очищает GPS-ошибки.

## Стек
Python + FastAPI + PostgreSQL 16 (Docker Compose), написано через ИИ (open code style).
Сервер: Docker Compose — 3 контейнера (`db`, `app`, `bot`).
Локальная разработка: `docker compose up db -d && DATABASE_URL=postgresql://running_coach:<PASSWORD>@localhost:5432/running_coach uvicorn main:app --host 0.0.0.0 --port 8000`.

## Дисциплина работы ИИ-агента (AI Agent Discipline)

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

6. **Протокол конца сессии.** commit → обновить чекбоксы в `AGENTS.md` → обновить `CHANGELOG.md` → push → отчёт пользователю.

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
1. **Константы** — используй `from src.config import CONFIG`. Никаких magic numbers.
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
- `src/models.py` — все ORM модели (планируется разбивка Sprint 11)
- `src/config/settings.py` — `Settings(BaseSettings)` из pydantic-settings
- `src/config/constants.py` — плоские module-level константы
- `src/exceptions.py` — типизированные исключения приложения (`WatchAPIError`, `WatchAuthError`, `NotFoundError`, etc.)
- `src/deps.py` — общие зависимости (Jinja2Templates и др.)
- `src/utils/logger.py` — структурированное логирование с ротацией
- `src/watch/` — мульти-брендовая абстракция часовых клиентов (`base.py`, `coros.py`, `factory.py`)
- `src/services/audit.py` — сервис аудита (БД + файл)
- `src/services/auth.py` — генерация и проверка токенов Telegram-авторизации, bcrypt
- `src/services/sync_service.py` — бренд-независимая логика синхронизации
- `src/services/sync_utils.py` — хелперы синхронизации (TODO Sprint 11)
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

## Текущее состояние (Session — 13.07.2026 — Модуль анализа + отладка алгоритма)

**Фаза A ✅:** Починены сломанные импорты в `src/telegram/` (AUDIT-015), удалены `COROS_SYNC_*` константы (AUDIT-011).
**Фаза B ✅:** Тонкие роуты (sync.py 444→93), мульти-бренд settings, единый `run_sync_for_user`, пакет `pages/`.
**Фаза C ✅:** Cleanup: `requests`→`httpx`, удалены мёртвые зависимости, `CorosAPIError`→`WatchAPIError` (brand-agnostic).
**Фаза D ✅:** Документация: `BACKLOG.md`, `docs/CHECKLIST_NEW_PROVIDER.md`, усилен `AGENTS.md`.
**Модуль анализа ✅:** Новый пакет `src/analysis/` (классификация, сегментация, пульсовые зоны, утилиты).
**Алгоритм интервалов ✅:** `src/analysis/oscillation.py` — детекция по базовому темпу (easy pace) + HR-lag корреляция.
**Отладка анализа ✅:** Исправлены баги: base_pace self-defeating, HR-lag инверсия, time units, NameError. Добавлен умный fallback: км-блоки если сегменты похожи или число отлично от км. 40 тестов, 29 тренировок пересчитаны (27/29 ✓).

### Что сделано в этой сессии (13.07.2026):
1. Создан `src/analysis/` (6 файлов): `__init__.py` (оркестратор process_trackpoints), `oscillation.py` (easy_pace + pace_gap детекция + HR-lag), `classify.py`, `segment.py`, `hr_zones.py`, `utils.py`
2. Удалены старые модули из `src/parsers/`: `common.py`, `segmentation.py`, `classification.py`, `hr_zones.py`, `utils.py`
3. `src/models.py`: `TrainingSession.training_type_override` + `trackpoints_json`; `User`: `interval_pace_threshold`, `interval_min_phase_duration`, `interval_hr_lag_sec`, `interval_min_oscillations`
4. Alembic миграции: `d1e2f3a4b5c6` (6 колонок) + `e5f6a7b8c9d0` (rename amplitude → pace_threshold)
5. `src/services/reanalyze.py`: пересчёт тренировок из сохранённых трекпоинтов с override типа
6. `POST /session/{id}/reanalyze`: эндпоинт + dropdown типа в `session.html`
7. `src/config/constants.py`: `DEFAULT_PACE_THRESHOLD=1.0`, `DEFAULT_MIN_PHASE_DURATION_SEC=15`, `DEFAULT_HR_LAG_SEC=5`, `DEFAULT_MIN_OSCILLATIONS=3`
8. `settings.html`: настройки интервалов — порог ускорения (ввод в секундах, отображение X:XX мин/км)
9. `trackpoints_json` сохраняется при загрузке TCX/FIT и синхронизации с часов
10. Новый алгоритм oscillation: `base_pace = easy_pace`, `threshold = base_pace - pace_gap`, work = темп < threshold, recovery = темп >= threshold
11. **Отладка анализа (13.07.2026):**
    - `oscillation.py`: base_pace self-defeating → `mean(paces >= overall_mean)` 
    - `oscillation.py`: HR-lag инверсия → `pace_change = -(p_cur - p_prev)`
    - `segment.py`: CHANGE_POINT_MIN_DIFF 0.3 → 0.5 + умный fallback
    - `segment.py`: time units bug в _km_segment_fallback
    - `reanalyze.py`: NameError _run_async → run_async_in_thread
    - `reanalyze.py`: _restore_trackpoints добавлены недостающие ключи
    - `analysis/__init__.py`: _serialize_trackpoints сохраняет None
    - Добавлены 40 тестов (tests/)

### Коммиты:
- `cda4a0a` Sprint 8+9: разбивка parsers/common.py и telegram_bot.py на пакеты
- `3b4dd34` fix segmentation and tcx_parser import
- `f1a60fa` feat: модуль анализа + новый алгоритм детекции интервалов
- `99be684` fix: отладка и улучшение алгоритма анализа (40 тестов, 29 тренировок пересчитаны)
- *(Фаза A+B+C+D: коммит будет выполнен после проверки)*

### Следующие шаги:
- **Docker**: пересобрать `app` и `bot` (изменены weather.py, exceptions.py, coros.py, sync_service.py, sync_runner.py, pyproject.toml)
- **Коммит**: Фаза A+B+C+D → push
- **Sprint 10**: Тесты (минимум 20) с реальными TCX/FIT-файлами ✅ (40 тестов)
- **Sprint 11**: Разбивка models.py + sync_service.py на пакеты.
- **Sprint 12**: Чистка роутов (sync.py, pages.py).
- **Sprint 13-15**: Фазы 3-5 (новая функциональность).

### Команды управления:
```bash
./bin/docker.sh up -d        # запуск
./bin/docker.sh down          # остановка
./bin/docker.sh build app     # пересборка app
./bin/docker.sh build bot     # пересборка bot
python3 -m alembic upgrade head  # миграции
```
