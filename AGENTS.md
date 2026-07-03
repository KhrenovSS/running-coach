# Контекст проекта Running Coach

## Суть
Персональный AI-тренер для бега. Парсит TCX-файлы (любые часы: Garmin, Coros, Polar, Suunto), анализирует тренировки, определяет тип (интервальная/темповая/long/recovery), разбивает на сегменты, считает пульсовые зоны, очищает GPS-ошибки.

## Стек
Python + FastAPI + PostgreSQL 16 (Docker Compose), написано через ИИ (open code style).  
Сервер: Docker Compose — 3 контейнера (`db`, `app`, `bot`).  
Локальная разработка: `docker compose up db -d && DATABASE_URL=postgresql://running_coach:<PASSWORD>@localhost:5432/running_coach uvicorn main:app --host 0.0.0.0 --port 8000`.

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
10. **Мульти-брендовость закладывать сразу** — не хардкодить «coros»:
    - Креды → `WatchCredential`, не поля `coros_*` на `User`.
    - Клиент часов → `BaseWatchClient(ABC)` в `src/watch/`, не standalone `CorosClient`.
    - Audit-события → `sync.{brand}.*`, не `coros.sync.*`.
    - Роуты → `/sync/{brand}`, не `/coros/sync`.
    - Sync-сервис принимает `BaseWatchClient`, не `CorosClient`.
    - Credential key → `CRED_KEY` (с fallback на `COROS_CRED_KEY`).

## Структура файлов
- `main.py` — 7 строк: `create_app()` + `uvicorn.run()`
- `src/startup.py` — фабрика FastAPI, startup-событие, подключение роутов
- `src/scheduler.py` — `AutoSyncScheduler` (бренд-независимый, перебирает `WatchCredential`)
- `src/models.py` — модель TrainingSession, DailyMetrics, WatchCredential (SQLAlchemy)
- `src/config/settings.py` — `Settings(BaseSettings)` из pydantic-settings
- `src/config/constants.py` — плоские module-level константы (HR зоны, API endpoints, пороги)
- `src/exceptions.py` — типизированные исключения приложения
- `src/deps.py` — общие зависимости (Jinja2Templates и др.)
- `src/utils/logger.py` — структурированное логирование с ротацией
- `src/watch/` — мульти-брендовая абстракция часовых клиентов:
  - `base.py` — `BaseWatchClient(ABC)`
  - `coros.py` — `CorosWatchClient(BaseWatchClient)` (бывший `coros_client.py`)
  - `factory.py` — реестр брендов: `register(brand, cls)`, `get_watch_client(brand, **kwargs)`
- `src/services/audit.py` — сервис аудита (БД + файл; события `sync.{brand}.*`)
- `src/services/auth.py` — генерация и проверка токенов Telegram-авторизации, bcrypt
- `src/services/sync_service.py` — бренд-независимая логика синхронизации (принимает `BaseWatchClient`)
- `src/telegram_bot.py` — Telegram-бот
- `src/api/middleware.py` — централизованная обработка ошибок, логирование запросов и session middleware
- `src/api/deps.py` — `get_current_user` dependency (session-cookie)
- `src/api/routes/health.py` — health check endpoint
- `src/api/routes/auth.py` — маршруты аутентификации
- `src/web/state.py` — глобальное состояние (`_pending`, `_sync_tasks`)
- `src/web/routes/pages.py` — GET /, /login, /register, /session/{id}, /settings
- `src/web/routes/uploads.py` — POST /upload, /upload/confirm
- `src/web/routes/sync.py` — POST /sync/{brand}/run, /sync/{brand}/health, /sync/status/{id}
- `src/web/routes/logs.py` — GET /logs
- `src/web/templates/` — 6 Jinja2-шаблонов (base, index, login, register, session, settings)
- `src/parsers/common.py` — общая логика: очистка треков, сегментация, классификация, погода
- `src/parsers/tcx_parser.py` — парсинг TCX-файлов
- `src/parsers/fit_parser.py` — парсинг FIT-файлов
- `src/parsers/fit_parser.py` — парсинг FIT-файлов (бинарный) → вызов `process_trackpoints()`

