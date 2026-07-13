# AI Running Coach — Персональный AI-тренер для бега

Персональный AI-тренер для бега. Парсит TCX‑ и FIT‑файлы (Garmin, Coros, Polar, Suunto), анализирует тренировки, определяет тип (интервальная/темповая/long/recovery), разбивает на сегменты, считает пульсовые зоны, очищает GPS‑ошибки. Интегрируется с Coros Training Hub для автоматической синхронизации метрик здоровья и тренировок.

---

## 🚀 Основные возможности (Features)

- **📤 Поддержка форматов** – TCX (XML) и FIT (бинарный) от любых часов/приложений
- **🧠 Автоклассификация** – автоматически определяет тип тренировки (интервальная, темповая, long, recovery) по вариативности темпа
- **📊 Сегментация** – каждый километр как отдельный отрезок; для интервальных тренировок – сплит на быстрые/медленные фазы
- **🫀 Пульсовые зоны** – время в зонах Z1–Z5 (на основе max_hr)
- **🗺️ Чистка GPS‑данных** – удаляет скачки и нереальные темпы, пересчитывает дистанцию
- **🌤️ Погода** – температура и иконка погоды для каждой тренировки (Open‑Meteo API)
- **⛰️ Высота** – парсинг набора/спуска (AltitudeMeters)
- **🕐 Часовой пояс** – автоматическое определение по GPS‑координатам
- **📈 Графики** – интерактивный график пульса и темпа (Chart.js)
- **🔄 Интеграция Coros** – автоматическая синхронизация тренировок и метрик здоровья через неофициальное API
- **📱 Telegram‑бот** – регистрация, синхронизация, статистика, ежедневный опрос веса, напоминания
- **⭐ Оценка тренировок** – inline-клавиатура 0–10 в Telegram после каждой синхронизации (авто, ручная, загрузка); отображение оценки в веб-интерфейсе
- **💤 Мониторинг восстановления** – ежедневная проверка данных о сне (10:00 → 18:00 или каждые 2 часа при отсутствии данных)
- **📊 Корректное удаление** – отслеживание удалённых тренировок с подтверждением перед повторной загрузкой
- **🔐 Шифрование** – пароли часов шифруются Fernet‑ключом перед сохранением в БД
- **🔔 Автоматическая синхронизация** – фоновая проверка новых данных по настроенному интервалу для каждого бренда (тренировки + метрики здоровья)
- **🔑 Telegram‑аутентификация** – одноразовые токены для регистрации, bcrypt-хеширование паролей, вход по email+паролю, session-cookie в веб-интерфейсе
- **📝 Структурированное логирование и аудит** – ежедневная ротация, JSON/text формат, запись событий аудита в БД и файл

---

## 🏗️ Архитектура

### Стек
- **Backend**: Python + FastAPI + SQLAlchemy + PostgreSQL 16 (через Docker Compose)
- **Frontend**: HTML/CSS/JS (Vanilla) + Chart.js
- **Парсеры**: `parsers/` — 9 модулей: `common.py` (оркестратор), `tcx_parser.py` (XML), `fit_parser.py` (бинарный), `gps.py` (очистка), `segmentation.py` (change-point detection), `classification.py` (автоопределение типа), `hr_zones.py` (пульсовые зоны), `weather.py` (Open‑Meteo API), `utils.py`
- **Интеграции**: Coros Training Hub (неофициальное API), Open‑Meteo (погода), Telegram Bot API. Мульти-бренд: `BaseWatchClient` ABC + `factory.py` реестр.
- **Аутентификация**: email+пароль (bcrypt), одноразовые токены регистрации (`secrets`), session-cookie (`SessionMiddleware`)
- **Логирование**: структурированное, ежедневная ротация (`TimedRotatingFileHandler`), JSON/text
- **Аудит**: события в БД (`audit_events`) + файл (`logs/audit_*.log`)
- **Планировщик**: `threading.Thread` с jitter (фоновые задачи, автосинхронизация)
- **Шифрование**: Fernet (ключ из окружения)
- **Развёртывание**: Docker Compose — 3 контейнера: `db` (postgres:16-alpine), `app` (uvicorn), `bot` (run_telegram_bot.py)

## 🗄️ Структура базы данных

