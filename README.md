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

---

## 🏗️ Архитектура

### Стек
- **Backend**: Python + FastAPI + SQLAlchemy + SQLite
- **Frontend**: HTML/CSS/JS (Vanilla) + Chart.js
- **Парсеры**: `tcx_parser.py` (XML), `fit_parser.py` (бинарный), `common.py` (общая обработка)
- **Интеграции**: Coros Training Hub (неофициальное API), Open‑Meteo (погода), Telegram Bot API
- **Планировщик**: APScheduler (фоновые задачи, автосинхронизация)
- **Шифрование**: Fernet (ключ из окружения)

## 🗄️ Структура базы данных

Проект использует SQLite (`running_coach.db`) с автоматической миграцией (ALTER TABLE при старте сервера).

### Таблицы и схемы

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

#### **`user_settings`** — **DEPRECATED** (настройки перенесены в `users`)

### Автомиграция (Auto‑migration)
При старте сервера (`init_db()` в `models.py`) проверяется наличие таблиц и добавляются отсутствующие колонки через `ALTER TABLE`:
- `weather_code`, `avg_cadence`, `training_effect`, `vo2max`, `calories` в `training_sessions`
- `ltsp`, `stamina_level_7d` в `daily_metrics`
- `user_id` в `training_sessions`, `daily_metrics`, `weight_measurements`, `deleted_trainings`

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
/home/nimda/projects/running-coach/running-coach/
├── main.py                          # FastAPI‑роуты, HTML‑шаблоны
├── src/
│   ├── telegram_bot.py              # Telegram‑бот (регистрация, sync, stats, daily weight)
│   ├── models.py                    # SQLAlchemy‑модели (TrainingSession, DailyMetrics, User, …)
│   ├── coros_client.py              # Клиент для неофициального Coros API (логин, список активностей, скачивание FIT)
│   ├── parsers/
│   │   ├── common.py                # Общая логика: очистка треков, сегментация, классификация, погода
│   │   ├── tcx_parser.py            # Парсинг TCX‑файлов
│   │   └── fit_parser.py            # Парсинг FIT‑файлов (Coros, Garmin, Polar, Suunto)
│   ├── logger.py                    # Ротация логов (5×1 MB)
│   └── crypto.py                    # Шифрование паролей Coros (Fernet)
├── docs/
│   └── coros_health_metrics.md      # Теоретическая база метрик здоровья Coros (HRV, RHR, tiredness, readiness, ATI/CTI, stamina)
├── uploads/                         # Временные загруженные файлы (.tcx, .fit)
├── running_coach.db                 # SQLite‑база данных
├── CHANGELOG.md                     # История изменений (датированная)
├── AGENTS.md                        # Контекст для ИИ‑агента (правила работы, текущее состояние)
├── README.md                        # (этот файл)
└── run_telegram_bot.py             # Запуск бота как отдельного процесса (subprocess)
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

### Автоматические напоминания
- **Ежедневный опрос веса** – в 9:00 (APScheduler)
- **Проверка данных о сне** – запускается в 10:00:
  - Если данные за последние 12 часов **есть** – следующая проверка в 18:00
  - Если данных **нет** – проверка каждые 2 часа (12:00, 14:00, 16:00, 18:00)
  - Ночью (0:00–8:00) и после 20:00 уведомления **не отправляются** (пользователь спит)
  - При отсутствии данных – сообщение «🌙 Нет данных о восстановлении — используй /sync»

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
TELEGRAM_BOT_TOKEN=      # Токен бота от @BotFather
COROS_CRED_KEY=          # Ключ шифрования паролей Coros (32‑байтовый base64)
COROS_HEALTH_SYNC_INTERVAL=360   # Интервал синхронизации метрик здоровья (секунды)
COROS_ACTIVITY_SYNC_INTERVAL=60  # Интервал синхронизации тренировок (секунды)
GITHUB_TOKEN=            # Токен для пуша в GitHub
```

### Запуск сервера
```bash
cd /home/nimda/projects/running-coach/running-coach
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Запуск как служба systemd (рекомендуется)
```bash
# Копируем конфиг
cp running-coach.service ~/.config/systemd/user/

# Включаем автозагрузку и запускаем
systemctl --user enable running-coach.service
systemctl --user start running-coach.service

# Проверяем статус
systemctl --user status running-coach.service
```

### Команды управления
```bash
systemctl --user start running-coach.service
systemctl --user stop running-coach.service
systemctl --user restart running-coach.service
systemctl --user status running-coach.service
```

### Запуск Telegram‑бота
Бот запускается автоматически при старте сервера (через `subprocess` в `main.py`). Вручную:
```bash
cd /home/nimda/projects/running-coach/running-coach
python src/telegram_bot.py
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
- [x] Автомиграция БД (ALTER TABLE при старте)

### ⬜ В работе / Планы
- [ ] AI‑рекомендации (8 IF‑THEN правил из `docs/coros_health_metrics.md`)
- [ ] Training Status / Running Efficiency (расчётные метрики)
- [ ] Фильтр по типу тренировки на главной (Все / Бег / Ходьба)
- [ ] Общая дистанция и время за неделю/месяц
- [ ] Уведомления о прогрессе (похвала / ругань)
- [ ] Прогноз восстановления (на основе HRV‑тренда)
- [ ] Экспорт тренировок в Strava / TrainingPeaks
- [ ] Мобильное PWA (Progressive Web App)

---

## 📄 Лицензия

Проект разрабатывается как open‑source инструмент для личного использования. Используйте на свой страх и риск.

---

## 🐛 Отладка

### Логи
Логи ротируются в `app.log` (5 файлов × 1 MB). Просмотр последних 100 строк:
```bash
tail -n 100 app.log
```

Через веб‑интерфейс: `/logs?lines=100`

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

*Последнее обновление: 29.06.2026*