## Реализованная логика

### Сегментация
- По умолчанию: каждый километр — отдельный сегмент (км-блоки)
- Внутри км сплит делается только если тренировка опознана как интервальная
- Минимальная дистанция сегмента 200м (<200м не дробить)
- Дистанция округляется до 1 знака (1.0 км, а не 0.999)

### Классификация тренировки
- Внутри каждого км считаются 200м бины, для каждого бина — средний темп
- Если разница макс/мин темпа бинов внутри км > 1 мин/км — км считается "вариативным"
- **3+ вариативных км** → Интервальная (сплит этих км на быстрый/медленный сегмент)
- **1–2 вариативных км** → Темповая (км-блоки как есть, без сплита)
- **0 вариативных км** → Long/Recovery по ЧСС и длительности

### Пульсовые зоны (max_hr=177 по умолчанию)
- Z1: 60–70% (106–124 bpm)
- Z2: 70–80% (124–142 bpm)
- Z3: 80–87% (142–154 bpm)
- Z4: 87–93% (154–165 bpm)
- Z5: 93–100% (165–177 bpm)

### Формат отображения
- Длительность сегментов: мм:сс (3:09), не дробные минуты
- Вместо easy/moderate/hard показывать Z1–Z5

## Реализованная логика
- `killall uvicorn` НЕ убивает процесс (команда python, а не uvicorn). Использовать `pkill -9 -f "uvicorn main"`.
- При удалении БД через rm старый процесс продолжает держать данные через file descriptor. Надо убить процесс, потом удалять БД, потом запускать заново.
- - TCX — универсальный формат, не привязан к Garmin. Подходят часы Coros, Polar, Suunto и любые другие, умеющие экспортировать TCX.
- В перспективе: получение данных о сне и восстановлении с часов Coros (через Coros API или экспорт).
- TCX-файлы лежат в `/home/nimda/uploads/` и `/home/nimda/projects/tcx/`
- Настройка max_hr вынесена в Settings (POST /settings, доступно по /settings)
- Время тренировки сохраняется в локальном часовом поясе (без tzinfo). Определяется по GPS через timezonefinder.
- Open-Meteo API: `archive-api.open-meteo.com/v1/archive`. Параметры: lat, lon, start_date, end_date, hourly=temperature_2m,precipitation, timezone=UTC.
- Полная модель TrainingSession: `id`, `begin_ts`, `total_distance_km`, `avg_heart_rate`, `max_heart_rate`, `training_type`, `segments_count`, `duration_minutes`, `segments_json`, `hr_pace_series`, `avg_temperature`, `weather_code`, `elevation_gain`, `elevation_loss`, `suspect_flags`, `cleaning_log`.
- Модель DailyMetrics: `date` (unique), `avg_sleep_hrv`, `sleep_hrv_baseline`, `sleep_hrv_sd`, `rhr`, `tired_rate`, `training_load`, `training_load_ratio`, `performance`, `ati`, `cti`, `vo2max`, `lthr`, `stamina_level`, `synced_at`.
- Health sync endpoint: `POST /coros/sync/health` — фоновая синхронизация через `/analyse/dayDetail/query` за 180 дней инкрементально.
- На странице детального просмотра тренировки показывается блок восстановления (`recovery_html`) если на дату тренировки есть записи в `DailyMetrics`.

## Важные моменты

**ВАЖНО: комментарии писать СРАЗУ при написании кода, а не добвлять потом отдельным коммитом.**

При написании любого кода (новые функции, классы, методы, сложные блоки) добавлять комментарии на русском языке, а в скобках — английский перевод. Пример:
```python
# Расчёт среднего темпа по сегменту (Calculate average pace for segment)
def calc_avg_pace(...):
```
Это относится ко всем файлам: Python, HTML-шаблоны, конфигурация, SQL и т.д.

