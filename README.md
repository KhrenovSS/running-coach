# AI Running Coach — Персональный AI-тренер для бега

Персональный AI-тренер для бега. Парсит TCX‑ и FIT‑файлы (Garmin, Coros, Polar, Suunto), анализирует тренировки, определяет тип (интервальная/темповая/long/recovery), разбивает на сегменты, считает пульсовые зоны, очищает GPS‑ошибки. Интегрируется с Coros Training Hub для автоматической синхронизации метрик здоровья и тренировок.

---

## 🚀 Основные возможности (Features)

- **📤 Поддержка форматов** – TCX (XML) и FIT (бинарный) от любых часов/приложений
- **🧠 Автоклассификация** – автоматически определяет тип тренировки (интервальная, темповая, long, recovery) по вариативности темпа и осцилляциям
- **🔄 Пересчёт тренировок** – ручная смена типа (interval/tempo/long/recovery/easy) + автоматический пересчёт анализа из сохранённых трекпоинтов
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
- **🤖 ИИ-коуч (гибрид)** – LLM рассуждает и предлагает тренировку, детерминированная граница
  безопасности урезает всё рискованное (числа в карточке — только из кода): утренний вердикт
  (09:30), разбор тренировки, свободный чат в Telegram, команда `/verdict`
- **🦵 Трекинг боли** – после оценки RPE бот спрашивает про колено (2–3 тапа: уровень + фаза
  «старт/середина/конец/после»); вечерний опрос самочувствия в 21:00; боль ≥5/10 автоматически
  запрещает тренировку на день

---

## 🏗️ Архитектура

### Стек
- **Backend**: Python + FastAPI + SQLAlchemy + PostgreSQL 16 (через Docker Compose)
- **Frontend**: HTML/CSS/JS (Vanilla) + Chart.js
- **Анализ**: `src/analysis/` — пакет анализа (7 файлов): `__init__.py` (оркестратор process_trackpoints), `oscillation.py` (детекция интервалов: base_pace + pace_gap + HR-lag), `classify.py` (interval/tempo/long/recovery/easy), `segment.py` (change-point detection + осцилляции), `segment_km.py` (km-fallback, вариативность), `hr_zones.py` (пульсовые зоны Z1–Z5), `utils.py`
- **Парсеры**: `src/parsers/` — `tcx_parser.py` (XML), `fit_parser.py` (бинарный), `gps.py` (очистка GPS), `weather.py` (Open-Meteo API, httpx)
- **Интеграции**: Coros Training Hub (неофициальное API), Open‑Meteo (погода), Telegram Bot API. Мульти-бренд: `BaseWatchClient` ABC + `factory.py` реестр.
- **Аутентификация**: email+пароль (bcrypt), одноразовые токены регистрации (`secrets`), session-cookie (`SessionMiddleware`)
- **Логирование**: структурированное, ежедневная ротация (`TimedRotatingFileHandler`), JSON/text
- **Аудит**: события в БД (`audit_events`) + файл (`logs/audit_*.log`)
- **Планировщик**: `threading.Thread` с jitter (фоновые задачи, автосинхронизация)
- **Шифрование**: Fernet (ключ из окружения)
- **ИИ-коуч**: `src/coach/` — скиллы/граница безопасности/tools/LLM-слой (`anthropic==1.0.0`);
  LLM-бэкенды: API-ключ → **мост через подписку Claude Code** (`bin/coach_llm_bridge.py`,
  systemd, :8765) → детерминированный fallback. Карта модулей: `docs/coach/ARCHITECTURE.md`
- **Развёртывание**: Docker Compose — 3 контейнера: `db` (postgres:16-alpine), `app` (uvicorn),
  `bot` (run_telegram_bot.py) + systemd-юнит `running-coach-llm-bridge.service` на хосте

## 🗄️ Структура базы данных

