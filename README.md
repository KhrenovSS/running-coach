# AI Running Coach — Персональный AI-тренер для бега

Персональный AI-тренер для бега. Парсит TCX‑ и FIT‑файлы (Garmin, Coros, Polar, Suunto), анализирует тренировки, определяет тип (интервальная/темповая/long/recovery), разбивает на сегменты, считает пульсовые зоны, очищает GPS‑ошибки. Интегрируется с Coros Training Hub для автоматической синхронизации метрик здоровья и тренировок.

---

## 🚀 Основные возможности (Features)

- **📤 Поддержка форматов** – TCX (XML) и FIT (бинарный) от любых часов/приложений
- **🧠 Автоклассификация** – автоматически определяет тип тренировки (интервальная, темповая, long, recovery) по вариативности темпа и осцилляциям
- **🔄 Пересчёт тренировок** – ручная смена типа (interval/tempo/long/recovery/easy) + автоматический пересчёт от сырого FIT/TCX (fallback — сохранённые трекпоинты)
- **📊 Сегментация** – каждый километр как отдельный отрезок; для интервальных тренировок – сплит на быстрые/медленные фазы
- **🫀 Пульсовые зоны** – время в зонах Z1–Z5 от ПАНО (LTHR, лестница 81/89/100/105%), fallback — %max_hr
- **🗺️ Чистка GPS‑данных** – удаляет скачки и нереальные темпы, пересчитывает дистанцию; + квалиметрия GPS: при недостоверном треке дистанция оценивается по шагам (каденс × длина шага)
- **📦 Парсер FIT v2** – лапы часов (laps_json), паузы записи и эталоны session-сообщения (device_summary), каналы динамики (power/stance/oscillation/step_length)
- **🔍 Кросс-чек с часами** – расхождение с эталонами устройства (device_mismatch) и лапами (lap_check)
- **⏱️ HRR-разбор интервалов** – восстановление пульса между повторами
- **📅 Мониторинг недели** – структура качественных дней, downhill-нагрузка, детренированность, session-RPE
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
- **🏃 Тренировки по сегментам (M2.1)** – назначение раскладывается на сегменты с конкретными,
  считываемыми с часов метриками (пульсовые потолки из зон, ориентир темпа из истории, критерии
  восстановления «до пульса ≤X, или N мин, или N км»); общий итог времени считается из сегментов;
  где темпа мало — честная пометка / цель «по ощущениям» (`segments.py`/`render_segments.py`)
- **🛡️ Устойчивость к сбою LLM-моста** – ретрай транзиентных ошибок (502/timeout), при недоступности
  моста утренний вердикт остаётся детерминированным со назначением + отложенный upgrade-повтор
- **🦵 Трекинг боли** – после оценки RPE бот спрашивает про колено (2–3 тапа: уровень + фаза
  «старт/середина/конец/после»); вечерний опрос самочувствия в 21:00; боль ≥5/10 автоматически
  запрещает тренировку на день

---

## 🏗️ Архитектура

