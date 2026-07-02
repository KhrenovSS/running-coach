# Контекст проекта Running Coach

## Суть
Персональный AI-тренер для бега. Парсит TCX-файлы (любые часы: Garmin, Coros, Polar, Suunto), анализирует тренировки, определяет тип (интервальная/темповая/long/recovery), разбивает на сегменты, считает пульсовые зоны, очищает GPS-ошибки.

## Стек
Python + FastAPI + PostgreSQL 16 (Docker Compose), написано через ИИ (open code style).  
Сервер: Docker Compose — 3 контейнера (`db`, `app`, `bot`).  
Локальная разработка: `uvicorn main:app --host 0.0.0.0 --port 8000` (SQLite fallback).

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

## Структура файлов
- `main.py` — FastAPI-роуты, HTML-шаблоны, отображение списка и деталей тренировок
- `src/models.py` — модель TrainingSession (SQLAlchemy), путь к БД абсолютный
- `src/config/constants.py` — централизованные константы (`CONFIG`)
- `src/exceptions.py` — типизированные исключения приложения
- `src/utils/logger.py` — структурированное логирование с ротацией
- `src/services/audit.py` — сервис аудита (БД + файл)
- `src/services/auth.py` — генерация и проверка токенов Telegram-авторизации, bcrypt-хеширование паролей (`hash_password`, `verify_password`, `authenticate_user`)
- `src/api/middleware.py` — централизованная обработка ошибок, логирование запросов и session middleware
- `src/api/routes/health.py` — health check endpoint
- `src/api/routes/auth.py` — маршруты аутентификации (`/auth/telegram`, `/auth/login`, `/auth/register`, `/auth/logout`)
- `src/parsers/common.py` — общая логика: очистка треков, сегментация, классификация, погода (`process_trackpoints()`)
- `src/parsers/tcx_parser.py` — парсинг TCX-файлов (XML) → вызов `process_trackpoints()`
- `src/parsers/fit_parser.py` — парсинг FIT-файлов (бинарный) → вызов `process_trackpoints()`
- `src/coros_client.py` — клиент для неофициального Coros API (логин, список активностей, скачивание FIT)

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

## Что было сделано сегодня (20.06.2026)
1. Переписана сегментация: км-блоки по умолчанию, сплит только для интервальной
2. Классификация переделана на подсчёт вариативных км (с бинами по 200м для сглаживания GPS-шума)
3. Добавлен format_duration (мм:сс) и duration в сегменты
4. Установлен минимум 200м для дробления
5. Обновлены пороги пульсовых зон по таблице пользователя
6. Дистанция округлена до 1 знака
7. Загружены и проверены 6 TCX-файлов (все корректно опознаны как Темповые)
8. База данных очищалась, сервер перезапускался (важно: pkill -9 -f "uvicorn main")

## Что было сделано (21.06.2026)
1. **Высота (elevation)**: Парсинг `AltitudeMeters` из TCX. Добавлен расчёт набора/спуска в каждый сегмент (`elevation_gain`/`elevation_loss`) и суммарный за тренировку. Отображается в карточке тренировки и в таблице сегментов.
2. **Часовой пояс**: Определяется через `timezonefinder` по первой GPS-координате тренировки. Время конвертируется из UTC в локальное (например, `Europe/Moscow` → +03:00). В БД сохраняется наивное локальное время.
3. **Погода (Open-Meteo)**: Интегрирован Open-Meteo Archive API (бесплатно, без API-ключа). По средней GPS-координате и дате тренировки запрашивается почасовая температура. Средняя температура за тренировку — на главном экране. Температура по сегментам — в детальном просмотре. Кэширование погоды в памяти.

## Важные моменты
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