Проект использует **PostgreSQL 16** (через Docker Compose, контейнер `db`) с управлением схемой через **Alembic** (миграции применяются автоматически при старте контейнера `app`). Для локальной разработки требуется запущенный контейнер PostgreSQL:
```
docker compose up db -d          # Запустить PostgreSQL
DATABASE_URL=postgresql://running_coach:${POSTGRES_PASSWORD}@localhost:5432/running_coach
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Таблицы и схемы (дополнительные)

Помимо перечисленных ниже, в БД есть таблицы:
- **`auth_tokens`** — одноразовые токены входа (Telegram → web). Поля: `id`, `user_id`, `token` (String(64), генерируется через `secrets.token_urlsafe`), `expires_at`, `used_at` (DateTime, nullable), `created_at`.
- **`audit_events`** — события аудита. Поля: `id`, `user_id`, `event_type`, `metadata_json` (JSON), `severity` (String), `message` (Text), `ip_address`, `created_at`.
- **`watch_credentials`** — учётные данные часов (мульти-бренд). Поля: `id`, `user_id`, `brand`, `encrypted_user`, `encrypted_password`, `access_token`, `token_expires_at`, `last_activity_sync_at`, `last_health_sync_at`, `activity_sync_interval`, `health_sync_interval`, `is_active`.

- **Таблицы коуча** (миграции `j3k4l5m6n7o8` + `p9q0r1s2t3u4`): `recommendations` (назначения:
  тип/цель/объём/rationale + наблюдаемость `proposal_json`/`safety_json`/`clamped`/`source`),
  `prediction_logs` (прогноз vs факт, UNIQUE по session_id), `user_models` (персональные параметры,
  1 строка/юзер), `lessons` (извлечённые уроки), `coach_messages` (история диалога + токены/стоимость
  LLM), `wellness_reports` (вечерний самоотчёт: боль/крепатура/настроение/сон, UNIQUE user+date).
- В `training_feedback` добавлены колонки боли: `pain_level` (0–10), `pain_location`, `pain_phase`
  (start/middle/end/after/none).

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
interval_pace_threshold FLOAT             -- Порог темпа: разница с базовым (мин/км, default 1.0)
interval_min_phase_duration INTEGER       -- Мин. длительность фазы (сек, default 15)
interval_hr_lag_sec INTEGER               -- Лаг пульса (сек, default 5)
interval_min_oscillations INTEGER         -- Мин. число осцилляций для interval (default 3)
is_active BOOLEAN DEFAULT TRUE          -- Активен ли пользователь
created_at DATETIME DEFAULT CURRENT_TIMESTAMP
registered_at DATETIME                  -- Дата регистрации
last_health_sync_at DATETIME            -- Время последней синхронизации метрик здоровья
```