**Правила:**
- Каждая `def` (включая вложенные, `__init__`, `_private`) — комментарий выше не более чем в 1 строке
- Каждый `class` — комментарий выше
- Каждый нетривиальный блок (`for`, `if`, `try`) внутри функции — комментарий выше
- `pass`, `return`, простые присваивания, одиночные вызовы — без комментария
- Комментарий не обязателен, если код тривиален и однозначен (например, `return x + 1`)

## Рекомендации по написанию кода (Code Guidelines)

**ВАЖНО: Перед написанием кода прочитай `docs/CODE_GUIDELINES.md`.**

Ключевые правила (кратко):

### Архитектура
- **DRY** — не дублируй код, извлекай в переиспользуемые функции
- **Тонкие роуты** — API endpoint = валидация + вызов сервиса + возврат JSON
- **Доменная группировка** — код группируй по предметной области (`src/services/training/`, `src/services/coros/`)
- **Максимальный размер файла** — ~500 строк, больше — выноси

### Константы
- **Никаких magic numbers** — используй константы из `src.config.constants` или `settings` из `src.config`
- Пример: `from src.config import settings; settings.default_max_hr` вместо `177`
- Пример: `from src.config.constants import HTTP_TIMEOUT` вместо `15`

### API
- **Валидация** — через Pydantic модели (аналог Zod из sample)
- **Response model** — типизируй ответы через `response_model=`
- **Статус-коды** — через `status.HTTP_*`
- **Обработка ошибок** — через `HTTPException` или кастомные исключения из `src/exceptions.py`

### База данных
- **Миграции** — только через Alembic (`alembic revision --autogenerate`)
- **Параметризованные запросы** — никогда не конкатенируй SQL строки
- **Индексы** — добавляй для часто запрашиваемых полей

### Исключения
- **Никогда** `except: pass` — указывай конкретный тип + логируй
- **Централизованная обработка** — через `src/api/middleware.py`
- **User-friendly** сообщения, не stack traces

### Логирование
- **Структурированный логгер** — `src/utils/logger.py`
- **Контекст** — `logger.info(f"Sync completed: {count} activities")`
- **Не логируй** пароли, токены, персональные данные

### Тестирование
- **Unit** — быстрые, с моками, без БД
- **Integration** — с реальной БД (in-memory SQLite)
- **Покрывай** бизнес-логику, edge cases, error paths

### Стиль
- **Комментарии** — bilingual (RU/EN), сразу при написании кода
- **Импорты** — порядок: stdlib → third-party → internal → types
- **Именование** — snake_case для функций/файлов, PascalCase для классов

### Чеклисты
Перед коммитом проверь:
- [ ] Константы из `src.config`, не hardcoded
- [ ] Нет `except: pass`
- [ ] Бизнес-логика в `services/`, не в роуте
- [ ] Тесты написаны
- [ ] CHANGELOG.md обновлён

**Полная документация:** `docs/CODE_GUIDELINES.md`

---

## Администрирование (Admin panel — планируем заранее)

**При проектировании новых эндпоинтов, моделей и сервисов учитывайте будущую панель администрирования (Sprint 7, `TECH_DEBT.md`):**

- Все данные изолируйте по `user_id` — админка будет смотреть данные конкретного пользователя
- Все ключевые события логируйте через `AuditService` — админка читает `audit_events`
- Глобальное состояние (статусы, счётчики) — в БД, не только в памяти процесса (контейнеры `app` и `bot` не разделяют память)
- Модели: оставляйте поля nullable там, где данные могут отсутствовать при создании — админка должна корректно показывать неполные профили
- Роуты: используйте `APIRouter` с префиксами — admin-роуты (`/admin/*`) будут изолированы от пользовательских