## Что было сделано (21.06.2026, вечер)
1. **Иконка погоды в колонке «Погода»**: Вместо «Темп.» теперь колонка «Погода». Температура отображается с иконкой (☀️⛅☁️🌫️🌦️🌧️❄️🌨️⛈️) и знаком градуса без C (25°C → ☀️ 25°).
2. **WMO weathercode**: Добавлен параметр `weathercode` в запрос к Open-Meteo. WMO-код маппится на иконку погоды. Код сохраняется в модель (`weather_code`) и в каждый сегмент (`segments_json[].weather_code`).
3. **Автомиграция БД**: При старте сервера добавляет колонку `weather_code` через `ALTER TABLE` (если её нет).
4. **Иконка в детальном просмотре**: На странице тренировки иконка погоды показывается в карточке и в таблице сегментов.
5. **Graceful fallback для старых данных**: Если `weather_code` отсутствует (старые тренировки), иконка не показывается — отображается только температура без иконки (чтобы не было `?`). При перезагрузке TCX данные подтянутся заново.
6. **График пульса и темпа (Chart.js)**: При загрузке TCX парсер собирает временной ряд HR (посекундно, каждый trackpoint) и pace (сглажен скользящим окном **10 секунд**, минимум 5 сек и 15м дистанции для достоверности). Окно 10 сек — компромисс: для равномерного бега фильтрует GPS-шум, для интервалов (30+ сек) перепады темпа видны. На странице тренировки — интерактивный график с двойной осью: пульс (слева, красный) и темп (справа, синий, обратная шкала). Данные сохраняются в `hr_pace_series` (JSON).
7. **Индикатор загрузки (overlay)**: При выборе TCX-файлов показывается полупрозрачный оверлей со спиннером и надписью «Обработка файлов…». Отправка через fetch (AJAX), после ответа — редирект на главную.
8. **Полноэкранный режим**: Убрано ограничение `max-width` на страницах списка тренировок и детального просмотра — сайт растягивается на весь экран (отступы 30px по бокам). Страница настроек осталась компактной (500px).

## Что было сделано (25.06.2026)
1. **Детекция ошибочных точек**: функция `clean_trackpoints()` в `tcx_parser.py` — два прохода (GPS-скачки, нереальный темп), удаление точек и логирование в `cleaning_log`
2. **Пересчёт дистанции после очистки**: phantom-дельты с темпом быстрее `max_credible_pace` отбрасываются; `total_distance_km`, сегменты и темп корректны
3. **Подтверждение загрузки**: если после очистки осталось <1 км или `training_type='invalid'` — сервер возвращает JSON, браузер показывает `confirm()`, пользователь решает, добавлять ли
4. **JS bugfix**: `\n` в Python f-строке экранировано (была синтаксическая ошибка — confirm не показывался)
5. **CHANGELOG.md**: создан файл истории версий
6. **AGENTS.md**: добавлены правила ведения changelog, формат коммитов, актуализация README
7. **README.md**: обновлён под текущее состояние

## Стиль комментариев (Comment style)

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

## Текущее состояние (Session — 01.07.2026, вечер)

**Развёртывание:** Docker Compose, 3 контейнера (`db` + `app` + `bot`)  
**Команды управления:**
```bash
# Запуск (из директории проекта, нужен sudo для docker)
sudo bash -c 'cd /home/nimda/projects/running-coach && set -a && source .env && set +a && export POSTGRES_PASSWORD && docker compose up -d'

# Остановка
sudo bash -c 'cd /home/nimda/projects/running-coach && docker compose down'

# Статус
sudo docker compose -f /home/nimda/projects/running-coach/docker-compose.yml ps

# Логи
sudo docker logs running-coach-app-1 --tail 50
sudo docker logs running-coach-bot-1 --tail 50
sudo docker logs running-coach-db-1 --tail 50
```
**Команда пуша (из любой папки):**
```bash
set -a && source /home/nimda/projects/running-coach/.env && set +a && cd /home/nimda/projects/running-coach && git push "https://KhrenovSS:${GITHUB_TOKEN}@github.com/KhrenovSS/running-coach.git" main
```

**БД:** PostgreSQL 16 (контейнер `running-coach-db-1`), volume `pgdata`.
**Пользователь зарегистрирован:** user id=1, email=khrenov.ss@gmail.com, coros_email=khrenov.ss@gmail.com, 0 тренировок (первая синхронизация — вручную через 🔄 Coros Sync).

**Systemd-юниты удалены.** Раньше использовались `running-coach.service` и `running-coach-bot.service` — теперь Docker управляет запуском.

**Спринты 1-2, 4-5 завершены.** Sprint 6 (per-user частота синхронизации Coros) — план в `TECH_DEBT.md`, не реализован.