Проект использует **PostgreSQL 16** (через Docker Compose, контейнер `db`) с управлением схемой через **Alembic** (миграции применяются автоматически при старте контейнера `app`). Для локальной разработки требуется запущенный контейнер PostgreSQL:
```
docker compose up db -d          # Запустить PostgreSQL
DATABASE_URL=postgresql://running_coach:${POSTGRES_PASSWORD}@localhost:5432/running_coach
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Таблицы и схемы (дополнительные)

Помимо перечисленных ниже, в БД есть таблицы:
- **`auth_tokens`** — одноразовые токены входа (Telegram → web). Поля: `id`, `user_id`, `token` (UUID), `expires_at`, `used` (boolean), `created_at`.
- **`audit_events`** — события аудита. Поля: `id`, `user_id`, `event_type`, `details` (JSON), `ip_address`, `created_at`.
- **`watch_credentials`** — учётные данные часов (мульти-бренд). Поля: `id`, `user_id`, `brand`, `encrypted_user`, `encrypted_password`, `access_token`, `token_expires_at`, `last_activity_sync_at`, `last_health_sync_at`, `activity_sync_interval`, `health_sync_interval`, `is_active`.

Также в `daily_metrics` добавлена колонка `sleep_hrv_interval_list` (TEXT, JSON) — интервалы HRV из Coros (минимальное, низкое, норма start, норма end).

#### **`users`** — основной профиль пользователя
```sql
id INTEGER PRIMARY KEY
email VARCHAR(255) UNIQUE             -- Email для входа (login)
password_hash VARCHAR(255)            -- bcrypt-хеш пароля
telegram_chat_id BIGINT UNIQUE          -- ID чата Telegram (для бота)
telegram_username VARCHAR(255)          -- @username пользователя
name VARCHAR(255)                       -- Имя
age INTEGER                             -- Возраст
height_cm INTEGER                       -- Рост (см)
weight_kg FLOAT                         -- Вес (кг)
sport_level VARCHAR(50)                 -- Уровень (beginner/intermediate/advanced)
goal_type VARCHAR(50)                   -- Цель (lose_weight/10k/half_marathon/marathon/general)
goal_target VARCHAR(255)                -- Конкретная цель («sub 60 min 10k»)
max_hr INTEGER DEFAULT 177              -- Максимальный пульс (уд/мин)
max_credible_pace FLOAT DEFAULT 3.0     -- Максимально правдоподобный темп (мин/км)
max_gps_jump_m FLOAT DEFAULT 100.0      -- Макс. скачок GPS между точками (м)
min_hr_for_fast_pace INTEGER DEFAULT 130-- Мин. пульс для быстрого темпа (уд/мин)
timezone VARCHAR(50)                     -- IANA-таймзона пользователя (e.g. "Europe/Moscow")
is_active BOOLEAN DEFAULT TRUE          -- Активен ли пользователь
created_at DATETIME DEFAULT CURRENT_TIMESTAMP
registered_at DATETIME                  -- Дата регистрации
```

#### **`training_sessions`** — тренировки
```sql
id INTEGER PRIMARY KEY
user_id INTEGER FOREIGN KEY(users.id)   -- Связь с пользователем
begin_ts DATETIME DEFAULT CURRENT_TIMESTAMP -- Дата и время начала тренировки
total_distance_km FLOAT                  -- Общая дистанция (км)
avg_heart_rate INTEGER                  -- Средний пульс (уд/мин)
max_heart_rate INTEGER                  -- Максимальный пульс (уд/мин)
training_type VARCHAR(50)               -- Тип: interval/tempo/long/recovery
segments_count INTEGER DEFAULT 1        -- Количество сегментов
duration_minutes FLOAT DEFAULT 0        -- Длительность (минуты)
segments_json JSON DEFAULT []           -- JSON-массив сегментов [{distance, pace, hr, elevation_gain/loss, weather_code, avg_cadence, duration}]
hr_pace_series JSON DEFAULT []          -- Временные ряды пульса и темпа для графика
avg_temperature INTEGER                 -- Средняя температура (°C)
weather_code INTEGER                    -- WMO-код погоды для иконки
elevation_gain INTEGER                  -- Общий набор высоты (м)
elevation_loss INTEGER                  -- Общий спуск (м)
suspect_flags JSON DEFAULT []           -- Флаги сомнительных точек
cleaning_log JSON DEFAULT []            -- Лог очистки GPS-ошибок
avg_cadence INTEGER                     -- Средний каденс (spm)
timezone VARCHAR(50)                     -- IANA-таймзона тренировки (e.g. "Europe/Moscow")
training_effect FLOAT                   -- Аэробный тренировочный эффект (0‑10)
anaerobic_training_effect FLOAT         -- Анаэробный тренировочный эффект (0‑10)
vo2max FLOAT                           -- Макс. потребление кислорода
calories INTEGER                        -- Потраченные калории
```

#### **`daily_metrics`** — ежедневные метрики здоровья (Coros)
```sql
id INTEGER PRIMARY KEY
user_id INTEGER FOREIGN KEY(users.id)
date DATE NOT NULL                     -- Дата метрики
avg_sleep_hrv FLOAT                    -- HRV (SDNN) за сон
sleep_hrv_baseline FLOAT               -- Базовый HRV
sleep_hrv_sd FLOAT                     -- Стандартное отклонение HRV
rhr INTEGER                            -- Пульс покоя (RHR)
tired_rate INTEGER                     -- Усталость (-10…+10)
training_load FLOAT                    -- Тренировочная нагрузка
training_load_ratio FLOAT              -- Отношение нагрузки к норме
performance INTEGER                    -- Эффективность (0‑100)
ati FLOAT                              -- Аэробный тренировочный эффект (ATI)
cti FLOAT                              -- Анаэробный тренировочный эффект (CTI)
vo2max FLOAT                          -- VO₂max
lthr INTEGER                           -- Лактатный порог (ЧСС)
stamina_level FLOAT                    -- Уровень выносливости (stamina)
ltsp FLOAT                             -- Темп лактатного порога (LTSP, мин/км)
stamina_level_7d FLOAT                 -- 7‑дневный тренд выносливости
synced_at DATETIME DEFAULT CURRENT_TIMESTAMP -- Когда метрика синхронизирована
UNIQUE(user_id, date)                  -- Уникальность по дате
```

#### **`deleted_trainings`** — удалённые тренировки (для избежания дублей)
```sql
id INTEGER PRIMARY KEY
user_id INTEGER FOREIGN KEY(users.id)
begin_ts DATETIME NOT NULL             -- Дата тренировки
total_distance_km FLOAT                -- Дистанция (км)
avg_heart_rate INTEGER                 -- Средний пульс
max_heart_rate INTEGER                 -- Макс. пульс
training_type VARCHAR(50)              -- Тип
duration_minutes FLOAT                 -- Длительность
avg_temperature INTEGER                -- Температура
elevation_gain INTEGER                 -- Набор высоты
avg_cadence INTEGER                    -- Каденс
training_effect FLOAT                  -- Training Effect
vo2max FLOAT                          -- VO₂max
calories INTEGER                       -- Калории
avg_pace FLOAT                         -- Средний темп (мин/км)
deleted_at DATETIME DEFAULT CURRENT_TIMESTAMP -- Когда удалена
```

#### **`weight_measurements`** — замеры веса
```sql
id INTEGER PRIMARY KEY
user_id INTEGER FOREIGN KEY(users.id)
weight_kg FLOAT NOT NULL               -- Вес (кг)
measured_at DATETIME DEFAULT CURRENT_TIMESTAMP -- Дата/время замера
```

#### **`watch_credentials`** — учётные данные часов (мульти-бренд)
```sql
id INTEGER PRIMARY KEY
user_id INTEGER FOREIGN KEY(users.id)
brand VARCHAR(50) NOT NULL               -- Бренд часов (coros, polar, garmin, suunto, …)
encrypted_user TEXT                       -- Зашифрованный email/логин
encrypted_password TEXT                   -- Зашифрованный пароль
access_token TEXT                         -- Временный токен доступа (nullable)
token_expires_at DATETIME                 -- Срок токена доступа (nullable)
last_activity_sync_at DATETIME            -- Время последней синхронизации тренировок
last_health_sync_at DATETIME              -- Время последней синхронизации метрик здоровья
activity_sync_interval INTEGER            -- Интервал синхронизации тренировок (мин, nullable)
health_sync_interval INTEGER              -- Интервал синхронизации здоровья (мин, nullable)
is_active BOOLEAN DEFAULT TRUE            -- Активны ли учётные данные
created_at DATETIME
updated_at DATETIME
```

#### **`training_feedback`** — оценка тренировок пользователем
```sql
id INTEGER PRIMARY KEY
session_id INTEGER FOREIGN KEY(training_sessions.id)
user_id INTEGER FOREIGN KEY(users.id)
rating INTEGER NOT NULL                -- Оценка тяжести (0–10)
notes VARCHAR(500)                     -- Комментарий
created_at DATETIME DEFAULT CURRENT_TIMESTAMP
```

### Миграции схемы (Alembic)

Управление схемой БД — через **Alembic**. При старте контейнера `app` выполняется `alembic upgrade head`:

- `f75d2362cf9f` (fresh baseline) — единая database-agnostic миграция: все таблицы
- `a1b2c3d4e5f6` — data migration: конвертация старых naive-local `begin_ts` → naive UTC
- `5e287a9fc289` — convert all DateTime columns to `TIMESTAMP WITH TIME ZONE`
- `b6c7d8e9f0a1` — add `watch_credentials` table, `source_brand` to `daily_metrics`
- `c9d8e7f6a0b2` — remove `coros_email`, `coros_password`, `last_coros_sync` from `users`

Файлы миграций: `alembic/versions/`. Конфигурация: `alembic.ini`, `alembic/env.py` (`DATABASE_URL` из env).

### Отношения (Foreign Keys)
```
users.id ←──────────────────────────────┐
       │                                 │
       ├─ training_sessions.user_id      │
       ├─ daily_metrics.user_id          │
       ├─ weight_measurements.user_id    │
       ├─ deleted_trainings.user_id      │
       └─ watch_credentials.user_id      │
                                         │