**Текущая готовность к админке:**
- ✅ `AuditEvent` + `AuditService` — события пишутся в БД
- ✅ `is_active` на User — базовый ban/unban
- ✅ `get_current_user` (session-cookie) — основа для auth
- ✅ Per-user isolation (`user_id` во всех запросах)
- ✅ Индексы на `audit_events.created_at` и `event_type`
- ⬜ `role` колонка (добавит Sprint 7)
- ⬜ `get_admin_user` dependency (добавит Sprint 7)

---

## GitHub

Репозиторий: https://github.com/KhrenovSS/running-coach
Ветка: `main`

**Правила работы:**
- **Каждый раз после завершения небольшой логически законченной задачи делай commit.** Новый функционал, исправление, рефакторинг — сразу коммит. Не копить изменения.
- Сообщение коммита — кратко, на русском с английским в скобках или просто на английском.
- **В конце сессии:** сделать финальный commit (если остались незакоммиченные изменения) + push в GitHub. Это «итог дня» — вся проделанная работа на GitHub.
- Токен для пуша хранится в `/home/nimda/projects/running-coach/.env` в переменной `GITHUB_TOKEN`. Этот файл в `.gitignore`.
- Команда для пуша (из любой директории):
  ```
  set -a && source /home/nimda/projects/running-coach/.env && set +a && cd /home/nimda/projects/running-coach && git push "https://KhrenovSS:${GITHUB_TOKEN}@github.com/KhrenovSS/running-coach.git" main
  ```
- Перед коммитом проверить `git status`. Исключать из коммитов: `running_coach.db`, `.venv/`, `__pycache__/`, `uploads/` (они в `.gitignore`).
- Не хранить токен, пароли или ключи в исходном коде.
- Email в git config: `khrenov.ss@gmail.com` (привязан к GitHub).
- **Формат коммитов**: сообщение писать на русском с английским переводом в скобках, кратко и по делу. Пример:
  ```
  Fix: rebuild cumulative distance after cleaning; add confirm dialog before saving empty sessions
  ```
  (Английский в заголовке достаточен, но в теле, если нужно, пояснять на двух языках.)

## Ведение истории изменений (Changelog)

**ВАЖНО: запись в CHANGELOG.md писать СРАЗУ в том же коммите, что и изменения кода. Не откладывать на потом и не добвлять отдельным коммитом.**

- Файл `CHANGELOG.md` находится в `/home/nimda/projects/running-coach/CHANGELOG.md`
- Открывать файл, добавлять запись, редактировать код, коммитить — всё в одном шаге
- После каждого значимого изменения (новый функционал, исправление, рефакторинг) обновлять CHANGELOG.md
- Секции: `### Added`, `### Changed`, `### Fixed`, `### Removed`
- **Версии ОБЯЗАТЕЛЬНО датировать по дням: `## [ДД.ММ.ГГГГ]`** (например `## [27.06.2026]`). Не использовать `[Unreleased]` — каждая запись должна иметь конкретную дату
- Запись должна быть краткой, но достаточной для понимания, что именно изменилось

## README.md

- Файл `README.md` в корне проекта (`/home/nimda/projects/running-coach/README.md`)
- При добавлении нового функционала проверять, нужно ли обновить README:
  - Добавить новую возможность в секцию «Основные возможности (Features)»
  - Обновить/добавить скриншоты (лежат в `/home/nimda/projects/running-coach/screenshots/`)
  - Обновить Roadmap (пометить сделанное ✅, если пункт был ⬜)
- README должен отражать актуальное состояние проекта

## Идея проекта (из описания пользователя)
Накопить статистику тренировок, чтобы система сама рекомендовала тренировки, хвалила за успехи, ругала за пропуски, отслеживала прогресс, контролировала восстановление, не давала перетренироваться — как настоящий тренер.

## Завершение сессии (End of session)

- Когда пользователь говорит «На сегодня все» или «продолжим завтра»:
  1. **Обновить секцию «Текущее состояние»** ниже — записать актуальную информацию: состояние сервера, БД, что сделано в этой сессии
  2. **Сделать commit (если есть незакоммиченные изменения) + push** в GitHub. Это «итог дня».
  3. Сообщить пользователю, что изменения сохранены и запушены.