**Что сделано за сессию 01.07.2026 (ночь — PostgreSQL + Docker):**
1. **PostgreSQL + Docker (3 контейнера)**: `db` (postgres:16-alpine), `app` (uvicorn), `bot` (run_telegram_bot.py)
2. **`src/models.py`**: engine database-agnostic — PostgreSQL или SQLite в зависимости от `DATABASE_URL`
3. **`alembic/env.py`**: `DATABASE_URL` из env, `render_as_batch` только для SQLite
4. **Fresh Alembic baseline** (`f75d2362cf9f`): заменены 4 старые миграции, database-agnostic
5. **`Dockerfile`**, **`docker-compose.yml`**, **`.dockerignore`** созданы
6. **`PENDING_DIR`** configurable через env
7. **`src/crypto.py`**: предупреждение если `COROS_CRED_KEY` не задан
8. **Systemd-юниты удалены** — Docker управляет запуском
9. **DNS**: `/etc/resolv.conf` переключён на 8.8.8.8 (роутер 192.168.1.1 не резолвит CloudFront)

**Что сделано за сессию 01.07.2026 (вечер — password auth + Sprint 6 план):**
1. **Email+password аутентификация**: bcrypt, `/login`, `/register`, `/reset_password` в боте
2. **Telegram-бот**: `/login_info`, `/reset_password`
3. **Пользователь зарегистрирован**: user id=1, email=khrenov.ss@gmail.com, Coros привязан
4. **Sprint 6 план** добавлен в `TECH_DEBT.md`: per-user настраиваемая частота синхронизации Coros (10 задач 6.1–6.10), ручная первая синхронизация, баннер для новых пользователей

**Что сделано за сессию 01.07.2026 (день — вынос бота в systemd + опрос веса):**
1. **Telegram-бот вынесен в отдельный systemd-юнит** (теперь заменён на Docker)
2. **Починен ежедневный опрос веса**: расписание 9/12/15/18

**Известные проблемы:**
- Docker требует `sudo` (пользователь `nimda` в группе `docker`, но может потребоваться перелогин)
- DNS: `/etc/resolv.conf` перезаписывается на 8.8.8.8 — после перезагрузки может вернуться 192.168.1.1
- Существующие данные SQLite не перенесены — пользователь создан заново через Telegram `/start`

**Следующие шаги:**
- ✅ Создать пользователя: /start в Telegram → ссылка на /register → установить email+пароль — **выполнено**
- ⬜ Первая синхронизация: пользователь нажимает 🔄 Coros Sync в веб-интерфейсе
- ⬜ **Спринт 6** (TECH_DEBT.md): per-user частота синхронизации, баннер, настройки
- ✅ **Спринт 3** (TECH_DEBT.md): декомпозиция main.py, Jinja2, pydantic-settings — **завершён**
- ⬜ **Спринт 4** (TECH_DEBT.md): стандартизация времени (UTC), Coros-клиент на httpx
- ⬜ **Модуль аналитики** — 8 этапов из `decision_module_design.md`
- ⬜ **Фильтр по типу** тренировки на главной
- ⬜ **Общая дистанция и время** за неделю/месяц

## Текущее состояние (Session — 02.07.2026, Sprint 3 завершён)

**Спринт 3 полностью завершён!** `main.py` декомпозирован с 2776 до 7 строк.

### Итоговая структура после Спринта 3:
- `main.py` (7 строк) — только `create_app()` + `uvicorn.run()`
- `src/startup.py` — фабрика приложения, startup-событие
- `src/scheduler.py` — `AutoSyncScheduler` (одиночка)
- `src/web/routes/` — 4 sub-router: `pages.py` (7), `uploads.py` (3), `coros.py` (3), `logs.py` (1)
- `src/web/state.py` — глобальное состояние (`_pending`, `_sync_tasks`, `TRAINING_TYPES_RU`)
- `src/deps.py` — общие зависимости (`templates = Jinja2Templates`)
- `src/services/*.py` — 4 сервисных модуля (telegram_notify, stats, recovery_view, coros_sync_auto)
- `src/config/settings.py` — `Settings(BaseSettings)` из pydantic-settings
- `src/config/constants.py` — плоские module-level константы (HR зоны, API endpoints, пороги)
- `src/web/templates/*.html` — 6 Jinja2-шаблонов

**Если сессия прервана:** перед продолжением работы прочитать:
1. `AGENTS.md` — правила проекта
2. `SPRINT_3_PLAN.md` — план с чекбоксами
3. `README.md` — актуальное состояние проекта

**Следующие шаги (из TECH_DEBT.md):**
- Sprint 4: стандартизация времени (UTC), Coros-клиент на httpx
- Sprint 6: per-user частота синхронизации, баннеры, настройки
- Модуль аналитики (8 этапов из decision_module_design.md)
- Фильтр по типу тренировки на главной
- Общая дистанция и время за неделю/месяц
