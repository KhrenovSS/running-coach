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

3. **Спринт 3 — структура и UI** (3–5 дней) — ✅ *завершён*
   - [x] п.1: декомпозиция `main.py` на `web/routes`, `services`, `scheduler`.
   - [x] п.11: Jinja2-шаблоны.
   - [x] п.13: единая конфигурация через `pydantic-settings`.

4. **Шаг 0 — быстрые исправления** (до Спринта 4)
   - [ ] п.15: исправить часовой пояс daily weight reminder (бот присылает в 12:00 MSK вместо 9:00).

5. **Спринт 4 — процессы, интеграции, мульти-брендовая архитектура** (3–4 дня)
   - [x] п.8: стандартизировать время (UTC + `User.timezone`).
   - [x] п.12+14: переписать Coros-клиент на `httpx.AsyncClient` сразу как `CorosWatchClient(BaseWatchClient)`, внедрить мульти-брендовую архитектуру.
   — *см. подробное описание ниже.*
   — **Важно:** п.12+14 выполняется **после** Sprint 4.5, чтобы `WatchCredential` и миграции создавались на чистой PostgreSQL-схеме с `TIMESTAMPTZ`.

6. **Спринт 5 — PostgreSQL + Docker (3 контейнера)** (2–3 дня)
   — *завершён, см. подробное описание ниже.*

7. **Sprint 4.5 — Полный отказ от SQLite, переход на PostgreSQL + TIMESTAMPTZ** (1 день)
   — *следующий шаг после п.8, перед п.12+14.*
   — **Зачем:** убирает SQLite-специфичные костыли (`render_as_batch`, naive UTC, `check_same_thread`) перед созданием новых таблиц мульти-брендовой архитектуры.

8. **Спринт 4 (продолжение) — п.12+14: Multi-brand architecture** (2–3 дня)
   - [x] п.12+14: переписать Coros-клиент на `httpx.AsyncClient` сразу как `CorosWatchClient(BaseWatchClient)`, внедрить мульти-брендовую архитектуру.
   — **Зависимость:** выполняется после Sprint 4.5.

9. **Спринт 6 — Настраиваемая частота синхронизации per-user (бренд-независимая)** (1–2 дня)
   — *см. подробное описание ниже.*
   — **Зависимость:** выполняется после п.12+14 (требуется `WatchCredential`).

10. **Спринт 7 — Панель администрирования (Admin panel)** (2–3 дня)
   — *отложен до появления >1 пользователя или модуля аналитики.*

---

### Детальное описание Шага 0 (перед Спринтом 4)

#### п.15 — Исправление daily weight reminder (часовой пояс бота)

**Проблема:** PTB `JobQueue` работает в UTC, `run_daily(hour=9)` срабатывает в 9:00 UTC = 12:00 MSK.  
Пользователь ожидает напоминание в 9:00 MSK.

- [ ] **15.1** `src/telegram_bot.py`: добавить `Defaults(tzinfo=pytz.timezone("Europe/Moscow"))` в `Application.builder()`.
- [ ] **15.2** Исправить catch-up запрос при старте бота (`telegram_bot.py:1049-1053`): убрать глобальную проверку `any_weight_today` без `user_id` — она бессмысленна, т.к. `daily_weight_job` и так итерирует всех пользователей. Заменить на `run_once` через 30 сек без предварительной проверки (бот сам разберётся).
- [ ] **15.3** `docker-compose.yml`: добавить `TZ=Europe/Moscow` в `environment` сервисов `bot` и `app`.
- [ ] **15.4** Пересобрать образ бота: `docker compose build bot && docker compose up -d`.
- [ ] **15.5** Проверить лог: `sudo docker logs running-coach-bot-1 --tail 20 | grep -i "weight\|вес"`.

**Как проверить:**
- [ ] Бот присылает напоминание о весе ровно в 9:00 MSK (а не в 12:00).
- [ ] Лог содержит `Scheduler timezone: Europe/Moscow` или эквивалент.
- [ ] `daily_weight_job` в логе показывает `hour=9` в 9:00 MSK.