## После внесения изменений (After making changes)

**Важно:** если проект работает в Docker, изменения в коде не применяются автоматически — нужно пересобрать и перезапустить контейнер.

1. **Определить, какие контейнеры нужно пересобрать:**
   - Изменения в `src/`, `main.py`, `pyproject.toml`, шаблонах → пересобрать `app`
   - Изменения в `src/telegram_bot.py` → пересобрать `bot`
   - Изменения в `docker-compose.yml`, `Dockerfile` → пересобрать оба
   - Изменения в миграциях Alembic → `./bin/docker.sh exec app alembic upgrade head`
   - Изменения только в документации (CHANGELOG, AGENTS, README, план) → перезапуск не нужен

2. **Команда для пересборки и перезапуска:**
   ```bash
   ./bin/docker.sh build app    # пересобрать образ app
   ./bin/docker.sh build bot    # пересобрать образ bot
   ./bin/docker.sh up -d        # перезапустить все контейнеры
   ```

3. **Пароль sudo** для `./bin/docker.sh` хранится в `SUDO_PASSWORD` в файле `.env`. Скрипт читает его автоматически — вводить вручную не требуется.

## Текущее состояние (Session — 03.07.2026 — Sprint 6: per-user sync intervals)

**Фаза 3Б (inline-клавиатура оценки) — ✅ выполнено.**
**Sprint 6 (per-user sync intervals) — ✅ выполнено.**

### Что сделано в этой сессии (03.07.2026 — Sprint 6: per-user sync intervals + Оценка тренировки через веб):

1. ✅ **Sprint 6** — per-user sync intervals (6.3–6.9): tick-based scheduler, константы, UI-поля, баннер, Telegram-бот.
2. ✅ **Оценка через веб** — `POST /session/{id}/feedback` + безусловный блок оценки с формой (select 0–10) на странице тренировки.

### Что сделано в этой сессии (02.07.2026 ночь):

1. **🐛 `src/services/sync_service.py:51`**: `save_dashboard_data()` вызывала `client.get_dashboard()` (async корутину) без `await` — падало `'coroutine' object has no attribute 'get'`. Функция сделана `async`, добавлен `await`. Обновлены вызовы в `sync_health_for_user()`.
2. **`src/web/routes/uploads.py`**: добавлен импорт `telegram_notify`. При успешной загрузке TCX/FIT через веб теперь приходит уведомление в Telegram с датой, дистанцией, типом тренировки и именем файла.
3. **`src/telegram_bot.py`**: в уведомление о новой тренировке добавлены дата и время тренировки (ранее было только название + дистанция).
4. **`src/services/sync_service.py`**: в уведомление автосинка добавлена метка времени синхронизации.
5. **Запись в TECH_DEBT.md**: добавлен раздел 🔴 16 (баг save_dashboard_data) и Фаза 3Б — inline-клавиатура оценки 0-10 + отображение рейтинга в веб.
6. **Docker**: пересобраны и перезапущены `app` (3 раза: багфикс, upload уведомления, тест) и `bot` (дата/время в уведомлениях).
7. **Старые процессы убиты**: 2 локальных uvicorn (порты 8005, 8006) на старом монолитном `main.py` остановлены.

### Текущее состояние контейнеров:
```
running-coach-db-1    postgres:16-alpine   Up (healthy)
running-coach-app-1   uvicorn main:app     Up (порт 8000)
running-coach-bot-1   python run_bot()     Up
```

### Развёртывание

### Развёртывание
Docker Compose, 3 контейнера (`db` + `app` + `bot`).

**Команды управления (через `bin/docker.sh`):**
```bash
# Запуск
./bin/docker.sh up -d

# Остановка
./bin/docker.sh down

# Статус
./bin/docker.sh ps

# Логи
sudo docker logs running-coach-app-1 --tail 50
sudo docker logs running-coach-bot-1 --tail 50
sudo docker logs running-coach-db-1 --tail 50
```

