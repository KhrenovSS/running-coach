# CLAUDE.md — инструкции для разработки Running Coach

Основной файл инструкций для Claude-агента. Кратко и по делу; расширенный контекст и история
спринтов — в `AGENTS.md`, глубокие темы — в `docs/*`.

## Что это за проект
Персональный AI-тренер для бега. Парсит TCX/FIT-файлы (Garmin, Coros, Polar, Suunto), анализирует
тренировки (тип, сегменты, пульсовые зоны, GPS-очистка), синхронизируется с Coros. Интерфейсы:
веб (FastAPI + Jinja2) и Telegram-бот. Следующий большой этап — **модуль аналитики/рекомендаций**
(«коуч», см. `decision_module_design.md`).

## Стек и запуск
- Python 3.12, FastAPI, SQLAlchemy 2.0, PostgreSQL 16, Alembic; Telegram — python-telegram-bot.
- Прод: Docker Compose — 3 контейнера (`db`, `app`, `bot`).
- Локальная разработка:
  ```bash
  docker compose up db -d
  DATABASE_URL=postgresql://running_coach:<PASSWORD>@localhost:5432/running_coach \
    uvicorn main:app --host 0.0.0.0 --port 8000
  ```
- Тесты: `.venv/bin/python -m pytest -q` (харнесс форсит SQLite in-memory — прод БД не трогается).

## Дисциплина (обязательно)
1. **~400 строк/файл.** Приближается к 400 → выноси логику в новый модуль.
2. **Backlog-дисциплина.** Заметил мелочь (баг/TODO) → строка в `BACKLOG.md`, вернись к задаче.
   **Не чини «заодно»** — это раздувает diff и усложняет ревью.
3. **Секреты.** Нет ключа/токена/пароля → остановись и спроси пользователя. Не выдумывай плейсхолдеры
   (`sk-xxx`, `YOUR_TOKEN_HERE`) в коде или `.env`.
4. **Проверка — поведенческая, не `py_compile`.** Минимум: import-check + запрет-паттерны, например
   ```bash
   .venv/bin/python -c "from src.startup import create_app; create_app()"
   grep -rn "from src.database" src/ | wc -l   # → 0
   ```
   Для бота — smoke: запуск, `/start` отвечает.
5. **Data-safety guard.** Любое изменение с риском потери данных (drop/rename колонок/таблиц, смена
   сигнатур сервисов, правка `startup.py`/`domain/models/base.py`/`alembic/`) → **сначала предупреди
   пользователя**: какие данные затронуты, есть ли миграция/fallback, обратимо ли. Без подтверждения — не применяй.
6. **DB SAFETY — тесты НИКОГДА не трогают production.**
   - По умолчанию `conftest.py` выставляет `os.environ["DATABASE_URL"] = "sqlite:///:memory:"` ДО импорта `src.*`.
   - Единственное исключение (одобрено 05.08.2026): opt-in PG-режим через **отдельную** переменную
     `TEST_PG_URL` (не `DATABASE_URL`!) — только localhost/CI (hard fail иначе), схема строится
     через `alembic upgrade head` (ловит дрейф миграций), схема пересоздаётся на старте сессии.
     Прод-контейнер никогда не выставляет `TEST_PG_URL`.
   - НИКОГДА `os.environ.setdefault("DATABASE_URL", ...)` (no-op в контейнере → тесты пишут в прод).
   - НИКОГДА `drop_all` в autouse-фикстурах.
   - CI дублирует это grep-гвардами (`from src.database`, `except: pass`, `os.environ.setdefault`)
     и гоняет тесты в обоих режимах (SQLite + PostgreSQL/Alembic).
7. **Backup перед деплоем.** Перед `docker compose build/up` → `bin/backup_db.sh`.
   НИКОГДА `docker compose down -v`, НИКОГДА `docker volume rm running-coach_pgdata`.
   Безопасно: `docker compose restart app`, `docker compose build app && docker compose up -d app`.

