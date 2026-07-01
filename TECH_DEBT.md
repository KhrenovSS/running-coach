# TECH_DEBT.md — Руководство по исправлению технического долга

> Это **руководство по исправлению** проблем, накопившихся в проекте AI Running Coach
> на момент июня 2026. Каждая запись объясняет:
>
> - **Где проблема** (файл/строки),
> - **В чём именно она состоит** (что код делает не так),
> - **Почему это плохо** (какой риск, что сломается при росте),
> - **Как исправить** (конкретные шаги),
> - **Как проверить, что починили**.
>
> Документ написан в расчёте на разработчика, который не писал этот код.
> Если вы только что подключились к проекту — начните с раздела «Порядок работ».
>
> Все исправления **необходимо завершить до начала разработки модуля аналитики и
> рекомендаций** (`decision_module_design.md`). Иначе новый модуль будет постоянно
> спотыкаться о те же грабли: блокировки БД, расхождение настроек между веб и
> ботом, невозможность писать тесты на формулы.

---

## Условные обозначения

- 🔴 **Критично** — блокирует масштабирование/разработку модуля аналитики, чинить в первую очередь.
- 🟠 **Серьёзно** — мешает развитию, чинить во вторую очередь.
- 🟡 **Средне** — техдолг, чинить, когда дойдут руки.

После каждого пункта — чекбокс `[ ]`. Помечайте сделанное.

---

## 🔴 1. Монолитный `main.py` на 2359 строк

**Где:** `main.py` (весь файл).

**В чём проблема.**
В одном файле смешаны:
- FastAPI-роуты (`@app.get`, `@app.post`),
- ~900 строк HTML-шаблонов в виде f-строк (строки 393–1073),
- бизнес-логика разбора тренировок,
- Coros-синхронизация (`/coros/sync`, `_auto_sync_health`),
- запуск фонового планировщика,
- запуск Telegram-бота как subprocess,
- утилиты рендеринга, форматирования времени, классификации HRV и т.д.

**Почему это плохо.**
- Любая правка одного куска рискует сломать соседний.
- Невозможно покрыть тестами — нечего изолировать.
- Слияние веток превращается в ад конфликтов.
- Новый модуль `src/coach/` (см. `decision_module_design.md`) **не сможет** аккуратно
  встроиться в такой файл — придётся снова писать «в кучу».

**Как исправить.**

Разложить `main.py` по пакетам. Рекомендуемая структура:

```
src/
├── web/
│   ├── app.py            # создание FastAPI app, подключение роутов
│   ├── routes/
│   │   ├── pages.py      # GET / , /session/{id}, /settings
│   │   ├── uploads.py    # POST /upload, /upload/confirm
│   │   ├── coros.py      # POST /coros/sync, /coros/sync/health
│   │   └── logs.py       # GET /logs
│   ├── templates/        # Jinja2-шаблоны (index.html, session.html, settings.html)
│   └── static/           # CSS, JS, картинки (вынести из inline)
├── services/
│   ├── trainings.py      # создание/поиск/удаление TrainingSession
│   ├── stats.py          # calc_stats, render_zone_bars, render_type_row
│   ├── recovery_view.py  # _hrv_status, _tired_label, _readiness_label
│   └── coros_sync.py     # _sync_for_user, _auto_sync_health
├── scheduler.py          # APScheduler-задачи (вынести из main)
└── startup.py            # init_db + миграции (вынести из @app.on_event)
```

Алгоритм:
1. Создать `src/web/templates/` и перенести HTML туда. Использовать `Jinja2Templates`.
2. По одному вырезать роуты из `main.py` в `src/web/routes/*.py`, регистрировать через `APIRouter`.
3. Вспомогательные функции (`calc_stats`, `render_*`, `_hrv_status` и т.д.) — в `src/services/`.
4. `main.py` оставить как тонкую точку входа: `app = create_app()` + `uvicorn.run(...)`.

**Как проверить.**
- [ ] `wc -l main.py` показывает < 50 строк.
- [ ] Все страницы открываются, все формы работают.
- [ ] HTML лежит в `.html`-файлах, не в Python-коде.

---

## 🔴 2. Веб захардкожен на одного пользователя