#### **`training_sessions`** — тренировки
```sql
id INTEGER PRIMARY KEY
user_id INTEGER FOREIGN KEY(users.id)   -- Связь с пользователем
begin_ts DATETIME DEFAULT CURRENT_TIMESTAMP -- Дата и время начала тренировки
total_distance_km FLOAT                  -- Общая дистанция (км)
avg_heart_rate INTEGER                  -- Средний пульс (уд/мин)
max_heart_rate INTEGER                  -- Максимальный пульс (уд/мин)
training_type VARCHAR(50)               -- Тип: interval/tempo/long/recovery/easy
training_type_override VARCHAR(50)      -- Ручная установка типа (NULL = автоопределение)
trackpoints_json JSON                   -- Сырые трекпоинты для пересчёта (reanalyze)
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
avg_pace FLOAT                          -- Средний темп (мин/км)
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
recovery_pct INTEGER                    -- Восстановление Coros (%)
form_score FLOAT                        -- Базовая форма Coros
load_impact FLOAT                       -- Влияние нагрузки Coros
intensity_trend FLOAT                   -- Тренд интенсивности Coros
sleep_hrv_interval_list JSON            -- Интервалы HRV из Coros (минимальное, низкое, норма start, норма end)
source_brand VARCHAR(50)                -- Бренд-источник метрики (coros, polar, …)
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
encrypted_user VARCHAR(255)               -- Зашифрованный email/логин
encrypted_password VARCHAR(255)           -- Зашифрованный пароль
access_token VARCHAR(512)                 -- Временный токен доступа (nullable)
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

Управление схемой БД — через **Alembic**. При старте контейнера `app` выполняется
`alembic upgrade head`. Полный и всегда актуальный список — файлы в `alembic/versions/`
(порядок задаёт цепочка `down_revision`); ключевые вехи:

- `f75d2362cf9f` — fresh baseline: все таблицы одной database-agnostic миграцией
- `g9h0i1j2k3l4` — analytics preparation: индексы, `avg_pace`, `performance`
- `j3k4l5m6n7o8` — 4 таблицы модуля коуча (recommendations, prediction_logs, user_models, lessons)
- `m6n7o8p9q0r1`/`n7o8p9q0r1s2` — честный дедуп (`external_activity_id`) + сырые FIT/TCX
- `o8p9q0r1s2t3` — адаптивный max_hr (`hr_peak_smoothed`)
- `p9q0r1s2t3u4` — **текущий head**: боль (`training_feedback.pain_*`), `wellness_reports`,
  `coach_messages`, наблюдаемость решений в `recommendations`

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
├── bin/                             # Ops-скрипты + рантайм-компоненты хоста
│   ├── docker.sh                    # Защищённая обёртка docker compose (права 700, создать вручную)
│   ├── backup_db.sh                 # Бэкап БД (обязателен перед деплоем)
│   ├── backfill_*.py                # Разовые backfill-скрипты
│   └── coach_llm_bridge.py          # LLM-мост коуча (headless Claude Code по подписке, systemd :8765)
├── running-coach-*.service          # systemd-юниты: bot, web, llm-bridge
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
│   │   ├── handlers/                 #   start, sync, stats, trainings, weight, account, feedback,
│   │   │                             #   coach (/verdict, /coach_settings, роутер текста), pain, hr_max
│   │   └── jobs/                     #   weight, recovery, hr_max, coach_morning (09:30), coach_evening (21:00)
│   ├── models.py                    # Shim: реэкспорт из src/domain/models/ + хелперы
│   ├── domain/
│   │   └── models/                  # Доменные модели (User, TrainingSession, WatchCredential, …)
│   │       ├── __init__.py          #   реэкспорт всех моделей
│   │       ├── base.py              #   Base, utcnow, get_engine, SessionLocal, get_db, init_db
│   │       ├── user.py              #   User
│   │       ├── training.py          #   TrainingSession, TrainingFeedback, DeletedTraining
│   │       ├── watch.py             #   WatchCredential
│   │       ├── health.py            #   DailyMetrics, WeightMeasurement, WellnessReport
│   │       ├── coach.py             #   Recommendation, PredictionLog, UserModel, Lesson, CoachMessage
│   │       ├── auth.py              #   AuthToken
│   │       └── audit.py             #   AuditEvent
│   ├── watch/                       # Мульти-брендовая абстракция часов
│   │   ├── __init__.py              #   register("coros", CorosWatchClient)
│   │   ├── base.py                  #   BaseWatchClient(ABC)
│   │   ├── coros.py                 #   CorosWatchClient на httpx.AsyncClient
│   │   └── factory.py               #   Реестр брендов (register / get_watch_client)
│   ├── crypto.py                    # Шифрование паролей (Fernet, требует CRED_KEY)
│   ├── exceptions.py                # WatchAPIError, NotFoundError, …; CoachError → LLMUnavailable/ToolExecution
│   ├── coach/                       # Гибридный ИИ-коуч (полная карта — docs/coach/ARCHITECTURE.md)
│   │   ├── config.py                #   пороги/веса (единственный исполняемый источник)
│   │   ├── contracts.py / state.py  #   контракты + сборка AthleteState
│   │   ├── rules/p1_safety.py + safety.py  # граница безопасности (clamp)
│   │   ├── prescriber / render / fallback / orchestrator / util
│   │   ├── skills/                  #   fatigue, recovery, load, distribution, progress, pain, workout
│   │   ├── tools/                   #   7 read-only tools для LLM
│   │   ├── knowledge/guides/        #   методические руководства (loader + 4 seed)
│   │   └── llm/                     #   CoachLLM: anthropic / bridge (мост подписки) / null + agent
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
│   ├── analysis/                    # Пакет анализа тренировок
│   │   ├── __init__.py              #   оркестратор process_trackpoints()
│   │   ├── oscillation.py           #   детекция интервалов: base_pace + pace_gap + HR-lag
│   │   ├── classify.py              #   классификация (interval/tempo/long/recovery/easy)
│   │   ├── segment.py               #   сегментация: change-point detection + осцилляции
│   │   ├── segment_km.py            #   km-fallback, вариативность
│   │   ├── hr_zones.py              #   пульсовые зоны Z1–Z5
│   │   └── utils.py                 #   format_pace, haversine_m, calc_elevation
│   ├── parsers/
│   │   ├── __init__.py              #   (очищен)
│   │   ├── gps.py                   #   Очистка GPS‑ошибок, haversine_m
│   │   ├── weather.py               #   Погода (Open‑Meteo API, httpx)
│   │   ├── tcx_parser.py            #   Парсинг TCX (XML)
│   │   └── fit_parser.py            #   Парсинг FIT (бинарный)
│   ├── services/
│   │   ├── audit.py                 # AuditService (БД + файл)
│   │   ├── auth.py                  # bcrypt, токены входа
│   │   ├── async_utils.py           # run_async_in_thread(coro)
│   │   ├── sync/                    # Пакет синхронизации
│   │   │   ├── __init__.py          #   реэкспорт (run_sync_for_user, etc.)
│   │   │   ├── utils.py             #   SYNC_TICK_INTERVAL, интервалы, _make_client
│   │   │   ├── health.py            #   save_dashboard_data, sync_health_for_user
│   │   │   ├── activities.py        #   sync_activities_for_user
│   │   │   └── orchestrator.py      #   run_sync_for_user, auto_sync_health, auto_sync_activities
│   │   ├── sync_service.py          # Shim: DeprecationWarning (обратная совместимость)
│   │   ├── watch_credentials.py     # upsert_watch_credential()
│   │   ├── training_service.py      #   delete_training(), upsert_feedback()
│   │   ├── reanalyze.py             #   пересчёт тренировок из trackpoints_json
│   │   ├── stats.py                 #   calc_stats, fmt_duration, zone_ranges
│   │   ├── recovery_view.py         # hrv_status, tired_label, readiness_label
│   │   ├── telegram_notify.py       # Отправка уведомлений в Telegram
│   │   ├── user_service.py          # get_user_settings, get_or_create_user_by_telegram
│   │   ├── analytics_helpers.py     # compute_slope, compute_ewma, moving average
│   │   ├── repositories.py          # TrainingRepository, HealthRepository, FeedbackRepository
│   │   ├── repositories_coach.py    # CoachRepository: выборки для коуча, честный ACWR, coach_messages
│   │   ├── hr_max.py                # Адаптивный max_hr (пики/снижение)
│   │   ├── raw_files.py             # Хранилище исходных FIT/TCX (uploads/raw/)
│   │   └── weight_service.py        # save_weight, current_weight
│   ├── web/
│   │   ├── state.py                 # Глобальное состояние (_pending, _sync_tasks)
│   │   ├── templates/               # 6 Jinja2-шаблонов + __init__.py
│   │   └── routes/
│   │       ├── __init__.py          # web_router = pages + uploads + sync + logs
│   │       ├── pages/               # Пакет: auth (48), index (240), session (191), settings (149)
│   │       │   ├── auth.py          #   GET /login, /register
│   │       │   ├── index.py         #   GET / — главная страница
│   │       │   ├── session.py       #   GET /session/{id}, POST /session/{id}/delete, /session/{id}/feedback, /session/{id}/reanalyze
│   │       │   └── settings.py      #   GET /settings, POST /settings
│   │       ├── uploads.py           # POST /upload, /upload/confirm, /upload/confirm_deleted
│   │       ├── sync.py              # POST /sync/{brand}/run, /sync/{brand}/health, GET /sync/status/{task_id}; legacy /coros/sync*
│   │       └── logs.py              # GET /logs
│   └── utils/
│       ├── logger.py                # Структурированное логирование, ротация
│       └── rate_limit.py            # In-memory rate limiter (Sprint 13)
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/                    # Миграции (fresh baseline f75d2362cf9f)
├── docs/                            # Документация (см. таблицу в CLAUDE.md)
│   ├── coach/                       #   DEV_PLAN.md (нормативный план) + ARCHITECTURE.md (ADR коуча)
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
└── decision_module_design.md        # SUPERSEDED — историческая деривация (норматив: docs/coach/DEV_PLAN.md)
```