training_sessions.id                     │
       │                                 │
       └─ training_feedback.session_id ──┘
```

---

## 📂 Структура проекта

```
running-coach/
├── main.py                          # 7 строк — create_app() + uvicorn.run()
├── run_telegram_bot.py              # Запуск Telegram‑бота
├── bin/
│   └── docker.sh                    # Защищённая обёртка docker compose (права 700, в .gitignore — создать вручную)
├── src/
│   ├── startup.py                   # create_app() фабрика + startup-событие
│   ├── scheduler.py                 # AutoSyncScheduler (одиночка)
│   ├── deps.py                      # Jinja2Templates (общие зависимости)
│   ├── telegram/                     # Пакет Telegram‑бота (handlers, jobs, config, state)
│   │   ├── __init__.py              #   экспорт run_bot
│   │   ├── main.py                   #   run_bot, Application сборка
│   │   ├── config.py                 #   Константы состояний
│   │   ├── state.py                  #   _awaiting_weight
│   │   ├── utils.py                  #   get_user, _get_web_app_url
│   │   ├── sync_runner.py            #   run_sync_in_thread
│   │   ├── handlers/                 #   start, sync, stats, trainings, weight, account, feedback
│   │   └── jobs/                     #   weight, recovery
│   ├── models.py                    # SQLAlchemy‑модели (User, TrainingSession, WatchCredential, …)
│   ├── watch/                       # Мульти-брендовая абстракция часов
│   │   ├── __init__.py              #   register("coros", CorosWatchClient)
│   │   ├── base.py                  #   BaseWatchClient(ABC)
│   │   ├── coros.py                 #   CorosWatchClient на httpx.AsyncClient
│   │   └── factory.py               #   Реестр брендов (register / get_watch_client)
│   ├── crypto.py                    # Шифрование паролей (Fernet, требует CRED_KEY)
│   ├── exceptions.py                # WatchAPIError, WatchAuthError, NotFoundError, …
│   ├── api/
│   │   ├── __init__.py              # re-export: register_middleware, get_db
│   │   ├── deps.py                  # get_current_user dependency (session-cookie)
│   │   ├── middleware.py            # SessionMiddleware, error handlers, request logging
│   │   └── routes/
│   │       ├── auth.py              # /auth/telegram, /auth/login, /auth/register, /auth/logout
│   │       └── health.py            # /health/ endpoint
│   ├── config/
│   │   ├── __init__.py              # Экспортирует settings + constants
│   │   ├── settings.py              # pydantic-settings BaseSettings (env vars)
│   │   └── constants.py             # Плоские module-level константы
│   ├── parsers/
│   │   ├── __init__.py              # реэкспорт process_trackpoints()
│   │   ├── common.py                # Оркестратор: process_trackpoints
│   │   ├── gps.py                   # Очистка GPS‑ошибок, haversine_m
│   │   ├── segmentation.py          # Сегментация по темпу (change-point detection)
│   │   ├── classification.py        # Автоклассификация (interval/tempo/long/recovery)
│   │   ├── hr_zones.py              # Пульсовые зоны Z1–Z5
│   │   ├── weather.py               # Погода (Open‑Meteo API, httpx)
│   │   ├── utils.py                 # format_pace, format_duration, calc_elevation, find_timezone
│   │   ├── tcx_parser.py            # Парсинг TCX (XML)
│   │   └── fit_parser.py            # Парсинг FIT (бинарный)
│   ├── services/
│   │   ├── audit.py                 # AuditService (БД + файл)
│   │   ├── auth.py                  # bcrypt, токены входа
│   │   ├── async_utils.py           # run_async_in_thread(coro)
│   │   ├── sync_service.py          # Brand-agnostic sync (оркестрация + run_sync_for_user)
│   │   ├── watch_credentials.py     # upsert_watch_credential()
│   │   ├── training_service.py      # delete_training(), upsert_feedback()
│   │   ├── stats.py                 # calc_stats, fmt_duration, zone_ranges
│   │   ├── recovery_view.py         # hrv_status, tired_label, readiness_label
│   │   └── telegram_notify.py       # Отправка уведомлений в Telegram
│   ├── web/
│   │   ├── state.py                 # Глобальное состояние (_pending, _sync_tasks)
│   │   ├── templates/               # 6 Jinja2-шаблонов + __init__.py
│   │   └── routes/
│   │       ├── __init__.py          # web_router = pages + uploads + sync + logs
│   │       ├── pages/               # Пакет: auth (48), index (184), session (177), settings (118)
│   │       ├── uploads.py           # POST /upload, /upload/confirm, /upload/confirm_deleted
│   │       ├── sync.py              # POST /sync/{brand}/run, /sync/{brand}/health
│   │       └── logs.py              # GET /logs
│   └── utils/
│       └── logger.py                # Структурированное логирование, ротация
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/                    # Миграции (fresh baseline f75d2362cf9f)
├── docs/                            # 13 документов
│   ├── ARCHITECTURE.md
│   ├── CODE_GUIDELINES.md
│   ├── API_ROUTES_GUIDE.md
│   ├── ERROR_HANDLING.md
│   ├── NAMING_CONVENTIONS.md
│   ├── TESTING.md
│   ├── LOGGING.md
│   ├── DEVELOPMENT_GUIDELINES.md
│   ├── CHECKLIST_API.md
│   ├── CHECKLIST_FEATURE.md
│   ├── CHECKLIST_MIGRATION.md
│   ├── CHECKLIST_NEW_PROVIDER.md    # Чеклист: новый бренд часов
│   └── coros_health_metrics.md
├── tests/                           # Pytest‑тесты
├── uploads/                         # Загруженные файлы (.tcx, .fit)
├── screenshots/                     # Скриншоты интерфейса
├── logs/                            # Ротируемые лог-файлы
├── Dockerfile                       # Python 3.13-slim
├── docker-compose.yml               # 3 сервиса: db, app, bot
├── pyproject.toml                   # Зависимости (version 2.0.0)
├── alembic.ini
├── pytest.ini
├── .env.example                     # Шаблон переменных окружения
├── CHANGELOG.md
├── AGENTS.md                        # Контекст для ИИ‑агента
├── BACKLOG.md                       # Парковка TODO/идей/вопросов
├── PROJECT_AUDIT.md                 # Аудит и план рефакторинга
└── decision_module_design.md        # Архитектура модуля аналитики
```

---

## 🧠 Классификация тренировок

- **Интервальная** – 3+ «вариативных» километров (разница темпа между 200‑метровыми бинами > 1 мин/км)
- **Темповая** – 1–2 вариативных километра
- **Long / Recovery** – 0 вариативных километров (определяется по ЧСС и длительности)

### Сегментация
- Change-point detection: анализ smoothed tempo по всему треку (rolling window 50м)
- Слайдящее окно находит точки смены темпа, пиковая детекция для обработки плато
- Минимальная длина сегмента — 200м
- Fallback: км-блоки (если change-point detection не дал результатов)

---

## 📱 Telegram‑бот

Бот управляется через пакет `src/telegram/`. Запускается в отдельном Docker-контейнере `bot` (см. `docker-compose.yml`). Для локальной разработки — `python run_telegram_bot.py`.

### Доступные команды
- `/start` – регистрация (email + пароль часов, пароль удаляется после ввода) или вход (если уже зарегистрирован)
- `/sync` – полная синхронизация со всеми подключёнными брендами (тренировки + метрики здоровья)
- `/stats` – статистика за всё время и за 7 дней
- `/trainings` – последние 5 тренировок с деталями
- `/weight <кг>` – ручной ввод веса (например, `/weight 75.5`)
- `/login_info` – показать email для входа в веб-интерфейс
- `/reset_password` – сменить пароль (бот показывает 2 сек и удаляет)
- `/delete_me` – удалить все данные пользователя (тренировки, метрики, настройки)

### Обратная связь по тренировкам
- **Оценка 0–10** – пользователь оценивает каждую новую тренировку по шкале сложности
- **Inline‑кнопки** – два ряда (0‑5 и 6‑10) после импорта тренировки
- **Эмодзи‑обратная связь**: 0=😴, 1=😌, 2=🙂, 3=😐, 4=😅, 5=💪, 6=😤, 7=🥵, 8=😵, 9=💀, 10=⚰️
- **Одна оценка на тренировку** – нельзя переоценить после сохранения
- **Уведомления** – при автосинхронизации и ручном `/sync`

### Автоматические напоминания
- **Ежедневный опрос веса** – в 9:00 (python-telegram-bot JobQueue)
- **Проверка данных о сне** – запускается в 10:00:
  - Если данные за последние 12 часов **есть** – следующая проверка в 18:00
  - Если данных **нет** – проверка каждые 2 часа (12:00, 14:00, 16:00, 18:00)
  - Ночью (0:00–8:00) и после 20:00 уведомления **не отправляются** (пользователь спит)
  - При отсутствии данных – сообщение «🌙 Нет данных о восстановлении — используй /sync»
- **Безопасность пароля** – сообщение с паролем Coros автоматически удаляется через 2 секунды

---

## 🔄 Интеграция с часами (Watch Integration)

### Архитектура
Мульти-брендовая абстракция: `BaseWatchClient` (ABC) + `factory.py` (реестр брендов). Currently: `CorosWatchClient`. Adding new brands — см. `docs/CHECKLIST_NEW_PROVIDER.md`.

### Автоматическая синхронизация
- **Тренировки** и **метрики здоровья** — по настроенному интервалу для каждого пользователя (per-user в `WatchCredential`)
- **Jitter ±20%** – чтобы избежать одновременных запросов
- **Graceful error handling** – ошибки API не роняют планировщик

### Метрики здоровья (DailyMetrics)
- **HRV (SDNN)** – вариабельность сердечного ритма за сон
- **RHR** – пульс покоя
- **Tiredness** – уровень усталости (-10…+10)
- **Training Load** – нагрузка (лёгкая/средняя/высокая)
- **Readiness** – готовность к тренировкам (-10…+10)
- **ATI / CTI** – аэробный/анаэробный тренировочный эффект
- **VO₂max** – максимальное потребление кислорода
- **LTHR** – порог лактата (ЧСС)
- **Stamina** – уровень выносливости

### Аналитика (12 недель)
- **VO₂max trend** – тренд VO₂max
- **LTHR trend** – тренд лактатного порога
- **Stamina trend** – тренд выносливости
- **Performance** – общая эффективность

Данные загружаются через эндпоинты `/dashboard/query` и `/analyse/dayDetail/query` (за последние 180 дней, инкрементально).

---

## ⚙️ Настройки

Доступны через веб‑интерфейс (`/settings`) и Telegram‑бота:

- **max_hr** – максимальный пульс (по умолчанию 177 уд/мин)
- **max_credible_pace** – максимально правдоподобный темп (для очистки GPS‑ошибок)
- **max_gps_jump_m** – максимальный скачок GPS между точками
- **min_hr_for_fast_pace** – минимальный пульс для быстрого темпа (проверка правдоподобия)
- **Учётные данные часов** – для каждого подключённого бренда (Coros, Polar, Garmin, …): email/логин + пароль (шифруются Fernet), интервал синхронизации тренировок и здоровья (per-user)

---

## 🚀 Запуск

### Переменные окружения (`.env`)
```
TELEGRAM_BOT_TOKEN=              # Токен бота от @BotFather
SECRET_KEY=                      # Ключ для session-cookie (itsdangerous)
WEB_APP_URL=http://192.168.1.101:8000  # URL веб-приложения для ссылок из бота
CRED_KEY=                          # Ключ шифрования паролей часов (32‑байтовый base64)
# COROS_CRED_KEY=                  # Deprecated, работает как fallback
POSTGRES_PASSWORD=               # Пароль PostgreSQL (для Docker Compose)
DATABASE_URL=                    # postgresql://running_coach:...@db:5432/running_coach
LOG_LEVEL=info                   # Уровень логирования
LOG_FORMAT=text                  # Формат: text или json
LOGS_DIR=logs                    # Папка логов
SLOW_REQUEST_MS=1000            # Порог медленного запроса для лога
GITHUB_TOKEN=                    # Токен для пуша в GitHub
COROS_HEALTH_SYNC_INTERVAL=360  # (Устарело — заменён per-user интервалами в WatchCredential, Sprint 6)
COROS_ACTIVITY_SYNC_INTERVAL=60 # (Устарело — заменён per-user интервалами в WatchCredential, Sprint 6)
```

### Запуск через Docker Compose (рекомендуется)

3 контейнера: `db` (PostgreSQL 16), `app` (FastAPI/uvicorn), `bot` (Telegram-бот).

> **Примечание:** `bin/docker.sh` — защищённая обёртка (права 700, пароль из .env). Не отслеживается git — создать вручную по образцу из `.env.example` или использовать `docker compose` напрямую.

```bash
# Запуск
docker compose up -d