**Где:** `main.py:33` — `_current_user_id = 1`. Используется во всех роутах
(см. `main.py:252, 254, 256, 1179, 1235, 1263, 1298, ...`).

**В чём проблема.**
Веб-интерфейс всегда отображает данные пользователя с `id=1`, независимо от того, кто
открыл страницу. Аутентификации нет вообще — любой, кто открыл URL сервера, видит данные
«админа». При этом Telegram-бот уже корректно работает с несколькими пользователями
(`User.telegram_chat_id`). Получается две несовместимые модели: бот многопользовательский,
веб — однопользовательский.

**Почему это плохо.**
- Если запустить сервер на внешнем IP — данные пользователя видны всем.
- Новый модуль рекомендаций строится **per-user** (персональная модель, история, уроки).
  Без идентификации текущего пользователя в вебе движок будет показывать рекомендации
  не тому человеку.
- Любое масштабирование на >1 человека невозможно.

**Как исправить.**

Минимальный вариант (для домашнего использования):
1. Добавить логин по Telegram-привязке: на странице `/login` пользователь вводит код, который
   ему присылает бот, → сервер сохраняет cookie с подписанным `user_id`.
2. Создать FastAPI-зависимость `get_current_user()`, читающую cookie и возвращающую `User`.
3. Заменить все обращения к `_current_user_id` на `current_user.id`.
4. Удалить переменную `_current_user_id` и функцию `_telegram_notify` переписать на работу
   с конкретным `User.telegram_chat_id`.

Полноценный вариант (если планируется внешний доступ):
- OAuth/Telegram Login Widget или Magic Link через бота;
- сессии в БД, CSRF-защита для POST-форм.

**Как проверить.**
- [ ] Поиск по коду: `grep -rn "_current_user_id" src/ main.py` → пусто.
- [ ] Открытие `/` в режиме инкогнито без логина → редирект на `/login`.
- [ ] Два разных пользователя видят свои тренировки, не пересекаясь.

---

## 🔴 3. Два источника правды для настроек пользователя

**Где:**
- `src/models.py:74-84` — модель `UserSettings` (помечена DEPRECATED в комментарии, но используется).
- `src/models.py:177-188` — функция `get_settings()`.
- `main.py` — везде вызывает `get_settings()` и читает `settings.max_hr`, `settings.weight`,
  `settings.coros_email` (строки 253, 1175, 1205, 1543 и др.).
- В то же время `User` (`src/models.py:13-40`) содержит те же поля плюс `user_id`-связь.

**В чём проблема.**
Одни и те же настройки (`max_hr`, `weight`, `coros_email`, `max_credible_pace`) хранятся в
двух местах: одна строка в `user_settings` для веба и колонки в `users` для бота. При
синхронизации Coros через бота обновляется `User`, а веб продолжает читать `UserSettings` —
данные расходятся.

**Почему это плохо.**
- Веб может парсить TCX с одним `max_hr`, а бот — с другим → пульсовые зоны посчитаны по-разному
  у одной и той же тренировки.
- Модуль рекомендаций использует `max_hr`, `lthr`, `weight` — если возьмёт «не ту» строку,
  выдаст некорректные зоны и нагрузку.
- Любая правка настроек в UI не отражается в работе бота.

**Как исправить.**

1. Перенести **все** обращения с `UserSettings` на `User`.
2. Создать сервисную функцию `get_user_settings(user_id) -> User` (или просто использовать `User`).
3. Удалить модель `UserSettings` и функцию `get_settings()`.
4. Написать миграцию Alembic (см. п.5): скопировать оставшиеся поля из `user_settings` в `users`,
   потом `DROP TABLE user_settings`.

**Как проверить.**
- [ ] `grep -rn "UserSettings\|get_settings" src/ main.py` → пусто.
- [ ] Изменение `max_hr` в `/settings` отражается в следующей синхронизации Coros через бот.
- [ ] Таблица `user_settings` отсутствует в БД.

---

## 🔴 4. SQLite без настройки конкурентного доступа

**Где:** `src/models.py:167` — `engine = create_engine(DATABASE_URL)`.