---

## 🧠 Классификация тренировок

- **Интервальная** – 3+ вариативных километров ИЛИ 3+ work→recovery циклов (темп ≥ 1 мин/км быстрее среднего)
- **Темповая** – 1–2 вариативных километра
- **Long / Recovery** – 0 вариативных километров (определяется по ЧСС и длительности)

### Детекция интервалов (новый алгоритм)
- **Base pace** = средний темп всей пробежки (разминка + заминка учитываются)
- **Work threshold** = base_pace − pace_gap (по умолчанию 1:00 мин/км)
- Участки с темпом < threshold → work-фаза (ускорение)
- Recovery = темп вернулся к среднему
- HR-lag корреляция: пульс растёт через 5 сек после ускорения = подтверждение интервала

### Сегментация
- Change-point detection: анализ smoothed tempo по всему треку (rolling window 50м)
- Слайдящее окно находит точки смены темпа, пиковая детекция для обработки плато
- Минимальная длина сегмента — 200м
- Fallback: осцилляции → км-блоки

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
- `/verdict` – вердикт коуча по запросу: состояние + назначение тренировки через границу безопасности
- `/coach_settings` – уровень инициативы коуча (🔕 выкл / 🔈 минимум / 🔔 обычная / 📣 максимум)
- `/delete_me` – удалить все данные пользователя; `/delete_me_confirm` – подтверждение (5 минут)
- `/cancel` – отмена текущего диалога (ConversationHandler)