# Остановка
docker compose down

# Статус
docker compose ps

# Логи
docker compose logs app --tail 50
docker compose logs bot --tail 50
docker compose logs db --tail 50
```

Архитектура:
```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   db        │     │   app       │     │   bot       │
│ postgres:16 │◄────│ uvicorn     │     │ python      │
│ alpine      │◄────│ main:app    │     │ run_bot()   │
│ port 5432   │     │ port 8000   │     │             │
└─────────────┘     └─────────────┘     └─────────────┘
     │                   │                   │
     ▼                   │                   │
volume: pgdata      uploads/ logs/      (нет volumes)
```

### Запуск для локальной разработки (без Docker)
```bash
cd /home/nimda/projects/running-coach

# Веб-сервер (требуется запущенный PostgreSQL через docker compose up db -d)
DATABASE_URL=postgresql://running_coach:${POSTGRES_PASSWORD}@localhost:5432/running_coach uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Telegram-бот (отдельный терминал)
python run_telegram_bot.py
```

---

## 📈 Roadmap

### ✅ Сделано
- [x] Парсинг TCX/FIT, классификация, сегментация
- [x] Пульсовые зоны, высота, погода, часовой пояс
- [x] Очистка GPS‑ошибок, подтверждение сомнительных тренировок
- [x] График пульса/темпа (Chart.js)
- [x] Интеграция с Coros (автосинхронизация тренировок)
- [x] Метрики здоровья (HRV, RHR, tiredness, readiness, нагрузка)
- [x] Telegram‑бот (регистрация, синхронизация, статистика, ежедневный вес)
- [x] Проверка данных о сне (10:00 → 18:00 / каждые 2 часа)
- [x] Шифрование паролей часов (Fernet)
- [x] Отслеживание удалённых тренировок (избежание дублирования)
- [x] Миграции схемы БД через Alembic (автоматически при старте)
- [x] Структурированное логирование и аудит
- [x] Аутентификация: email+пароль (bcrypt), Telegram-токены, session-cookie
- [x] PostgreSQL + Docker Compose (3 контейнера: db, app, bot)
- [x] Мульти-брендовая архитектура (`BaseWatchClient`, `WatchCredential`, `factory.py`)
- [x] Оценка тренировок 0–10 (Telegram inline + веб-форма)
- [x] Per-user интервалы синхронизации
- [x] Рефакторинг: main.py 2776→7, parsers разбиты на 9 модулей, telegram разбит на 12 файлов, тонкие роуты

### ⬜ Запланировано
- [ ] Тесты (минимум 20, реальные TCX/FIT-файлы)
- [ ] Разбивка models.py + sync_service.py на пакеты
- [ ] Фильтр по типу тренировки, общая дистанция/время за неделю/месяц
- [ ] Multi-brand onboarding (выбор бренда при регистрации)
- [ ] Факторы самочувствия после тренировки
- [ ] Панель администрирования
- [ ] Модуль аналитики и рекомендаций (8 этапов, `decision_module_design.md`)

---

## 🧠 План развития: модуль аналитики и рекомендаций

Главное направление развития проекта — **модуль аналитики и рекомендаций**: после каждой
тренировки анализировать её в контексте истории, восстановления и литературы, рекомендовать
**какую** следующую тренировку провести и **когда**. Полная архитектура и обоснование —
в `decision_module_design.md`.

**Ключевые идеи:**
- LLM — интерфейс общения, а не источник решений; решения принимает детерминированное ядро.
- Литература дистиллируется **офлайн** в тематические руководства (`knowledge/guides/*.md`) —
  книга анализируется один раз, дальше движок читает компактные правила.
- Система **обучается**: цикл «прогноз → факт → расхождение → разбор причины → калибровка».
  «Неожиданно тяжёлые» тренировки детектируются и разбираются (с уточнением причины у пользователя).

### Поэтапный план (по `decision_module_design.md`, раздел 12)

- [ ] **Этап 0 — Каркас и данные.** Пакет `src/coach/`, новые таблицы (`Recommendation`,
  `PredictionLog`, `UserModel`, `Lesson`), `config.py`, фикстуры для тестов.
- [ ] **Этап 1 — Аналитика (Skills) + State Assessor.** Перенос порогов из
  `docs/coros_health_metrics.md` в код (fatigue / load / recovery / distribution / progress /
  workout), сборка состояния `AthleteState`, команда `/state`.
- [ ] **Этап 2 — Движок + безопасность (P1) + Recovery Timing (P2).** 8 IF‑THEN правил,
  оценка времени до восстановления, команда `/recommend` (что + когда + причина).
- [ ] **Этап 3 — База знаний из литературы.** Офлайн‑пайплайн `knowledge/distill.py`
  (книга → `guides/*.md` с YAML‑правилами + проза), правила тренировочной логики (80/20, 3:1).
- [ ] **Этап 4 — Персонализация и обучение.** Персональная модель, прогноз тяжести/HR/нагрузки,
  калибровка по факту, детект «неожиданно тяжело» с уточнением причины в Telegram и «уроками».
- [ ] **Этап 5 — LLM Coach.** Обёртка над LLM, объяснение рекомендаций, RAG по руководствам
  для свободных вопросов в чате.
- [ ] **Этап 6 — Многонедельные планы.** Генерация плана под цель (10k / half / marathon),
  цикл 3:1, подводка, адаптация при отклонениях. Команда `/plan`.
- [ ] **Этап 7 — Обратная связь и качество.** Метрики точности прогнозов, доля принятых
  рекомендаций, отчёты прогресса (похвала / предупреждение), переключение наборов правил (A/B).

### Связанные пункты (войдут в этапы выше)
- [ ] Training Status / Running Efficiency (расчётные метрики) → Этап 1
- [ ] AI‑рекомендации (8 IF‑THEN правил из `docs/coros_health_metrics.md`) → Этап 2
- [ ] Прогноз восстановления (на основе HRV‑тренда) → Этап 2
- [ ] Уведомления о прогрессе (похвала / ругань) → Этап 7

---

## 🧹 Технический долг

> Полный список технического долга, план рефакторинга и статус спринтов — в [`PROJECT_AUDIT.md`](PROJECT_AUDIT.md).

---

## 📄 Лицензия

Проект разрабатывается как open‑source инструмент для личного использования. Используйте на свой страх и риск.

---

## 🐛 Отладка

### Логи
Структурированные логи с ежедневной ротацией (`logs/app_YYYY-MM-DD.log`, `logs/audit_YYYY-MM-DD.log`).
Просмотр последних 100 строк:
```bash
tail -n 100 logs/app_$(date +%F).log
```

Через веб‑интерфейс: `/logs?lines=100`

Формат (text/json) и уровень логирования настраиваются через `.env`:
```
LOG_LEVEL=info
LOG_FORMAT=text     # или json
LOGS_DIR=logs
```

### Очистка БД (PostgreSQL в Docker)
```bash
# Остановить контейнеры
docker compose down

# Удалить volume с данными PostgreSQL
sudo docker volume rm running-coach_pgdata

# Запустить заново (БД создастся с нуля)
docker compose up -d
```

---

## 🔗 Ссылки
- **GitHub**: https://github.com/KhrenovSS/running-coach
- **Coros Training Hub**: https://training.coros.com/
- **Open‑Meteo**: https://open-meteo.com/
- **Telegram Bot API**: https://core.telegram.org/bots/api

---

*Последнее обновление: 13.07.2026 — Фаза D: документация (BACKLOG, чеклисты, AGENTS, README актуализированы)*