**Команда пуша:**
```bash
set -a && source /home/nimda/projects/running-coach/.env && set +a && cd /home/nimda/projects/running-coach && git push "https://KhrenovSS:${GITHUB_TOKEN}@github.com/KhrenovSS/running-coach.git" main
```

**БД:** PostgreSQL 16 (контейнер `running-coach-db-1`), volume `pgdata`.
**Пользователь:** id=1, email=khrenov.ss@gmail.com, WatchCredential пуст — требуется перепривязка Coros через Telegram `/start`.

### Что сделано за сессию 02.07.2026 (вечер):
1. **п.12+14.9**: удалены поля `coros_email`, `coros_password`, `last_coros_sync` из модели `User`. Alembic-миграция `c9d8e7f6a0b2`.
2. **`src/telegram_bot.py`, `src/web/routes/pages.py`**: весь код переведён на `WatchCredential`
3. **Документация**: очищены упоминания `coros_client.py` из AGENTS.md, README.md, docs/ARCHITECTURE.md, docs/TESTING.md
4. **Безопасность**: `.env` — права 600, создан `bin/docker.sh` (права 700) для docker-команд без хранения пароля в истории. `bin/` в `.gitignore`.
5. **AGENTS.md, README.md**: все `sudo docker compose` заменены на `./bin/docker.sh`

### Что сделано за сессию 02.07.2026 (день):
2. **`WatchCredential`** — новая модель в `src/models.py` (таблица `watch_credentials`), Alembic migration `b6c7d8e9f0a1`
3. **`DailyMetrics.source_brand`** — колонка источника метрик
4. **`src/services/sync_service.py`** — brand-agnostic sync (замена `coros_sync_auto.py`)
5. **`src/web/routes/sync.py`** — `/sync/{brand}/run`, `/sync/{brand}/health` (замена `coros.py`)
6. **`src/scheduler.py`** — brand-agnostic
7. **`src/services/audit.py`** — `sync.{brand}.*` события
8. **`src/crypto.py`** — `CRED_KEY` с fallback на `COROS_CRED_KEY`
9. **`src/telegram_bot.py`** — обновлён на `CorosWatchClient` + `WatchCredential`
10. **Старые файлы удалены**: `coros_client.py`, `coros_sync_auto.py`, `web/routes/coros.py`

### Что сделано за сессию 02.07.2026 (день 2 — утро):
1. **🐛 Баг**: lookback-буфер 2ч в `sync_service.py:212` и `telegram_bot.py:460`.
2. **Интервал**: автосинхронизация 60→30 мин (`sync_service.py:27`).
3. **Docker**: пересобраны `app` + `bot`. Миграции `b6c7d8e9f0a1` + `c9d8e7f6a0b2` применены. Alembic downgrade/upgrade — OK.
4. **🐛 Бот падал**: после DROP-миграции контейнер `bot` не пересобран — `UndefinedColumn: coros_email`. Исправлено.
5. **Фаза 4**: добавлена в план — выбор бренда при регистрации, заглушки для Polar/Garmin/Suunto.
6. **WatchCredential пуст**: старые Coros-креды потеряны при миграции.

### Что запланировано на следующие сессии (план работ от 03.07.2026 — переприоритезация):

**Фаза 1 — Добить остатки Sprint 4 + Sprint 4.5:**
- [x] п.12+14.9: удалить поля `coros_email`, `coros_password`, `last_coros_sync` из модели `User`, перенести всё в `WatchCredential`. Alembic-миграция.
- [x] Удалить устаревшие упоминания `coros_client.py` из документации
- [x] Проверить чеклист Sprint 4.5 Фаза 7: Telegram, TCX, Coros sync, `alembic downgrade/upgrade`