**Свободный текст** (не команда) — чат с ИИ-коучем: вопросы о состоянии, самочувствии,
плане («что мне сегодня делать?»). Лимит 40 LLM-ходов/день; без LLM-бэкенда бот отвечает
детерминированной карточкой состояния.

### Обратная связь по тренировкам
- **Оценка 0–10** – пользователь оценивает каждую новую тренировку по шкале сложности
- **Inline‑кнопки** – два ряда (0‑5 и 6‑10) после импорта тренировки
- **Эмодзи‑обратная связь**: 0=😴, 1=😌, 2=🙂, 3=😐, 4=😅, 5=💪, 6=😤, 7=🥵, 8=😵, 9=💀, 10=⚰️
- **Боль (колено)** – после тапа RPE то же сообщение спрашивает «Колено?»
  (🚫 не беспокоило / 🟡 немного / 🔴 мешало), при боли — фаза (старт/середина/конец/после).
  Хороший день = 2 тапа. Боль ≥5/10 → коуч назначает отдых (граница безопасности).
- **Одна оценка на тренировку** – нельзя переоценить после сохранения
- **Уведомления** – при автосинхронизации и ручном `/sync`

### Автоматические напоминания
- **Ежедневный опрос веса** – в 9:00, 12:00, 15:00, 18:00 (python-telegram-bot JobQueue; если вес уже введён за сегодня — пропускается)
- **Проверка данных о сне** – запускается в 10:00:
  - Если данные за последние 12 часов **есть** – следующая проверка в 18:00
  - Если данных **нет** – проверка каждые 2 часа (12:00, 14:00, 16:00, 18:00)
  - Ночью (0:00–8:00) и после 20:00 уведомления **не отправляются** (пользователь спит)
  - При отсутствии данных – сообщение «🌙 Нет данных о восстановлении — используй /sync»
- **Утренний вердикт коуча** – 09:30 (гейт: инициатива «обычная» или «максимум»);
  состояние + назначение тренировки, LLM-проза при доступном бэкенде
- **Вечерний вопрос о самочувствии** – 21:00 (только «максимум»): «Колено сегодня?»
  → wellness_reports; пропускается, если боль уже записана из тренировки
- **Разбор тренировки** – после каждой синхронизации новой тренировки (гейт: инициатива ≠ выкл)
- **Еженедельная проверка max_hr** – понедельник 10:05 (предложение снизить, кулдаун 30 дней)
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

### Метрики здоровья — аналитические тренды (частично в коуче; развитие — C8+, docs/coach/DEV_PLAN.md)

> ⚠️ **Не реализовано.** Generic-хелперы трендов (slope, EWMA, MA) есть в `analytics_helpers.py`, но конкретные расчёты VO₂max/LTHR/Stamina/Performance trend не реализованы. Тренды VO2max/веса/темпа уже считает скилл `progress` (`src/coach/skills/progress.py`); выделенные веб-графики трендов — в рамках C8+ (`docs/coach/DEV_PLAN.md`).

Данные для расчётов загружаются через внешние эндпоинты Coros API `/dashboard/query` и `/analyse/dayDetail/query` (за последние 180 дней, инкрементально).

---

## ⚙️ Настройки

