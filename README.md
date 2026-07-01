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
- **💤 Мониторинг восстановления** – ежедневная проверка данных о сне (10:00 → 18:00 или каждые 2 часа при отсутствии данных)
- **📊 Корректное удаление** – отслеживание удалённых тренировок с подтверждением перед повторной загрузкой
- **🔐 Шифрование** – пароли Coros шифруются Fernet‑ключом перед сохранением в БД
- **🔔 Автоматическая синхронизация** – фоновая проверка новых данных каждые 1 час (тренировки) и 6 часов (метрики здоровья)
- **🔑 Telegram‑аутентификация** – одноразовые токены для регистрации, bcrypt-хеширование паролей, вход по email+паролю, session-cookie в веб-интерфейсе
- **📝 Структурированное логирование и аудит** – ежедневная ротация, JSON/text формат, запись событий аудита в БД и файл

---

## 🏗️ Архитектура

### Стек
- **Backend**: Python + FastAPI + SQLAlchemy + SQLite
- **Frontend**: HTML/CSS/JS (Vanilla) + Chart.js
- **Парсеры**: `parsers/tcx_parser.py` (XML), `parsers/fit_parser.py` (бинарный), `parsers/common.py` (общая обработка)
- **Интеграции**: Coros Training Hub (неофициальное API), Open‑Meteo (погода), Telegram Bot API
- **Аутентификация**: email+пароль (bcrypt), одноразовые токены регистрации (`secrets`), session-cookie (`SessionMiddleware`)
- **Логирование**: структурированное, ежедневная ротация (`TimedRotatingFileHandler`), JSON/text
- **Аудит**: события в БД (`audit_events`) + файл (`logs/audit_*.log`)
- **Планировщик**: `threading.Thread` с jitter (фоновые задачи, автосинхронизация)
- **Шифрование**: Fernet (ключ из окружения)

## 🗄️ Структура базы данных

Проект использует SQLite (`running_coach.db`) с управлением схемой через **Alembic** (миграции применяются автоматически при старте сервера).

### Таблицы и схемы (дополнительные)

Помимо перечисленных ниже, в БД есть таблицы:
- **`auth_tokens`** — одноразовые токены входа (Telegram → web). Поля: `id`, `user_id`, `token` (UUID), `expires_at`, `used` (boolean), `created_at`.
- **`audit_events`** — события аудита. Поля: `id`, `user_id`, `event_type`, `details` (JSON), `ip_address`, `created_at`.

Также в `daily_metrics` добавлена колонка `sleep_hrv_interval_list` (TEXT, JSON) — интервалы HRV из Coros (минимальное, низкое, норма start, норма end).

#### **`users`** — основной профиль пользователя
```sql
id INTEGER PRIMARY KEY
telegram_chat_id BIGINT UNIQUE          -- ID чата Telegram (для бота)
telegram_username VARCHAR(255)          -- @username пользователя
name VARCHAR(255)                       -- Имя
age INTEGER                             -- Возраст
height_cm INTEGER                       -- Рост (см)
weight_kg FLOAT                         -- Вес (кг)
sport_level VARCHAR(50)                 -- Уровень (beginner/intermediate/advanced)
goal_type VARCHAR(50)                   -- Цель (lose_weight/10k/half_marathon/marathon/general)
goal_target VARCHAR(255)                -- Конкретная цель («sub 60 min 10k»)
coros_email VARCHAR(255)                -- Email для Coros Training Hub
coros_password VARCHAR(255)             -- Пароль Coros (шифрованный Fernet)
last_coros_sync DATETIME                -- Время последней синхронизации с Coros
max_hr INTEGER DEFAULT 177              -- Максимальный пульс (уд/мин)
max_credible_pace FLOAT DEFAULT 3.0     -- Максимально правдоподобный темп (мин/км)
max_gps_jump_m FLOAT DEFAULT 100.0      -- Макс. скачок GPS между точками (м)
min_hr_for_fast_pace INTEGER DEFAULT 130-- Мин. пульс для быстрого темпа (уд/мин)
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

Управление схемой БД — через **Alembic**. При старте сервера выполняется `alembic upgrade head`:

- `c3f51ae84837` (baseline) — индексы `ix_*_user_id` + unique constraint `uq_user_date` на `daily_metrics`
- `0bba2c2badec` — удалена таблица `user_settings` (настройки перенесены в `users`)
- `eb50c256201f` — добавлена таблица `audit_events`
- `69f28e182276` — добавлена таблица `auth_tokens`

Файлы миграций: `alembic/versions/`. Конфигурация: `alembic.ini`, `alembic/env.py` (`render_as_batch=True` для совместимости с SQLite).

### Отношения (Foreign Keys)
```
users.id ←──────────────────────────────┐
       │                                 │
       ├─ training_sessions.user_id      │
       ├─ daily_metrics.user_id          │
       ├─ weight_measurements.user_id    │
       └─ deleted_trainings.user_id      │
                                          │