**Фаза 3Б ✅ — Inline-клавиатура оценки 0-10 + отображение в веб:**
- [x] 3Б.1 `sync_service.py` — автосинк отправляет каждую тренировку отдельным сообщением с кнопками 0-10
- [x] 3Б.2 `uploads.py` — добавить inline-клавиатуру 0-10 в уведомление
- [x] 3Б.3 `pages.py` — читать TrainingFeedback, передавать rating в шаблон
- [x] 3Б.4 `session.html` — отображать ⭐ Оценка: X/10
- [x] 3Б.5 `index.html` — колонка Оценка в таблице тренировок

**Фаза 2 — Sprint 6: Per-user частота синхронизации ✅:**
- [x] 6.1–6.2: колонки `activity_sync_interval`, `health_sync_interval` в `WatchCredential` (миграция `b6c7d8e9f0a1` уже есть)
- [x] 6.3: константы интервалов в `src/config/constants.py`
- [x] 6.4: индивидуальные интервалы в `sync_service.py` + `scheduler.py` (tick-based)
- [x] 6.5–6.6: UI-поля в настройках (activity + health interval с клипингом)
- [x] 6.7: баннер для новых пользователей на главной
- [x] 6.9: Telegram-бот — сообщение «Бренд Coros подключён!»

**Фаза 3 — Мелкие фичи:**
- [ ] Фильтр по типу тренировки на главной (Все / Бег / Ходьба)
- [ ] Общая дистанция и время за неделю/месяц

**Фаза 4 — Выбор бренда часов при регистрации (Multi-brand onboarding):**
- [ ] Telegram `/start` — после ввода email спрашивать бренд часов (Coros / Polar / Garmin / Suunto)
- [ ] Coros — существующий флоу. Остальные — заглушка «не реализовано»
- [ ] Сохранять бренд в `WatchCredential.brand`, показывать в настройках веб

**❄️ Отложено — Модуль аналитики (8 этапов из `decision_module_design.md`):**
- [ ] Этап 0 — Каркас и данные
- [ ] Этап 1 — Аналитика (Skills) + State Assessor
- [ ] Этап 2 — Движок + безопасность + Recovery Timing
- [ ] Этап 3 — База знаний из литературы
- [ ] Этап 4 — Персонализация и обучение
- [ ] Этап 5 — LLM Coach
- [ ] Этап 6 — Многонедельные планы
- [ ] Этап 7 — Обратная связь и качество

**❄️ Отложено — Sprint 7: Admin panel**

### Известные проблемы:
- DNS: `/etc/resolv.conf` может вернуться на 192.168.1.1 после перезагрузки
- **🐛 Потеря тренировок при задержке Coros API:** `list_activities(since=last_activity_sync_at)` теряет активности, которые Coros обработал с задержкой. Фикс: lookback-буфер (см. TECH_DEBT.md «🐛 Критический баг — Потеря тренировок при задержке Coros API»). Health sync не подвержен — использует окно 120 дней.

### Следующие шаги (по порядку выполнения):
1. ~~**Фаза 1** — остатки Sprint 4 (п.12+14.9) + Sprint 4.5 проверки~~ ✅
2. ~~**🐛 БАГ: Потеря тренировок при задержке Coros API** — lookback-буфер в `sync_activities_for_user()`~~ ✅
3. ~~**Фаза 2** — Sprint 6: per-user частота синхронизации (бренд-независимая), баннер для новых пользователей~~ ✅
4. **Фаза 3** — фильтр по типу тренировки на главной, общая дистанция/время за неделю/месяц
5. **Фаза 4** — выбор бренда часов при регистрации (multi-brand onboarding), заглушки для Polar/Garmin/Suunto
6. **Модуль аналитики** — 8 этапов из `decision_module_design.md`
7. **Sprint 7**: Admin panel

### Команды управления:
```bash
# Запуск (из директории проекта)
./bin/docker.sh up -d

# Остановка
./bin/docker.sh down

# Применить миграции alembic
python3 -m alembic upgrade head

# Проверить статус контейнеров
./bin/docker.sh ps
```

**Если сессия прервана:** перед продолжением работы прочитать:
1. `AGENTS.md` — правила проекта
2. `README.md` — актуальное состояние проекта