---

### Детальное описание Спринта 4

4. **Спринт 4 — Процессы, интеграции, мульти-брендовая архитектура** (3–4 дня)

   **Цель:** стандартизировать хранение времени, перевести Coros-клиент на async HTTP c одновременным внедрением абстракции `BaseWatchClient`, чтобы в будущем добавлять Garmin/Polar/Suunto без переписывания пайплайна синхронизации.

   #### п.8 — Стандартизация времени (UTC)

   - [x] **8.1** Заменить `datetime.utcnow()` → `datetime.now(timezone.utc)` во всех моделях и сервисах.
   - [x] **8.2** Добавить поле `User.timezone` (String(50), nullable) — определяется по GPS первой тренировки.
   - [x] **8.3** Парсер `src/parsers/common.py`: сохранять UTC-время, таймзону писать в `User.timezone` и `TrainingSession.timezone`.
   - [x] **8.4** Миграция Alembic: конвертировать старые naive-local `begin_ts` в UTC (используя таймзону первой GPS-точки каждой тренировки).
   - [x] **8.5** Шаблоны Jinja2: конвертировать UTC → локальное время пользователя через хелпер `local_dt(dt, user)`.
   - [x] **8.6** `grep -rn "datetime.utcnow" src/ main.py` → 0 совпадений.

   **Примечание:** п.8 завершён. Пункт п.12+14 (мульти-брендовая архитектура) выполняется **после Sprint 4.5**, чтобы `WatchCredential` и все новые таблицы создавались на чистой PostgreSQL-схеме с `TIMESTAMPTZ`, без SQLite-наследия.

   #### п.12+14 — Coros-клиент на httpx.AsyncClient + мульти-брендовая архитектура (одним блоком)

   > **Почему объединены:** переписывать `CorosClient` дважды (сначала на httpx, потом на BaseWatchClient) — лишняя работа. Сразу делаем `CorosWatchClient(BaseWatchClient)` на `httpx.AsyncClient`.

   - [x] **12+14.1** Создать `src/watch/` пакет с `__init__.py`.
   - [x] **12+14.2** Создать `src/watch/base.py` — `BaseWatchClient(ABC)` с протоколом:
     ```python
     class BaseWatchClient(ABC):
         @abstractmethod
         async def authenticate(self) -> bool: ...
         @abstractmethod
         async def list_activities(self, since: datetime | None) -> list[dict]: ...
         @abstractmethod
         async def download_activity(self, activity_id: str) -> bytes: ...
         @abstractmethod
         async def get_daily_metrics(self, date: str) -> dict | None: ...
     ```
   - [x] **12+14.3** Создать `src/watch/coros.py`:
     - Класс `CorosWatchClient(BaseWatchClient)` на `httpx.AsyncClient`.
     - Все методы async.
     - Кеширование токена через `WatchCredential.access_token` / `token_expires_at`.
   - [x] **12+14.4** Создать `src/watch/factory.py`:
     ```python
     _registry: dict[str, type[BaseWatchClient]] = {}
     def register(brand: str, client_cls: type[BaseWatchClient]): ...
     def get_watch_client(brand: str, **kwargs) -> BaseWatchClient: ...
     ```
   - [x] **12+14.5** Зарегистрировать `CorosWatchClient` в фабрике.
   - [x] **12+14.6** Удалить старый `src/coros_client.py` (весь функционал перенесён в `src/watch/coros.py`).
   - [x] **12+14.7** Создать модель `WatchCredential` (отдельная таблица):
     - `id` (PK), `user_id` (FK→users.id), `brand` (String, например 'coros'),
       `encrypted_user` (Text), `encrypted_password` (Text),
       `access_token` (Text, nullable), `token_expires_at` (DateTime, nullable),
       `created_at`, `updated_at`.
     - Alembic миграция.
   - [x] **12+14.8** Перенести данные из `User.coros_email`/`coros_password` в `WatchCredential` (миграция данных).
   - [ ] **12+14.9** Удалить поля `coros_email`, `coros_password`, `last_coros_sync` из модели `User`. (отложено — оставлено для обратной совместимости с telegram_bot.py)
   - [x] **12+14.10** Обобщить `src/services/coros_sync_auto.py` → `src/services/sync_service.py`:
     - Функции принимают `BaseWatchClient`, а не `CorosClient`.
     - Выбор клиента — через `get_watch_client(brand, ...)` из `WatchCredential`.
   - [x] **12+14.11** Обобщить `src/scheduler.py`:
     - Единый поток перебирает `WatchCredential`, группирует по `user_id`, для каждого brand вызывает соответствующий sync-метод.
   - [x] **12+14.12** Обобщить `src/web/routes/coros.py` → `src/web/routes/sync.py`:
     - `/sync/{brand}/run` вместо `/coros/sync`.
     - `/sync/{brand}/health` вместо `/coros/sync/health`.
     - `/sync/status/{task_id}` без brand — единый для всех.
     - Старый `/coros/sync` — редирект (обратная совместимость).
   - [x] **12+14.13** Добавить колонку `source_brand` (String) в `DailyMetrics`.
   - [x] **12+14.14** Переименовать `COROS_CRED_KEY` → `CRED_KEY` в `crypto.py` и `.env`. Поддерживать старый `COROS_CRED_KEY` как fallback с `warn`.
   - [x] **12+14.15** Обобщить audit-события в `src/services/audit.py`:
     - `coros.sync.*` → `sync.{brand}.*`.
     - Методы `log_coros_sync_*` → `log_sync_*(brand, ...)` (обратная совместимость через депрекейт).
   - [x] **12+14.16** `src/web/routes/pages.py` — заменить импорт `_auto_sync_status` на brand-agnostic статус.

   **Как проверить:**
   - [ ] `grep -rn "CorosClient" src/` → только в `src/watch/coros.py` и `src/watch/factory.py`.
   - [ ] `grep -rn "coros_email\|coros_password" src/` → 0 совпадений.
   - [ ] Синхронизация Coros работает через `/sync/coros/run`.
   - [ ] Написать заглушку `DummyWatchClient(BaseWatchClient)` — зарегистрировать, запустить синхронизацию — пайплайн не падает.
   - [ ] Audit-события пишут `sync.coros.*`.

   **Что НЕ входит в Спринт 4:**
   - Реализация клиентов для Polar, Suunto, Garmin — только архитектура.
   - Per-user интервалы синхронизации — Sprint 6.
   - Per-user интервалы синхронизации — Sprint 6.