### Стек
- **Backend**: Python + FastAPI + SQLAlchemy + PostgreSQL 16 (через Docker Compose)
- **Frontend**: HTML/CSS/JS (Vanilla) + Chart.js
- **Анализ**: `src/analysis/` — пакет анализа (15 модулей): `__init__.py` (оркестратор process_trackpoints), `oscillation.py` (детекция интервалов: base_pace + pace_gap + HR-lag), `classify.py` (interval/tempo/long/recovery/easy), `segment.py` (change-point detection + осцилляции), `segment_km.py` (km-fallback, вариативность), `hr_zones.py` (зоны от LTHR c fallback %max_hr: get_zone/get_band/zone_bounds/zone_ceiling_hr), `gap.py` (GAP/Minetti + downhill_block), `effort.py` (кардиодрейф/HR-стабильность), `hr_baseline.py` (базовая линия HR↔темп), `session_metrics.py` (метрики M1 разбора), `gps_quality.py` (квалиметрия GPS + оценка по шагам), `data_checks.py` (кросс-чеки с часами), `intervals.py` (HRR интервалов), `week_structure.py` (структура недели/детренированность), `utils.py`
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
  LLM), `wellness_reports` (вечерний самоотчёт: боль/крепатура/настроение/сон, UNIQUE user+date),
  `workout_insights` (очередь + итог разбора тренировки, `computed_json` schema v7, миграция `q0r1s2t3u4v5`).
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
hr_peak_smoothed INTEGER                -- Сглаженный пик пульса (для адаптивного max_hr)
external_activity_id VARCHAR(64)        -- ID активности у провайдера (честный дедуп)
source_brand VARCHAR(50)                -- Бренд-источник (coros, polar, …)
file_sha256 VARCHAR(64)                 -- SHA-256 исходного файла
raw_file_path VARCHAR(255)              -- Путь к сырому FIT/TCX (uploads/raw/)
gps_quality JSON                        -- Квалиметрия GPS (достоверность трека, оценка по шагам)
laps_json JSON                          -- Лапы часов (из FIT)
device_summary JSON                     -- Эталоны session-сообщения + паузы записи (из FIT)
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
sleep_duration_min INTEGER              -- Сон из скриншота (#257): общая длительность, мин
sleep_deep_min / sleep_rem_min / sleep_light_min / sleep_awake_min INTEGER  -- фазы, мин (если экран показывает)
sleep_score INTEGER                     -- оценка сна 0-100 (если есть на экране)
sleep_extra JSON                        -- гибкие метрики Coros: deep_pct/rem_pct/sleep_stress/bedtime_offset_min/note
sleep_source VARCHAR(30)                -- 'coros_screenshot' (источник данных сна)
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
- `p9q0r1s2t3u4` — боль (`training_feedback.pain_*`), `wellness_reports`,
  `coach_messages`, наблюдаемость решений в `recommendations`
- `q0r1s2t3u4v5` (workout_insights) → `r1s2t3u4v5w6` (сон из скриншота, `sleep_*` в daily_metrics)
  → `s2t3u4v5w6x7` (sleep_extra) → `t3u4v5w6x7y8` (gps_quality)
  → `u4v5w6x7y8z9` — **текущий head** (laps_json/device_summary)

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

Полное дерево `src/` с назначением каждого модуля, правила размещения кода и потоки данных —
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (единственное место, где оно ведётся). Верхний уровень:

| Путь | Что |
|---|---|
| `main.py`, `run_telegram_bot.py` | точки входа веб (`create_app()`) и бота |
| `src/api/`, `src/web/` | тонкие роуты: auth/health и Jinja2-страницы, загрузка, синк, логи |
| `src/services/` | бизнес-логика (плоские модули + пакет `sync/`) |
| `src/domain/models/` | SQLAlchemy-модели по доменам; `alembic/` — миграции |
| `src/parsers/`, `src/analysis/` | TCX/FIT, GPS/погода; классификация, сегменты, зоны, метрики разбора |
| `src/watch/` | клиенты часов (`BaseWatchClient` + реестр брендов) |
| `src/telegram/` | бот: handlers/, jobs/ |
| `src/coach/` | гибридный ИИ-коуч — [`docs/coach/ARCHITECTURE.md`](docs/coach/ARCHITECTURE.md) |
| `bin/` | ops: бэкап, backfill, LLM-мост (`coach_llm_bridge.py`, systemd) |
| `tests/` | pytest (SQLite in-memory; opt-in PostgreSQL) — [`docs/TESTING.md`](docs/TESTING.md) |
| `docs/` | документация — индекс в [`CLAUDE.md`](CLAUDE.md); `docs/archive/` — исторические документы |

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
- `/plan` – составить/пересоставить план тренировок на неделю (или фраза «перепланируй»); среди недели — остаток текущей
- `/week` – показать сохранённый план недели (прошедшие дни — факт ✓/✗)
- `/report` – итоги недели (пн–сегодня): проза тренера + карточка чисел «Итоги недели» (в вс 19:00 приходит сам, затем план следующей недели)
- `/sleep` – попросить прислать скриншот экрана сна (данные сна вводятся картинкой; фото распознаёт vision-мост, скриншот удаляется из чата)
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

### Метрики здоровья — аналитические тренды (частично в коуче)

> ⚠️ **Частично.** LTHR/LTSP используются (зоны и нормативные темпы, F4/M3.1); не реализованы веб-графики трендов VO₂max/Stamina/Performance. Generic-хелперы трендов (slope, EWMA, MA) есть в `analytics_helpers.py`; тренды VO2max/веса/темпа уже считает скилл `progress` (`src/coach/skills/progress.py`); выделенные веб-графики трендов не планируются (BACKLOG).

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

## 📈 Статус и дорожная карта

Всё перечисленное в «Возможностях» выше — в проде, включая гибридный ИИ-коуч (с 23.08.2026:
утренний вердикт, разбор тренировки, недельный план и отчёт, сон из скриншота, метрики разбора
insights v7). Нормативная дорожная карта коуча и статусы — [`docs/coach/DEV_PLAN.md`](docs/coach/DEV_PLAN.md);
открытые задачи и идеи (фильтры на главной, multi-brand onboarding, панель администратора, PWA) —
[`BACKLOG.md`](BACKLOG.md). Дорожная карта в README не дублируется.

---

## 🧹 Технический долг

> Открытые пункты — [`BACKLOG.md`](BACKLOG.md); закрытые — `docs/archive/BACKLOG_closed.md`.

---

## 📄 Лицензия

Проект разрабатывается как open‑source инструмент для личного использования. Используйте на свой страх и риск.

---

## 🐛 Отладка

### Логи
Структурированные логи с ежедневной ротацией: `logs/app.log`, `logs/requests.log`, `logs/audit.log`
(ротированные файлы — `app.log.YYYY-MM-DD` и т.д.).
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

*Последнее обновление: 01.09.2026 — синхронизация с кодом: тренировки по сегментам (M2.1), устойчивость к сбою LLM-моста, F-серия «сырые данные и физиология» (см. выше)*