Доступны через веб‑интерфейс (`/settings`) и Telegram‑бота:

- **max_hr** – максимальный пульс (по умолчанию 177уд/мин)
- **max_credible_pace** – максимально правдоподобный темп (для очистки GPS‑ошибок)
- **max_gps_jump_m** – максимальный скачок GPS между точками
- **min_hr_for_fast_pace** – минимальный пульс для быстрого темпа (проверка правдоподобия)
- **Порог ускорения (interval_pace_threshold)** – разница с базовым темпом (по умолчанию 1:00 мин/км). Участки быстрее = work‑фаза (интервал).
- **Мин. длительность фазы (interval_min_phase_duration)** – минимум 15 сек (по умолчанию)
- **Лаг пульса (interval_hr_lag_sec)** – задержка пульса после смены темпа (по умолчанию 5 сек)
- **Мин. число осцилляций (interval_min_oscillations)** – циклов work→recovery для interval (по умолчанию 3)
- **Учётные данные часов** – для каждого подключённого бренда (Coros, Polar, Garmin, …): email/логин + пароль (шифруются Fernet), интервал синхронизации тренировок и здоровья (per‑user)

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
SUDO_PASSWORD=                   # Для bin/backup_db.sh и docker-обёртки (только локально)
RAW_FILES_DIR=uploads/raw        # Хранилище исходных FIT/TCX