training_sessions.id                     │
       │                                 │
       └─ training_feedback.session_id ──┘
```

---

## 📂 Структура проекта

```
/home/nimda/projects/running-coach/
├── main.py                          # FastAPI‑роуты, HTML‑шаблоны, планировщик автосинхронизации
├── src/
│   ├── telegram_bot.py              # Telegram‑бот (регистрация, sync, stats, daily weight)
│   ├── models.py                    # SQLAlchemy‑модели (User, TrainingSession, DailyMetrics, …)
│   ├── coros_client.py              # Клиент для неофициального Coros API
│   ├── crypto.py                    # Шифрование паролей Coros (Fernet)
│   ├── exceptions.py                # Типизированные исключения приложения
│   ├── logger.py                    # re-export → src.utils.logger (обратная совместимость)
│   ├── api/
│   │   ├── __init__.py              # re-export: register_middleware, get_db
│   │   ├── deps.py                  # get_current_user dependency (session-cookie)
│   │   ├── middleware.py            # SessionMiddleware, error handlers, request logging
│   │   └── routes/
│   │       ├── auth.py              # /auth/telegram, /auth/login, /auth/register, /auth/logout
│   │       └── health.py            # /health/ endpoint
│   ├── config/
│   │   ├── __init__.py
│   │   └── constants.py             # Централизованный CONFIG
│   ├── parsers/
│   │   ├── common.py                # Очистка треков, сегментация, классификация, погода
│   │   ├── tcx_parser.py            # Парсинг TCX‑файлов (XML)
│   │   └── fit_parser.py            # Парсинг FIT‑файлов (бинарный)
│   ├── services/
│   │   ├── audit.py                 # AuditService (события в БД + файл)
│   │   └── auth.py                  # Генерация/верификация токенов входа
│   └── utils/
│       └── logger.py                # Структурированное логирование, ежедневная ротация
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/                    # Миграции (c3f51ae8, 0bba2c2b, eb50c256, 69f28e18)
├── docs/
│   ├── ARCHITECTURE.md
│   ├── CODE_GUIDELINES.md
│   ├── API_ROUTES_GUIDE.md
│   ├── ERROR_HANDLING.md
│   ├── NAMING_CONVENTIONS.md
│   ├── TESTING.md
│   ├── LOGGING.md
│   ├── CHECKLIST_API.md
│   ├── CHECKLIST_FEATURE.md
│   ├── CHECKLIST_MIGRATION.md
│   ├── coros_health_metrics.md
│   └── DEVELOPMENT_GUIDELINES.md
├── tests/                           # Pytest‑тесты
├── uploads/                         # Временные загруженные файлы (.tcx, .fit)
├── logs/                            # Ротируемые лог-файлы
│   ├── app_YYYY-MM-DD.log
│   └── audit_YYYY-MM-DD.log
├── running_coach.db                 # SQLite‑база данных
├── pyproject.toml                   # Манифест зависимостей
├── alembic.ini                      # Конфигурация Alembic
├── pytest.ini                       # Конфигурация pytest
├── .env                             # Переменные окружения (в .gitignore)
├── .env.example                     # Шаблон переменных окружения
├── running-coach-web.service        # systemd-юнит веб-сервера
├── running-coach-bot.service        # systemd-юнит Telegram-бота
├── CHANGELOG.md                     # История изменений (датированная)
├── AGENTS.md                        # Контекст для ИИ‑агента
├── TECH_DEBT.md                     # Технический долг и план исправления
└── decision_module_design.md        # Архитектура модуля аналитики
```

---

## 🧠 Классификация тренировок

- **Интервальная** – 3+ «вариативных» километров (разница темпа между 200‑метровыми бинами > 1 мин/км)
- **Темповая** – 1–2 вариативных километра
- **Long / Recovery** – 0 вариативных километров (определяется по ЧСС и длительности)

### Сегментация
- По умолчанию – каждый километр = отдельный сегмент (км‑блоки)
- Для интервальных тренировок – сплит вариативных километров на быстрый/медленный сегмент
- Минимальная длина сегмента – 200 м

---

## 📱 Telegram‑бот

Бот управляется через `/src/telegram_bot.py`. Запускается как отдельный процесс при старте сервера.

### Доступные команды
- `/start` – регистрация (Coros email + пароль, пароль удаляется после ввода)
- `/sync` – полная синхронизация с Coros (тренировки + метрики здоровья)
- `/stats` – статистика за всё время и за 7 дней
- `/trainings` – последние 5 тренировок с деталями
- `/weight <кг>` – ручной ввод веса (например, `/weight 75.5`)
- `/delete_me` – удалить все данные пользователя (тренировки, метрики, настройки)

### Обратная связь по тренировкам
- **Оценка 0–10** – пользователь оценивает каждую новую тренировку по шкале сложности
- **Inline‑кнопки** – два ряда (0‑5 и 6‑10) после импорта тренировки
- **Эмодзи‑обратная связь**: 0=😴, 1=😌, 2=🙂, 3=😐, 4=😅, 5=💪, 6=😤, 7=🥵, 8=😵, 9=💀, 10=⚰️
- **Одна оценка на тренировку** – нельзя переоценить после сохранения
- **Уведомления** – при автосинхронизации и ручном `/sync`

### Автоматические напоминания
- **Ежедневный опрос веса** – в 9:00 (APScheduler)
- **Проверка данных о сне** – запускается в 10:00:
  - Если данные за последние 12 часов **есть** – следующая проверка в 18:00
  - Если данных **нет** – проверка каждые 2 часа (12:00, 14:00, 16:00, 18:00)
  - Ночью (0:00–8:00) и после 20:00 уведомления **не отправляются** (пользователь спит)
  - При отсутствии данных – сообщение «🌙 Нет данных о восстановлении — используй /sync»
- **Безопасность пароля** – сообщение с паролем Coros автоматически удаляется через 2 секунды

---

## 🔄 Интеграция с Coros

### Автоматическая синхронизация
- **Тренировки** – каждые ~60 минут (настраивается через `COROS_ACTIVITY_SYNC_INTERVAL`)
- **Метрики здоровья** – каждые ~6 часов (настраивается через `COROS_HEALTH_SYNC_INTERVAL`)
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
- **coros_email / coros_password** – учётные данные Coros (шифруются Fernet‑ключом)
- **last_coros_sync** – время последней синхронизации с Coros

---

## 🚀 Запуск

### Предварительные требования
```bash
pip install fastapi uvicorn sqlalchemy python-telegram-bot[job-queue] fitdecode timezonefinder openmeteo-requests requests fernet
```

### Переменные окружения (`.env`)
```
TELEGRAM_BOT_TOKEN=              # Токен бота от @BotFather
SECRET_KEY=                      # Ключ для session-cookie (itsdangerous)
WEB_APP_URL=http://192.168.1.101:8000  # URL веб-приложения для ссылок из бота
COROS_CRED_KEY=                  # Ключ шифрования паролей Coros (32‑байтовый base64)
LOG_LEVEL=info                   # Уровень логирования
LOG_FORMAT=text                  # Формат: text или json
LOGS_DIR=logs                    # Папка логов
SLOW_REQUEST_MS=1000            # Порог медленного запроса для лога
GITHUB_TOKEN=                    # Токен для пуша в GitHub
COROS_HEALTH_SYNC_INTERVAL=360  # Интервал синхронизации метрик здоровья (мин)
COROS_ACTIVITY_SYNC_INTERVAL=60 # Интервал синхронизации тренировок (мин)
```

### Запуск сервера
```bash
cd /home/nimda/projects/running-coach
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Запуск как служба systemd (рекомендуется)
Сервер и Telegram-бот работают как отдельные systemd-сервисы с автоматическим перезапуском.