## Golden rules (код)
1. Константы через `from src.config import settings` / `src.config.constants` — без magic numbers.
2. Ошибки через `src/exceptions.py`. `except: pass` запрещён.
3. Тонкие роуты: валидация → сервис → ответ. Бизнес-логика — в `src/services/<domain>/`.
4. БД: миграции только через Alembic; параметризованные запросы.
5. Логи — `logger` из `src.utils.logger`, не `print()`.
6. Комментарии — bilingual RU/EN.
7. Тесты — unit для логики, integration для endpoint.
8. `CHANGELOG.md` — обновляй в том же коммите.
9. Мульти-брендовость закладывать сразу — не хардкодить «coros».

## Docker rebuild
| Изменён | Пересобрать |
|---------|-------------|
| `src/web,api,parsers,services,analysis,config`, `src/models.py` | `app` |
| `src/telegram/` | `bot` |
| `src/watch/` | `app` + `bot` |
| `pyproject.toml`, `Dockerfile` | `app` + `bot` |
| `alembic/` | `app` (миграции при старте) |

## Git / коммиты
- **Trunk-based: ведём всё в `main`** (не плодим ветки). Коммить логически завершёнными единицами;
  `CHANGELOG.md` — в том же коммите.
- **Коммить/пушить только по запросу пользователя** (не автоматически).
- `GITHUB_TOKEN` для push лежит в `.env`; отдельно не спрашивать.
- Перед рискованными правками (см. data-safety §5–7) — предупредить; крупное/необратимое лучше
  делать во временной ветке и сливать fast-forward.

## Субагенты (роли) — `.claude/agents/`
Это **on-demand делегирование, не обязательный конвейер** (в отличие от ретированного opencode).
Зови их, когда окупается; наследуют этот `CLAUDE.md` автоматически:
- **`db-safety-reviewer`** (read-only) — ПЕРЕД принятием правок `startup.py`, `domain/models/**`,
  `alembic/**`, `conftest.py`, sync-слоя или всего, что может потерять данные/сломать миграции.
- **`test-writer`** — написать поведенческие pytest-тесты на готовых фабриках (`tests/helpers.py`) + DI.

## Модуль аналитики («коуч») — при работе над ним
- Дизайн: `decision_module_design.md` (8 этапов). **Единственный источник порогов/формул для
  skills/rules — `docs/coros_health_metrics.md`**; `skills/` и `rules/p1_safety.py` не должны расходиться.
- Принципы: rules-first (детерминированный движок решает числа), LLM — только интерфейс/объяснение,
  никогда не меняет числа; каждое решение несёт `rationale`; обучение ограничено (min/max + EWMA).
- **Готово к Этапу 1.** Этап 0 (каркас) завершён 03.08.2026: 4 таблицы `src/domain/models/coach.py`
  (Recommendation/PredictionLog/UserModel/Lesson) + миграция; скелет `src/coach/{skills,rules,
  personalization,knowledge,llm}` + контракты `src/coach/contracts.py` (SkillResult/AthleteState/
  Prescription); `tests/skills/` + фикстура `athlete_with_history`. Фундамент (Sprint 20c):
  `config.py` (+`recovery_hours_for`), `repositories.py` (+`FeedbackRepository`, DI), `analytics_helpers.py`,
  structured-выводы `recovery_view.py`.
- **Следующий шаг — Этап 1 (Skills):** превратить пороги из `docs/coros_health_metrics.md` в чистые
  функции `src/coach/skills/*` (сейчас заглушки с `NotImplementedError`), возвращающие `SkillResult`;
  собрать `AthleteState` в `src/coach/state.py`; тесты в `tests/skills/`.

## Документация
| Тема | Файл |
|------|------|
| Правила кода | `docs/CODE_GUIDELINES.md` |
| Архитектура/структура | `docs/ARCHITECTURE.md` |
| API endpoints | `docs/API_ROUTES_GUIDE.md` |
| Ошибки | `docs/ERROR_HANDLING.md` |
| Именование | `docs/NAMING_CONVENTIONS.md` |
| Тесты | `docs/TESTING.md` |
| Логирование/аудит | `docs/LOGGING.md` |
| Чеклисты | `docs/CHECKLIST_FEATURE.md`, `docs/CHECKLIST_MIGRATION.md`, `docs/CHECKLIST_NEW_PROVIDER.md` |
| Метрики здоровья (пороги) | `docs/coros_health_metrics.md` |
| Аудит/бэклог | `PROJECT_AUDIT.md`, `BACKLOG.md` |
| Расширенный контекст + история спринтов + карта `src/` | `AGENTS.md` |