**В чём проблема.**
К одному файлу `running_coach.db` одновременно обращаются:
- FastAPI (несколько асинхронных запросов параллельно),
- фоновый поток автосинка Coros (`main.py:2155`, daemon thread),
- **отдельный процесс** Telegram-бота, запущенный через `subprocess.Popen` (`main.py:2166`).

При этом `create_engine` вызван **без параметров**:
- нет `connect_args={"check_same_thread": False}` → SQLAlchemy ругается на доступ из других потоков;
- нет включения **WAL** (Write-Ahead Logging) → запись блокирует все чтения;
- нет настройки пула.

**Почему это плохо.**
- Под малейшей нагрузкой будут `sqlite3.OperationalError: database is locked`.
- Особенно при автосинке: пока бот пишет тренировку, веб не может прочитать список.
- Новый модуль рекомендаций будет постоянно читать данные (тренды, история) параллельно с
  синхронизацией → блокировки гарантированы.

**Как исправить.**

Быстрый фикс (5 минут):
```python
# src/models.py
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
    pool_pre_ping=True,
)

# Включить WAL один раз
from sqlalchemy import event
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()
```

Стратегически (когда пользователей станет >5–10):
- Перейти на PostgreSQL. SQLAlchemy позволяет это сделать сменой `DATABASE_URL` и Alembic-миграцией.
- Это особенно важно, если планируется внешний доступ.

**Как проверить.**
- [ ] В директории БД появился файл `running_coach.db-wal`.
- [ ] Параллельный запуск синхронизации Coros и открытие страниц не выдаёт `database is locked`.
- [ ] `PRAGMA journal_mode;` возвращает `wal`.

---

## 🟠 5. Ручные миграции через `ALTER TABLE` с подавлением ошибок

**Где:** `main.py:1078-1174` — функция `startup()`.

**В чём проблема.**
Структура БД эволюционирует через цепочку `ALTER TABLE ... ADD COLUMN`, каждая обёрнута в
`try/except: pass`. Нет версионирования схемы. Нет отката. Если миграция упала — мы об этом
не узнаем. Если БД заведена с нуля — таблицы создаются через `Base.metadata.create_all`,
если из старой версии — через `ALTER`. Два разных пути → потенциальные расхождения схем.

**Почему это плохо.**
- Невозможно понять, в каком состоянии БД у конкретного пользователя.
- При добавлении новых таблиц модуля аналитики (`Recommendation`, `PredictionLog`,
  `UserModel`, `Lesson`) будем плодить ещё больше «слепых» ALTER-ов.
- Откатиться к предыдущей версии нельзя.

**Как исправить.**

Внедрить **Alembic** — стандартный инструмент миграций для SQLAlchemy:

```bash
alembic init migrations
# отредактировать alembic.ini → sqlalchemy.url = sqlite:///running_coach.db
# отредактировать migrations/env.py → target_metadata = Base.metadata
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

Шаги:
1. Поставить Alembic, инициализировать.
2. Создать **baseline-миграцию** под текущую схему (что сейчас в БД).
3. Все блоки `ALTER TABLE` из `startup()` удалить.
4. При старте сервера автоматически вызывать `alembic upgrade head` (или вынести в отдельный шаг деплоя).
5. Все будущие изменения моделей — через `alembic revision --autogenerate`.

**Как проверить.**
- [ ] В проекте есть папка `migrations/versions/` с файлами миграций.
- [ ] `startup()` не содержит `ALTER TABLE`.
- [ ] `alembic current` показывает текущую версию схемы.

---

## 🟠 6. Нет менеджмента сессий БД

**Где:** все файлы, везде `db = SessionLocal(); ... db.close()` вручную.

Особенно показательно: `src/models.py:191-220` — функции `get_user_by_telegram`,
`get_or_create_user_by_telegram`, `get_user` открывают сессию, **закрывают её** и
возвращают ORM-объект. Полученный объект — **detached**, при попытке обратиться к
его relationship (`user.training_sessions`) получим `DetachedInstanceError`.

**Почему это плохо.**
- Скрытые баги в коде, который пытается работать с возвращёнными `User`.
- Легко забыть `db.close()` → утечка соединений.
- Невозможно сделать транзакцию через несколько функций (каждая открывает свою сессию).
- В FastAPI принято использовать **Depends** — мы этот идиоматический паттерн не используем.

**Как исправить.**

1. Создать `src/db.py`:
   ```python
   from contextlib import contextmanager
   from src.models import SessionLocal

   @contextmanager
   def db_session():
       db = SessionLocal()
       try:
           yield db
           db.commit()
       except Exception:
           db.rollback()
           raise
       finally:
           db.close()

   # FastAPI dependency
   def get_db():
       with db_session() as db:
           yield db
   ```

2. В роутах FastAPI:
   ```python
   @router.get('/')
   def index(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
       ...
   ```

3. В сервисах — `with db_session() as db:`.

4. Из функций типа `get_user(...)` убрать `db.close()`, либо переписать так, чтобы
   принимали `db` параметром (явнее и без detached-объектов).

**Как проверить.**
- [ ] `grep -rn "SessionLocal()" src/ main.py` встречается только в `src/db.py`.
- [ ] Нет ошибок `DetachedInstanceError` в логах.
- [ ] Роуты используют `Depends(get_db)`.

---

## 🟠 7. Нет тестов и нет манифеста зависимостей

**Где:**
- Тестов в проекте 0 (`find . -name "test_*.py"` пусто).
- Нет `requirements.txt`, `pyproject.toml`, `Pipfile` — окружение существует только в
  `.venv` и нигде не зафиксировано.

**Почему это плохо.**
- Невозможно воспроизвести окружение на другой машине / в CI.
- При обновлении любой зависимости неизвестно, что сломается.
- Главное: **модуль рекомендаций без тестов разрабатывать опасно**. Формулы готовности,
  правила безопасности, калибровка — это математика, которую легко сломать незаметно.
  Без юнит-тестов мы будем выдавать пользователю неверные тренировочные советы.

**Как исправить.**

1. Зафиксировать зависимости через `pyproject.toml`:
   ```toml
   [project]
   name = "running-coach"
   requires-python = ">=3.13"
   dependencies = [
     "fastapi==0.138.0",
     "uvicorn==0.49.0",
     "sqlalchemy==2.0.51",
     "python-telegram-bot[job-queue]==22.8",
     "apscheduler==3.11.3",
     "cryptography==49.0.0",
     "fitparse==1.2.0",
     "httpx==0.28.1",
     "pydantic==2.13.4",
     "requests",
     "timezonefinder",
     "alembic",
     "jinja2",
   ]

   [project.optional-dependencies]
   dev = ["pytest", "pytest-asyncio", "freezegun", "factory-boy"]
   ```

2. Создать `tests/`:
   ```
   tests/
   ├── conftest.py        # фикстуры: тестовый engine (SQLite in-memory), пример user, фикстура данных
   ├── fixtures/          # JSON/CSV с примерами DailyMetrics, TrainingSession
   ├── parsers/
   │   └── test_tcx.py
   ├── services/
   │   └── test_stats.py
   └── coach/             # появится с разработкой модуля
       ├── test_skills.py
       └── test_rules.py
   ```

3. Добавить `pytest.ini` или секцию в `pyproject.toml` с настройками pytest.

4. (Опционально) GitHub Actions — простой workflow `pytest` на push.

**Как проверить.**
- [ ] `pip install -e .[dev]` ставит окружение из манифеста.
- [ ] `pytest` запускается и проходит хотя бы 5 базовых тестов на парсер и формулы.
- [ ] CI-бейдж в README.

---

## 🟠 8. Путаница со временем (UTC vs local)

**Где:**
- `src/models.py` — везде `default=datetime.utcnow` (строки 34, 49, 92, 105, 134, 145, 158).
- `src/parsers/common.py` — определение таймзоны через `timezonefinder` и сохранение
  **наивного локального** времени (зафиксировано в `AGENTS.md`).
- В БД лежат `DateTime` без `tzinfo` — нельзя по полю понять, это UTC или local.

**В чём проблема.**
`begin_ts` тренировки = naive local (например, 09:15 по Москве),
`created_at` юзера = naive UTC (например, 06:15 UTC того же момента).
В коде они сравниваются как одинаковые типы, но обозначают **разные** моменты времени.

**Почему это плохо.**
- Скользящие средние и тренды по `DailyMetrics.date` (Date) могут не совпадать с
  `TrainingSession.begin_ts` (наивная local datetime) — разные дни.
- «Часов до восстановления» (ключевая метрика модуля рекомендаций) считается между
  тренировкой и «сейчас» — если перепутаны таймзоны, отклонение в 3 часа.
- Пользователи в разных часовых поясах не поддерживаются вообще.

**Как исправить.**

Принять одно из двух правил **и применять везде**:

**Вариант A (рекомендуется):** хранить всё в UTC, у пользователя есть поле `timezone`,
конвертация только на границе UI.
- Заменить `datetime.utcnow` → `datetime.now(timezone.utc)`.
- Парсер TCX сохраняет UTC, но также пишет `User.timezone` при первой загрузке.
- В шаблонах UI конвертируем `utc → user.timezone` через хелпер `format_local(dt, user)`.
- Миграция: пройти по старым `begin_ts` (naive local) и сдвинуть в UTC, зная таймзону GPS-точки.

**Вариант B:** хранить как aware-datetime с таймзоной пользователя.
- Колонки `DateTime(timezone=True)` (SQLAlchemy сам сохраняет tzinfo для Postgres;
  для SQLite — текстом ISO-8601).

**Как проверить.**
- [ ] `grep -rn "datetime.utcnow" src/ main.py` → пусто.
- [ ] Поле `User.timezone` существует и заполняется.
- [ ] Тренировка, загруженная пользователем из Владивостока, отображается с правильным временем.

---

## 🟠 9. «Голые» `except Exception` подавляют ошибки

**Где:** 23 места в `main.py` и `src/*.py` (`grep -rn "except Exception:\|except:" main.py src/`).

Особенно: миграции в `startup()` (`main.py:1101, 1115, 1120, 1126, 1136, 1142, 1153, 1170`)
— все ALTER-ы обёрнуты в `except: pass`. Если миграция упала — мы об этом не узнаем.

**Почему это плохо.**
- Ошибки синхронизации Coros, парсинга TCX, миграций — пропадают молча.
- Отладить невозможно: пользователь говорит «не работает», в логах пусто.
- Для системы, которая будет **давать тренировочные рекомендации**, это категорически
  недопустимо: если калибровка персональной модели упала — мы продолжим выдавать советы
  на основе устаревших данных.

**Как исправить.**

1. Заменить голые `except` на конкретные типы:
   ```python
   # было
   try:
       ...
   except Exception:
       pass

   # стало
   try:
       ...
   except (OperationalError, IntegrityError) as e:
       logger.warning("Ожидаемая ошибка миграции %s: %s", col, e)
   ```

2. Если намерение — **проглотить** ошибку (например, повторный ALTER на существующую колонку),
   написать это явно и **залогировать на DEBUG**.

3. Никогда не использовать `except: pass` (без указания типа) — это ловит даже `KeyboardInterrupt`.

**Как проверить.**
- [ ] `grep -rn "except:\s*$\|except Exception:\s*$" main.py src/` → пусто или только осознанные случаи с логированием.
- [ ] При искусственной поломке миграции (например, конфликтный тип колонки) в логах
      появляется сообщение.

---

## 🟡 10. Хрупкий жизненный цикл процессов

**Где:**
- `main.py:2161-2168` — `_start_telegram_bot()` запускает бот через `subprocess.Popen` с
  `stdout=DEVNULL, stderr=DEVNULL`.
- `main.py:2155` — автосинк живёт в daemon-потоке внутри FastAPI.

**В чём проблема.**
- Бот — отдельный процесс, но его лог выкинут в `/dev/null`. Если упал — никто не узнает.
- Нет перезапуска при падении.
- Нет health-check.
- Перезапуск веба перезапускает бота (subprocess убивается).

**Как исправить.**

Разделить на **3 systemd-юнита**:
```
running-coach-web.service     # uvicorn main:app
running-coach-bot.service     # python run_telegram_bot.py
running-coach-worker.service  # APScheduler для синков/напоминаний
```

Каждый:
- пишет лог через `journalctl` или в отдельный файл (с ротацией),
- `Restart=on-failure`,
- зависимость `After=network-online.target`.

Из `main.py` убрать `_start_telegram_bot()` и поток автосинка — это не задача веба.

**Как проверить.**
- [ ] `systemctl --user status running-coach-bot` показывает живой процесс.
- [ ] `journalctl --user -u running-coach-bot -n 50` показывает логи.
- [ ] Падение бота → автоматический перезапуск через 5 секунд.

---

## 🟡 11. Inline-HTML на f-строках

**Где:** `main.py` строки 393–1073 — три огромных HTML-шаблона (index, session, settings)
вставлены прямо в Python как f-строки. Плюс ~94 места `html += f"..."` в `build_nav_html`,
`render_zone_bars` и т.п.

**Почему это плохо.**
- Любые данные пользователя вставляются без экранирования → потенциальный XSS.
- Нет переиспользования компонентов.
- Невозможно работать дизайнеру/верстальщику.
- Шаблоны не подсвечиваются IDE как HTML.

**Как исправить.**
1. Поставить Jinja2 (`pip install jinja2`).
2. Создать `src/web/templates/` с файлами `base.html`, `index.html`, `session.html`, `settings.html`.
3. Вынести CSS в `src/web/static/styles.css`.
4. Использовать `Jinja2Templates(directory="src/web/templates")`.
5. Все данные передавать через контекст шаблона — Jinja2 экранирует HTML автоматически.

**Как проверить.**
- [ ] `grep -c 'html += f' main.py src/` → 0.
- [ ] Передача `<script>alert(1)</script>` в комментарий не выполняется на странице.

---

## 🟡 12. Coros-клиент на синхронном `requests` без TTL токена

**Где:** `src/coros_client.py`.

**В чём проблема.**
- Используется `requests.Session()` (синхронный) внутри async/threaded приложения —
  блокирует event loop.
- Токен `accesstoken` сохраняется в памяти объекта, но не имеет срока жизни и не
  проверяется на истечение. На практике клиент создаётся заново и перелогинивается на
  каждую синхронизацию (см. `_sync_for_user`).

**Как исправить.**
1. Перейти на `httpx.AsyncClient` (httpx уже есть в зависимостях).
2. Хранить токен и `user_id` Coros в БД (поля `User.coros_access_token`, `User.coros_token_expires_at`).
3. Реавторизация только при `401` или истечении срока.

**Как проверить.**
- [ ] Повторная синхронизация в течение часа не вызывает `/account/login`.
- [ ] Метод `authenticate` асинхронный.

---

## 🟡 13. Конфигурация разбросана по проекту

**Где:**
- Хардкод: `_current_user_id = 1`, дефолты `max_hr=177`, лимиты `max_credible_pace=3.0`
  встречаются и в `models.py`, и в `parsers/common.py`, и в `main.py`.
- `.env`: `GITHUB_TOKEN`, `TELEGRAM_BOT_TOKEN`, `COROS_CRED_KEY`.
- БД: настройки пользователя в `User`.
- `src/crypto.py` сам **генерирует ключ шифрования** и **дописывает его в `.env`** при
  первом запуске — это опасный паттерн (deployer не контролирует ключи).

**Как исправить.**

1. Завести `src/config.py` на `pydantic-settings`:
   ```python
   from pydantic_settings import BaseSettings

   class Settings(BaseSettings):
       database_url: str = "sqlite:///running_coach.db"
       telegram_bot_token: str
       coros_cred_key: str
       max_hr_default: int = 177
       max_credible_pace_default: float = 3.0
       # ...

       class Config:
           env_file = ".env"

   settings = Settings()  # импортируется везде
   ```

2. Все константы и переменные окружения читать через `settings`.

3. Убрать автогенерацию ключа в `crypto.py` — если `COROS_CRED_KEY` не задан, **падать с понятной
   ошибкой**: «задайте COROS_CRED_KEY в .env, сгенерировать можно: `python -c 'from cryptography.fernet
   import Fernet; print(Fernet.generate_key().decode())'`».

**Как проверить.**
- [ ] `src/config.py` существует, все остальные модули импортируют `from src.config import settings`.
- [ ] Запуск без `COROS_CRED_KEY` падает с понятным сообщением, а не молча генерирует ключ.

---

## Порядок работ (предлагаемый)

Это **Этап -1** перед разработкой модуля аналитики (`decision_module_design.md`, Этап 0).

1. **Спринт 1 — фундамент окружения** (1–2 дня)
   - [x] п.7: `pyproject.toml` + `pytest` + папка `tests/`.
   - [x] п.4: SQLite WAL + `check_same_thread=False` (быстрый фикс).
   - [x] п.9: убрать `except: pass` в миграциях и автосинке.

2. **Спринт 2 — данные и пользователи** (2–4 дня)
   - [x] п.5: внедрить Alembic, baseline-миграцию.
   - [x] п.3: убрать `UserSettings`, всё на `User`.
   - [x] п.2: убрать `_current_user_id = 1`, добавить аутентификацию (email+password, bcrypt, `/login`, `/register`, `/reset_password` в боте).
   - [x] п.6: ввести `get_db()` через `Depends`, починить detached-объекты.

3. **Спринт 3 — структура и UI** (3–5 дней)
   - [ ] п.1: декомпозиция `main.py` на `web/routes`, `services`, `scheduler`.
   - [ ] п.11: Jinja2-шаблоны.
   - [ ] п.13: единая конфигурация через `pydantic-settings`.

4. **Спринт 4 — процессы и интеграции** (1–2 дня)
   - [x] п.10: разделить на systemd-юниты web/bot (выполнено: `running-coach-web.service` + `running-coach-bot.service`).
   - [ ] п.8: стандартизировать время (UTC + `User.timezone`).
   - [ ] п.12: переписать Coros-клиент на `httpx.AsyncClient` + TTL токена.

5. **Спринт 5 — PostgreSQL + Docker (3 контейнера)** (2–3 дня)
   - [x] **5.1** Добавить `psycopg2-binary==2.9.10` в `pyproject.toml`.
   - [ ] **5.2** `src/models.py` — убрать SQLite-only код, сделать engine database-agnostic (условное создание: PostgreSQL → `pool_size=10, max_overflow=20`; SQLite → `check_same_thread`, `PRAGMA WAL`).
   - [ ] **5.3** `alembic/env.py` — читать `DATABASE_URL` из env вместо хардкода в `alembic.ini`.
   - [ ] **5.4** Fresh Alembic baseline: удалить 4 старые миграции (`c3f51ae84837`, `0bba2c2badec`, `69f28e182276`, `eb50c256201f`, `eb448386be71`), создать один новый baseline через `alembic revision --autogenerate` (database-agnostic, `op.create_table` без `AUTOINCREMENT`).
   - [ ] **5.5** `main.py` — `PENDING_DIR` сделать configurable через env (`PENDING_DIR`).
   - [ ] **5.6** `src/crypto.py` — безопасный fallback если `.env` не найден (warning вместо crash).
   - [ ] **5.7** `Dockerfile` — Python 3.13-slim, установка зависимостей, копирование кода.
   - [ ] **5.8** `docker-compose.yml` — 3 сервиса: `db` (postgres:16-alpine), `app` (uvicorn), `bot` (run_telegram_bot.py). Healthcheck на db, `depends_on: condition: service_healthy`, `restart: on-failure`, volumes для pgdata/uploads/logs.
   - [ ] **5.9** `.dockerignore` — исключить `.venv/`, `__pycache__/`, `.git/`, `*.db*`, `logs/`, `uploads/`, `.env`.
   - [ ] **5.10** `.env` / `.env.example` — добавить `POSTGRES_PASSWORD`, `DATABASE_URL` (postgresql://...).
   - [ ] **5.11** Локальная проверка: `docker compose build && docker compose up`, `curl /health`, `/login` → 200, Telegram `/start` → `/register` → вход.
   - [ ] **5.12** Удалить systemd-юниты после успешного тестирования Docker.
   - [ ] **5.13** Обновить `CHANGELOG.md`, `AGENTS.md`, `README.md`.

   **Архитектура:**
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

   **Примечание:** данные SQLite не переносятся. Пользователь создаётся заново через Telegram `/start`, тренировки синхронизируются с Coros автоматически.

После этих спринтов можно с чистой совестью начинать **Этап 0** модуля аналитики
(см. `decision_module_design.md`, раздел 12).

---

*Версия: 1.0 · Дата: 29.06.2026 · Проект: AI Running Coach*