Файлы юнитов лежат в корне проекта и копируются в `~/.config/systemd/user/`:

```bash
cp running-coach-web.service ~/.config/systemd/user/running-coach.service
cp running-coach-bot.service ~/.config/systemd/user/

systemctl --user daemon-reload

# Веб-сервер
systemctl --user enable running-coach.service
systemctl --user start running-coach.service

# Telegram-бот (отдельный процесс, Restart=on-failure)
systemctl --user enable running-coach-bot.service
systemctl --user start running-coach-bot.service
```

### Команды управления
```bash
systemctl --user start/stop/status/restart running-coach.service      # веб-сервер
systemctl --user start/stop/status/restart running-coach-bot.service  # Telegram-бот
```

### Запуск вручную (без systemd)
```bash
cd /home/nimda/projects/running-coach

# Веб-сервер
uvicorn main:app --host 0.0.0.0 --port 8000

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
- [x] Метрики здоровья Coros (HRV, RHR, tiredness, readiness, нагрузка)
- [x] Telegram‑бот (регистрация, синхронизация, статистика, ежедневный вес)
- [x] Проверка данных о сне (10:00 → 18:00 / каждые 2 часа)
- [x] Шифрование паролей Coros (Fernet)
- [x] Отслеживание удалённых тренировок (избежание дублирования)
- [x] Миграции схемы БД через Alembic (автоматически при старте)
- [x] Структурированное логирование и аудит (Level 2 observability)
- [x] Аутентификация через Telegram-бота для веб-интерфейса

### ⬜ Прочие планы (UI / интеграции)
- [ ] Фильтр по типу тренировки на главной (Все / Бег / Ходьба)
- [ ] Общая дистанция и время за неделю/месяц
- [ ] Мобильное PWA (Progressive Web App)

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

---

## 🧹 Технический долг

> **Анализ проекта выполнен моделью Cloud Opus 4.8 (29.06.2026).**

Перед разработкой модуля аналитики и рекомендаций необходимо устранить накопившийся
технический долг — иначе новый модуль не сможет нормально развиваться (блокировки SQLite,
расхождение настроек между веб и ботом, невозможность писать тесты на формулы).

Полное руководство по исправлению — в **[`TECH_DEBT.md`](TECH_DEBT.md)** (для каждой
проблемы: где она, в чём состоит, почему это плохо, как починить, как проверить).

**Краткий список (по приоритету):**

🔴 **Критично — блокирует модуль рекомендаций:**
- Монолитный `main.py` на ~2650 строк (роуты + HTML + логика + планировщик в одном файле).
- ~~Веб захардкожен на одного пользователя (`_current_user_id = 1`), без аутентификации.~~ → ✅ решено: Telegram-аутентификация, session-cookie, `get_current_user` Depends

🟠 **Серьёзно — мешает развитию:**
- Путаница UTC vs локальное время в `DateTime`-полях.

🟡 **Средне — техдолг:**
- Inline-HTML на f-строках (~94 места), нужен Jinja2.
- Coros-клиент на синхронном `requests`, без TTL токена.
- Конфигурация разбросана; ключ шифрования автогенерируется в `.env`.

✅ **Решено (Sprint 1–2 + Sprint 2.4–2.5 + hotfix):**
- ~~Telegram-бот запускался через `subprocess.Popen` из `main.py` — при падении не перезапускался, а перезапуск веба убивал бота.~~ → Вынесен в отдельный systemd-юнит `running-coach-bot.service` с `Restart=on-failure`
- ~~Два источника правды для настроек: `UserSettings` (веб) vs `User` (бот).~~ → модель `UserSettings` удалена, всё на `User`
- ~~SQLite без WAL и `check_same_thread=False`~~ → WAL включён, `busy_timeout=5000`, `pool_pre_ping=True`
- ~~Ручные `ALTER TABLE` в `startup()`~~ → Alembic внедрён, 4 миграции
- ~~Нет тестов и манифеста зависимостей~~ → `pyproject.toml`, `tests/` (3 теста моделей)
- ~~23 места с `except Exception: pass`~~ → заменены на явные типы с логгированием
- ~~Ручное управление сессиями БД в эндпоинтах~~ → `get_db()` через `Depends` в 9 эндпоинтах
- ~~Бот запускается как subprocess с подавленным выводом~~ → `DEVNULL` убран, вывод в journal
- ~~Нет структурированного логирования~~ → `src/utils/logger.py` с ежедневной ротацией, JSON/text
- ~~Нет аудита событий~~ → `AuditService`, таблица `audit_events`, покрытие всех ключевых операций

Рекомендуемый порядок исправлений (4 спринта) описан в `TECH_DEBT.md` → раздел «Порядок работ».

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

### Остановка сервера
```bash
pkill -9 -f "uvicorn main"
```

### Очистка БД
```bash
# 1. Остановить сервер
pkill -9 -f "uvicorn main"

# 2. Удалить файл БД
rm running_coach.db

# 3. Запустить сервер заново
uvicorn main:app --host 0.0.0.0 --port 8000
```

---

## 🔗 Ссылки
- **GitHub**: https://github.com/KhrenovSS/running-coach
- **Coros Training Hub**: https://training.coros.com/
- **Open‑Meteo**: https://open-meteo.com/
- **Telegram Bot API**: https://core.telegram.org/bots/api

---

*Последнее обновление: 01.07.2026*