---

5. **Спринт 5 — PostgreSQL + Docker (3 контейнера)** (2–3 дня)
   - [x] **5.1** Добавить `psycopg2-binary==2.9.10` в `pyproject.toml`.
   - [x] **5.2** `src/models.py` — убрать SQLite-only код, сделать engine database-agnostic (условное создание: PostgreSQL → `pool_size=10, max_overflow=20`; SQLite → `check_same_thread`, `PRAGMA WAL`).
   - [x] **5.3** `alembic/env.py` — читать `DATABASE_URL` из env вместо хардкода в `alembic.ini`.
   - [x] **5.4** Fresh Alembic baseline: удалить 4 старые миграции (`c3f51ae84837`, `0bba2c2badec`, `69f28e182276`, `eb50c256201f`, `eb448386be71`), создать один новый baseline через `alembic revision --autogenerate` (database-agnostic, `op.create_table` без `AUTOINCREMENT`).
   - [x] **5.5** `main.py` — `PENDING_DIR` сделать configurable через env (`PENDING_DIR`).
   - [x] **5.6** `src/crypto.py` — безопасный fallback если `.env` не найден (warning вместо crash).
   - [x] **5.7** `Dockerfile` — Python 3.13-slim, установка зависимостей, копирование кода.
   - [x] **5.8** `docker-compose.yml` — 3 сервиса: `db` (postgres:16-alpine), `app` (uvicorn), `bot` (run_telegram_bot.py). Healthcheck на db, `depends_on: condition: service_healthy`, `restart: on-failure`, volumes для pgdata/uploads/logs.
   - [x] **5.9** `.dockerignore` — исключить `.venv/`, `__pycache__/`, `.git/`, `*.db*`, `logs/`, `uploads/`, `.env`.
   - [x] **5.10** `.env` / `.env.example` — добавить `POSTGRES_PASSWORD`, `DATABASE_URL` (postgresql://...).
   - [x] **5.11** Локальная проверка: `docker compose build && docker compose up`, `curl /health`, `/login` → 200, Telegram `/start` → `/register` → вход.
   - [x] **5.12** Удалить systemd-юниты после успешного тестирования Docker.
   - [x] **5.13** Обновить `CHANGELOG.md`, `AGENTS.md`, `README.md`.

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

---

### Детальное описание Sprint 4.5

7. **Sprint 4.5 — Полный отказ от SQLite, переход на PostgreSQL + TIMESTAMPTZ** (1 день)

   **Цель:** убрать SQLite как dev-альтернативу, стандартизироваться на PostgreSQL. Все DateTime-колонки хранят `TIMESTAMP WITH TIME ZONE` (aware UTC), убраны костыли `utcnow()` и `.replace(tzinfo=None)`.

   **Зачем:** SQLite вызывает различия в поведении Alembic, миграций, JSON-полей, datetime. Сейчас (один пользователь = разработчик) — самый дешёвый момент для перехода.

   **Позиция в очереди:** выполняется сразу после п.8 и **перед** п.12+14 (мульти-брендовая архитектура). Новые таблицы `watch_credentials` и `DailyMetrics.source_brand` должны создаваться уже на PostgreSQL-only схеме.

   ---

   #### Фаза 1 — Инфраструктура (без изменения кода)

   - [x] **4.5.1** `docker-compose.yml`: expose порт `5432` наружу для сервиса `db` (чтобы можно подключаться с хоста при локальной разработке).
   - [x] **4.5.2** `.env.example`: добавить `DATABASE_URL=postgresql://running_coach:${POSTGRES_PASSWORD}@localhost:5432/running_coach` для локальной разработки.
   - [x] **4.5.3** `README.md`: обновить раздел «Локальная разработка» — теперь требуется PostgreSQL (Docker или локальный).

   **Как проверить:**
   - `docker compose up db` → порт 5432 доступен с хоста (`psql postgresql://...` подключается).

   ---

   #### Фаза 2 — Убрать SQLite из кода

   - [x] **4.5.4** `src/models.py`:
      - Убрать ветку `if database_url.startswith("sqlite")`.
      - Всегда создавать engine для PostgreSQL (`pool_size=10, max_overflow=20`).
      - Убрать `check_same_thread=False`, `PRAGMA journal_mode=WAL`, `PRAGMA synchronous=NORMAL`.
      - Убрать fallback на SQLite при отсутствии `DATABASE_URL` (теперь URL обязателен).
      - Engine создаётся лениво (get_engine()), SessionLocal — ленивый враппер.
   - [x] **4.5.5** `alembic/env.py`:
      - Убрать `_RENDER_AS_BATCH` и `render_as_batch`.
      - Убрать условие `db_url is None or db_url.startswith("sqlite")`.
      - Всегда использовать `render_as_batch=False`.
   - [x] **4.5.6** `alembic.ini`:
      - Убрать `sqlalchemy.url = sqlite:///running_coach.db`.
      - Оставить пустым или прокомментировать: `# set via DATABASE_URL env variable`.

   **Как проверить:**
   - [x] `python3 -c "from src.models import engine; print(engine.url)"` → `postgresql://...`.
   - [x] `alembic current` подключается к PostgreSQL, не падает.
   - [x] Тесты (in-memory SQLite) проходят: `pytest tests/ -v` → 3 passed.

   ---

   #### Фаза 3 — TIMESTAMPTZ: модели и дефолты

   - [x] **4.5.7** `src/models.py`:
      - Убрать функцию `utcnow()` (helper для naive UTC).
      - Все `Column(DateTime, ...)` → `Column(DateTime(timezone=True), ...)` (12 колонок: users.created_at, users.registered_at, training_sessions.begin_ts, deleted_trainings.deleted_at, daily_metrics.synced_at, weight_measurements.measured_at, auth_tokens.expires_at/used_at/created_at, audit_events.created_at).
      - `default=utcnow` → `default=lambda: datetime.now(timezone.utc)`.
   - [x] **4.5.8** `src/startup.py`:
      - `measured_at=utcnow()` → `measured_at=datetime.now(timezone.utc)`.
   - [x] **4.5.7b** Alembic migration `5e287a9fc289`:
      - ALTER все DateTime колонки в PostgreSQL → `TIMESTAMP WITH TIME ZONE`
      - Существующие naive UTC значения интерпретируются как UTC
      - Применена на Docker PostgreSQL (14 колонок), все training_sessions корректно сконвертированы

   **Как проверить:**
   - [x] `python3 -c "from src.models import TrainingSession; print(TrainingSession.__table__.c.begin_ts.type)"` → `DATETIME (timezone=True)`.
   - [x] `psql -c "\d training_sessions"` → `begin_ts: timestamp with time zone`.
   - [x] Существующие записи сохраняют значения и получают timezone `+00`.

   ---

   #### Фаза 4 — Убрать `.replace(tzinfo=None)`

   Всё, что создаёт aware datetime, больше не нужно «обрезать» tzinfo для SQLite.

   - [x] **4.5.9** `src/services/auth.py` (5 мест):
      - `expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + ...` → `expires_at = datetime.now(timezone.utc) + ...`
      - Аналогично в `verify_telegram_login_token`, `check_telegram_login_token`, `cleanup_expired_tokens`.
   - [x] **4.5.10** `src/services/audit.py` (2 места):
      - `created_at=datetime.now(timezone.utc).replace(tzinfo=None)` → `created_at=datetime.now(timezone.utc)`.
      - `timestamp`: `.isoformat().replace("+00:00", "Z")` — оставлено (string replace для ISO 8601 Z-нотации, не tzinfo).
   - [x] **4.5.11** `src/telegram_bot.py` (~10 мест):
      - `user.registered_at = datetime.now(timezone.utc).replace(tzinfo=None)` → `user.registered_at = datetime.now(timezone.utc)`.
      - `wm = WeightMeasurement(..., measured_at=datetime.now(timezone.utc).replace(tzinfo=None))` → `...measured_at=datetime.now(timezone.utc)`.
      - `week_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)` → `week_ago = datetime.now(timezone.utc) - timedelta(days=7)`.
      - `today_start = datetime.now(timezone.utc).replace(tzinfo=None, hour=0, ...)` → `today_start = datetime.now(timezone.utc).replace(hour=0, ...)`.
   - [x] **4.5.12** `src/web/routes/pages.py` (2 места):
      - `wm = WeightMeasurement(..., measured_at=datetime.now(timezone.utc).replace(tzinfo=None))` → `...measured_at=datetime.now(timezone.utc)`.
      - `now = datetime.now(timezone.utc).replace(tzinfo=None)` → `now = datetime.now(timezone.utc)`.
   - [x] **4.5.13** `src/services/coros_sync_auto.py` (5 мест):
      - `datetime.now(timezone.utc).replace(tzinfo=None)` → `datetime.now(timezone.utc)`.
      - `bt` parsing: `strptime(...).replace(tzinfo=timezone.utc)` — добавлено для сравнения с aware DB колонками.
   - [x] **4.5.14** `src/utils/logger.py`:
      - `datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")` — оставлено (string replace для ISO 8601 Z-нотации).
   - [x] **4.5.15** `src/api/routes/health.py`:
      - `datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")` — оставлено (string replace для ISO 8601 Z-нотации).
   - [x] **4.5.16** `src/parsers/tcx_parser.py`:
      - `datetime.now(timezone.utc).replace(tzinfo=None)` → `datetime.now(timezone.utc)`.
   - [x] **4.5.17** `src/coros_client.py`:
      - `datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)` → `datetime.fromtimestamp(ts, tz=timezone.utc)`.

   **Как проверить:**
   - [x] `grep -rn "replace(tzinfo=None)" src/` → **0 совпадений**.
   - [x] `grep -rn "utcnow" src/` → только `datetime.now(timezone.utc)` (helper `utcnow()` в models.py возвращает aware).
   - [x] Docker app+bot запускаются без ошибок, миграции применяются.
   - [x] Audit events сохраняются с timezone `+00` (aware UTC).
   - [x] Tests pass (3/3).

   ---

   #### Фаза 5 — Хелперы для отображения

   - [x] **4.5.18** `src/deps.py:local_dt()`:
      - Было: `dt.replace(tzinfo=timezone.utc).astimezone(tz).replace(tzinfo=None)` (naive → aware → local → naive).
      - Стало: `dt.astimezone(tz)` (aware UTC → aware local), с fallback для naive (SQLite tests).
   - [x] **4.5.19** `src/web/routes/pages.py`:
      - `s.begin_ts.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz_name))` — оставлено (работает для both naive/aware из DB).
      - `begin_local = start_utc_aware.astimezone(local_tz)` в `common.py` — уже aware → aware, не трогать.
   - [x] **4.5.20** `src/parsers/common.py`:
      - `start_time_utc` нормализуется к aware UTC в начале `process_trackpoints()`.
      - `begin_ts` в return dict теперь aware UTC (не naive).
      - Убрано `start_utc_aware.replace(tzinfo=None)` → `begin_ts = start_utc_aware` (aware).

   **Как проверить:**
   - `grep -rn "replace(tzinfo=timezone.utc)" src/ main.py` → **0 совпадений**.
   - Загрузить TCX → на странице тренировки время отображается в MSK (не смещено на 3 часа).

   ---

   #### Фаза 6 — Data migration (naive UTC → aware UTC)

   Существующие записи в PostgreSQL хранят `begin_ts` как naive UTC (тип PostgreSQL `TIMESTAMP WITHOUT TIME ZONE`).
   После смены колонки на `TIMESTAMP WITH TIME ZONE` PostgreSQL будет считать эти значения UTC.
   Нужно «привязать» tzinfo к существующим значениям.

   - [x] **4.5.21** Alembic data migration `5e287a9fc289`:
      - Скрипт ALTER все DateTime колонки: `ALTER TABLE ... ALTER COLUMN ... TYPE TIMESTAMP WITH TIME ZONE USING col AT TIME ZONE 'UTC'`.
      - Применена на Docker PostgreSQL — 27 training sessions корректно сконвертированы (все получили `+00`).

   **Как проверить:**
   - [x] `SELECT begin_ts FROM training_sessions LIMIT 1` → `2026-06-30 12:23:07+00` (содержит `+00`).
   - [x] `SELECT column_name, data_type FROM information_schema.columns WHERE data_type LIKE 'timestamp%'` → все 14 колонок `timestamp with time zone`.

   ---

   #### Фаза 7 — Финальная проверка и тестирование

   - [x] **4.5.22** `docker compose build app bot && docker compose up -d`.
   - [x] **4.5.23** `curl /health/` — `database.status = ok`, `current_revision` корректная.
   - [ ] **4.5.24** Telegram `/start` → регистрация → вход через веб — работает.
   - [ ] **4.5.25** Загрузить TCX-файл через веб → тренировка сохраняется → время на странице в MSK.
   - [ ] **4.5.26** Синхронизация Coros через кнопку → тренировки загружаются → время в MSK.
   - [x] **4.5.27** `daily_weight_job` и `daily_recovery_check_job` — в логах нет ошибок (успешно выполнились).
   - [ ] **4.5.28** `alembic downgrade -1` → `alembic upgrade head` — чистый цикл без ошибок.

   **Регрессионные тесты:**
   - [ ] Старые тренировки (конвертированные в п.8.4) отображаются с правильным временем.
   - [ ] Новые тренировки (загруженные после перехода на TIMESTAMPTZ) отображаются с правильным временем.
   - [ ] `DeletedTraining.begin_ts` — корректно при удалении и повторной загрузке.
   - [ ] `WeightMeasurement.measured_at` — график веса показывает правильные даты.

   ---

   #### Итоговый чеклист перед мержем

   - [x] `grep -rn "replace(tzinfo=None)" src/ main.py` → **0**.
   - [x] `grep -rn "utcnow()" src/ main.py` → только `utcnow()` в `models.py` (возвращает aware datetime).
   - [x] `grep -rn "render_as_batch" alembic/` → **0**.
   - [x] `docker compose ps` → все 3 контейнера `Up`.
   - [x] `curl /health/` → `status: healthy`, `database: ok`, `migrations: ok`.
   - [ ] 1 новая тренировка загружена и отображается с правильным временем.
   - [x] `CHANGELOG.md`, `TECH_DEBT.md` обновлены (AGENTS.md, README.md — актуальны).

---

### Детальное описание Спринта 6

9. **Спринт 6 — Настраиваемая частота синхронизации per-user (бренд-независимая)** (1–2 дня)

   **Важно:** Спринт 6 выполняется **после Sprint 4 п.12+14** (требуется `WatchCredential` + `BaseWatchClient`).  
   Все изменения Спринта 6 делаются на brand-agnostic архитектуре и чистой PostgreSQL-схеме с `TIMESTAMPTZ`.

   - [ ] **6.1** `src/models.py` — новые колонки в `WatchCredential` (не `User`):
      - `activity_sync_interval` (Integer, nullable) — минуты, NULL = по умолчанию (60).
      - `health_sync_interval` (Integer, nullable) — минуты, NULL = по умолчанию (480 = 8 часов, 3 раза в день).
      - `last_activity_sync_at` (DateTime, nullable) — время последней синхронизации тренировок.
      - `last_health_sync_at` уже существует (перенести из `User` при миграции).
   - [ ] **6.2** Alembic миграция — добавить колонки в `watch_credentials`, удалить `last_coros_sync`, `last_health_sync_at` из `users`.
   - [ ] **6.3** `src/config/constants.py` — новые константы:
      - `MIN_ACTIVITY_SYNC_INTERVAL_MIN = 15`
      - `MIN_HEALTH_SYNC_INTERVAL_MIN = 30`
      - `MAX_SYNC_INTERVAL_MIN = 1440`
      - `DEFAULT_ACTIVITY_SYNC_INTERVAL_MIN = 60`
      - `DEFAULT_HEALTH_SYNC_INTERVAL_MIN = 480`
   - [ ] **6.4** `src/services/sync_service.py` — индивидуальные интервалы для каждого brand/пользователя:
      - Перебирать `WatchCredential`, проверять `last_activity_sync_at` + `activity_sync_interval`. Синхронизировать только тех, у кого интервал прошёл.
      - То же для health.
      - После синхронизации обновлять `last_activity_sync_at` / `last_health_sync_at` в `WatchCredential`.
   - [ ] **6.5** Страница настроек — добавить поля частоты синхронизации для каждого бренда:
      - **{Brand} — частота синхр. тренировок (мин)**: `<input ...>`
      - **{Brand} — частота синхр. здоровья (мин)**: `<input ...>`
      - Подсказка: «Оставьте пустым для значений по умолчанию (60 мин / 8 часов)».
   - [ ] **6.6** `POST /settings` — принимать `{brand}_activity_sync_interval` и `{brand}_health_sync_interval` (опционально). Валидация по min/max.
   - [ ] **6.7** Баннер для новых пользователей: если есть `WatchCredential` и 0 тренировок — показать жёлтый баннер: «👋 Нажмите «Синхронизация» для загрузки тренировок.» Исчезает после первой синхронизации.
   - [ ] **6.8** Индивидуальный статус автосинхронизации: на главной показывать время следующей синхронизации для каждого бренда пользователя.
   - [ ] **6.9** `src/telegram_bot.py` — обновить сообщение после сохранения credentials: «Бренд {brand} подключён. Откройте веб-интерфейс и нажмите «Синхронизация».»
   - [ ] **6.10** `CHANGELOG.md` — обновить.

   **Обоснование интервалов:**
   - Тренировки: мин. 15 мин. Каждая синхронизация = 2+ API-вызова к серверу бренда. Чаще 15 мин — риск блокировки. По умолчанию 60 мин.
   - Здоровье: мин. 30 мин, по умолчанию 480 мин (8 часов = 3 раза в день). Метрики не меняются чаще. Логирование новых vs. unchanged записей поможет определить оптимальную частоту.

   **Что не меняется:**
   - Первая синхронизация — ручная через кнопку в UI.
   - Никакого авто-запуска синхронизации при загрузке страницы.
   - Глобальные env-переменные `*_SYNC_INTERVAL` — удалить в пользу per-credential настроек.

---

### Детальное описание Спринта 7

10. **Спринт 7 — Панель администрирования (Admin panel)** (2–3 дня)

   > **Отложен** до появления >1 пользователя или до запуска модуля аналитики.
   - [ ] **7.1** `src/models.py` — колонка `role` (String(20), default='user', значения: 'user', 'admin') в модель User + Alembic миграция. Установить `role='admin'` для user id=1.
   - [ ] **7.2** `src/api/deps.py` — зависимость `get_admin_user`: проверяет `role == 'admin'`, иначе 403. Параллельно с `get_current_user`.
   - [ ] **7.3** `src/api/routes/admin.py` — роутер с префиксом `/admin`, все эндпоинты под `Depends(get_admin_user)`.
   - [ ] **7.4** `/admin` — дашборд: количество пользователей, тренировок, синхронизаций за день (агрегатные запросы по audit_events и таблицам).
   - [ ] **7.5** `/admin/users` — список пользователей (id, email, telegram, дата регистрации, last_sync, is_active, role).
   - [ ] **7.6** `/admin/audit` — просмотр audit_events с фильтром по пользователю/типу/дате (таблица уже есть, нужны только запросы + UI).
   - [ ] **7.7** `/admin/sync` — глобальный статус синхронизаций + принудительный sync для конкретного пользователя.
   - [ ] **7.8** `/admin/users/{id}` — управление пользователем: ban/unban (is_active toggle), сброс пароля, просмотр тренировок и метрик.
   - [ ] **7.9** Очистка старых данных: audit_events старше N дней, удалённые лог-файлы.
   - [ ] **7.10** `CHANGELOG.md` — обновить.

   **Что уже есть (не нужно делать заново):**
   - `AuditEvent` модель + `AuditService` — все ключевые события пишутся в БД
   - `is_active` на User — базовый ban/unban
   - `get_current_user` (session-cookie) — основа для auth admin-панели
   - `_auto_sync_status` (health/activity) — статус синхронизации
   - `/health/` endpoint, `/logs` endpoint
   - Per-user data isolation (`user_id` везде) — можно смотреть данные конкретного пользователя
   - Индексы на `audit_events.created_at` и `audit_events.event_type`

   **Дизайн-решения:**
   - Встроенная HTML-страница `/admin` (как `/settings`, `/logs`), не отдельный фронтенд
   - Доступ через `get_admin_user` dependency (проверка `role == 'admin'`)
   - Минимум стилей, таблицы + фильтры
   - user id=1 получает `role='admin'` при миграции

После этих спринтов можно с чистой совестью начинать **Этап 0** модуля аналитики
(см. `decision_module_design.md`, раздел 12).

---

*Версия: 1.2 · Дата: 01.07.2026 · Проект: AI Running Coach*