# --- ИИ-коуч ---
COACH_ENABLED=true               # Рубильник коуча (свободный чат + проактивность)
ANTHROPIC_API_KEY=               # API-ключ (пусто = ключа нет; тогда работает мост или fallback)
COACH_LLM_MODEL=claude-opus-5    # Модель API-режима
COACH_LLM_EFFORT=low             # Глубина рассуждений API-режима
COACH_LLM_BRIDGE_URL=            # URL LLM-моста (http://host.docker.internal:8765) — прод сейчас
COACH_LLM_BRIDGE_TOKEN=          # Токен моста (совпадает с .env.bridge)
```

Отдельный **`.env.bridge`** (только на хосте, вне git) — конфиг systemd-юнита моста:
`COACH_LLM_BRIDGE_TOKEN`, `BRIDGE_MODEL` (по умолчанию `sonnet`), `BRIDGE_TIMEOUT`,
опционально `CLAUDE_CODE_OAUTH_TOKEN` (от `claude setup-token`).

### Настройки `settings.py` (pydantic-settings, читаются из env)

| Настройка | По умолчанию | Описание |
|-----------|-------------|----------|
| `default_max_hr` | `177` | Максимальный пульс по умолчанию (уд/мин) |
| `http_timeout` | `15` | Таймаут HTTP-запросов (сек) |
| `timezone` | `UTC` | Часовой пояс по умолчанию |
| `session_ttl_days` | `7` | Время жизни session-cookie (дни) |
| `token_ttl_minutes` | `30` | Время жизни одноразового токена входа (мин) |
| `password_min_length` | `6` | Минимальная длина пароля |
| `slow_request_ms` | `1000` | Порог медленного запроса (мс) |
| `web_app_url` | `""` | URL веб-приложения для CSRF и ссылок из бота |
| `log_file` | `app.log` | Имя лог-файла |
| `raw_files_dir` | `uploads/raw` | Хранилище исходных FIT/TCX |
| `coach_enabled` | `True` | Рубильник коуча |
| `anthropic_api_key` | `""` | API-ключ Anthropic (пусто = API-режим выключен) |
| `coach_llm_model` | `claude-opus-5` | Модель API-режима |
| `coach_llm_effort` | `low` | Глубина рассуждений API-режима |
| `coach_llm_bridge_url` | `""` | URL LLM-моста (пусто = мост выключен) |
| `coach_llm_bridge_token` | `""` | Токен LLM-моста |

### Запуск через Docker Compose (рекомендуется)

3 контейнера: `db` (PostgreSQL 16), `app` (FastAPI/uvicorn), `bot` (Telegram-бот).
LLM-часть коуча дополнительно требует host-сервис — см. «Системные сервисы (systemd)» ниже.

## 🖥️ Системные сервисы (systemd)

В корне репозитория — три юнита (копируются в `/etc/systemd/system/`):

| Юнит | Что делает |
|---|---|
| `running-coach-web.service` | Веб-приложение без Docker (legacy-вариант запуска) |
| `running-coach-bot.service` | Telegram-бот без Docker (legacy-вариант запуска) |
| `running-coach-llm-bridge.service` | **LLM-мост коуча** (прод): uvicorn `bin/coach_llm_bridge.py` на :8765, headless Claude Code по подписке; конфиг — `EnvironmentFile=.env.bridge` |

Мост обязателен для LLM-части коуча в текущей конфигурации (API-ключа нет). Управление:
`sudo systemctl {status|restart} running-coach-llm-bridge`. Правка `bin/coach_llm_bridge.py`
или `.env.bridge` требует только рестарта юнита, не пересборки контейнеров.

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
- [x] Рефакторинг: main.py 2776→7, parsers разбиты на 5 файлов (tcx, fit, gps, weather + __init__), telegram разбит на пакет handlers/jobs, тонкие роуты
- [x] Пакет `src/analysis/` — модуль анализа тренировок (классификация, сегментация, осцилляции, HR-зоны)
- [x] Новый алгоритм детекции интервалов: base_pace + pace_gap + HR-lag корреляция
- [x] Пересчёт тренировок (`POST /session/{id}/reanalyze`) с ручной сменой типа
- [x] Хранение трекпоинтов (`trackpoints_json`) для повторного анализа

### ⬜ Запланировано
- [x] Тесты (полный набор, реальные TCX/FIT-фикстуры; зелёный без сети и API-ключа)
- [x] Разбивка models.py + sync_service.py на пакеты
- [ ] Фильтр по типу тренировки, общая дистанция/время за неделю/месяц
- [ ] Multi-brand onboarding (выбор бренда при регистрации)
- [~] Факторы самочувствия — частично в коуче (wellness_reports: боль/крепатура/настроение/сон); полный multi-select — BACKLOG #12
- [ ] Панель администрирования
- [x] Гибридный ИИ-коуч — **в проде** (C0–C7, деплой 23.08.2026); осталось C8/C9 — см. [`docs/coach/DEV_PLAN.md`](docs/coach/DEV_PLAN.md)

---

## 🧠 Гибридный ИИ-коуч (в проде с 23.08.2026)

**Работает**: LLM рассуждает и предлагает тренировки, детерминированные скиллы поставляют факты
(read-only tools), слой безопасности — непробиваемый фильтр поверх (числа для пользователя всегда
рендерятся детерминированно). Реализовано C0–C7: скиллы, граница (clamp), Telegram-интеграция,
tools, LLM-мост через подписку Claude Code, утренний вердикт и сбор боли. Открыты C8 (LLM-разбор
тренировки + недельный отчёт) и C9 (сверка документации).

> **Единственный нормативный план разработки — [`docs/coach/DEV_PLAN.md`](docs/coach/DEV_PLAN.md)**
> (инварианты, чек-листы C0–C9, статусы). Дорожная карта здесь не дублируется.
> Прежний дизайн «движок правил решает всё» (`decision_module_design.md`) — SUPERSEDED, сохранён как
> историческая деривация порогов и скиллов.

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
tail -n 100 logs/app.log.$(date +%F)
```

Через веб‑интерфейс: `/logs?lines=100`

Формат (text/json) и уровень логирования настраиваются через `.env`:
```
LOG_LEVEL=info
LOG_FORMAT=text     # или json
LOGS_DIR=logs
```

> ⚠️ **ВАЖНО: Не удаляйте volume с данными PostgreSQL!**
> Команды `docker compose down -v` или `docker volume rm running-coach_pgdata` удалят **ВСЕ данные** (тренировки, пользователей, настройки).
>
> Безопасные команды:
> - Перезапуск: `docker compose restart app`
> - Пересборка: `docker compose build app && docker compose up -d app`
> - Бэкап перед деплоем: `bin/backup_db.sh`

---

## 🔗 Ссылки
- **GitHub**: https://github.com/KhrenovSS/running-coach
- **Coros Training Hub**: https://training.coros.com/
- **Open‑Meteo**: https://open-meteo.com/
- **Telegram Bot API**: https://core.telegram.org/bots/api

---

*Последнее обновление: 16.07.2026 — Docs audit: исправлены migration order, users schema, weight schedule, analytics section; добавлены /cancel, undocumented routes*