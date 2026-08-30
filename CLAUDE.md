# CLAUDE.md — инструкции для разработки Running Coach

Основной файл инструкций для Claude-агента. Кратко и по делу; расширенный контекст и история
спринтов — в `AGENTS.md`, глубокие темы — в `docs/*`.

## Что это за проект
Персональный AI-тренер для бега. Парсит TCX/FIT-файлы (Garmin, Coros, Polar, Suunto), анализирует
тренировки (тип, сегменты, пульсовые зоны, GPS-очистка), синхронизируется с Coros. Интерфейсы:
веб (FastAPI + Jinja2) и Telegram-бот. **Гибридный ИИ-коуч работает в проде** (LLM — мост через
подписку Claude Code); нормативный план — `docs/coach/DEV_PLAN.md`.

## Стек и запуск
- Python 3.13 (Dockerfile: python:3.13-slim), FastAPI, SQLAlchemy 2.0, PostgreSQL 16, Alembic;
  Telegram — python-telegram-bot; LLM — anthropic SDK / мост подписки.
- Прод: Docker Compose — 3 контейнера (`db`, `app`, `bot`) + systemd-юнит на хосте
  `running-coach-llm-bridge.service` (LLM-мост, :8765, конфиг `.env.bridge`).
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
   **После пересборки образа поднимать контейнер ТОЛЬКО `docker compose up -d <svc>`**:
   `docker compose start` НЕ пересоздаёт контейнер из нового образа — бот останется на
   старом коде (инцидент 23.08.2026, BACKLOG #240).
   **Миграции с ALTER/DDL: сначала `docker compose stop bot`** — иначе лок → crash-loop
   (инцидент 05.08.2026; восстановление — `docs/CHECKLIST_MIGRATION.md`).
8. **Владение БД-сессией.** `SessionLocal()` — только в композиционных корнях (allowlist —
   тест-гвард `tests/test_session_ownership.py`); сервисы получают `db` параметром. Объекты из
   `telegram/utils.get_user()` — detached: не мутировать (изменения молча теряются).

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
| `src/web/`, `src/api/` | `app` |
| `src/telegram/` | `bot` |
| `src/services/`, `src/parsers/`, `src/analysis/`, `src/watch/`, `src/config/`, `src/domain/`, `src/models.py` | `app` + `bot` (бот сам синкает: sync → parse_fit → analysis) |
| `src/coach/` | `bot` (коуч живёт в боте; веб коуч не использует) |
| `pyproject.toml`, `Dockerfile`, `docker-compose.yml` | `app` + `bot` |
| `bin/coach_llm_bridge.py`, `.env.bridge` | не пересборка — `sudo systemctl restart running-coach-llm-bridge` (агент рестартит БЕЗ пароля: sudoers-правило `bin/sudoers-bridge-restart`, установка — `bin/install_bridge_sudoers.sh`). Мост: `/complete` (текст) + `/vision` (картинка→Read-tool) |
| `alembic/` | `app` (миграции при старте; **с ALTER — сначала stop bot**, §7) |

## Git / коммиты
- **Trunk-based: ведём всё в `main`** (не плодим ветки). Коммить логически завершёнными единицами;
  `CHANGELOG.md` — в том же коммите.
- **Коммить/пушить только по запросу пользователя** (не автоматически).
- Push — просто `git push`: настроен `credential.helper store` (токен в `~/.git-credentials`).
  Первоисточник — `GITHUB_TOKEN` в `.env` (отдельно не спрашивать); при ротации обновить обе
  точки. Токен не вставлять в remote-URL/командную строку.
- Перед рискованными правками (см. data-safety §5–7) — предупредить; крупное/необратимое лучше
  делать во временной ветке и сливать fast-forward.

## Субагенты (роли) — `.claude/agents/`
Это **on-demand делегирование, не обязательный конвейер** (в отличие от ретированного opencode).
Зови их, когда окупается; наследуют этот `CLAUDE.md` автоматически:
- **`db-safety-reviewer`** (read-only) — ПЕРЕД принятием правок `startup.py`, `domain/models/**`,
  `alembic/**`, `conftest.py`, sync-слоя или всего, что может потерять данные/сломать миграции.
- **`test-writer`** — написать поведенческие pytest-тесты на готовых фабриках (`tests/helpers.py`) + DI.

## Модуль коуча (гибридный ИИ-тренер) — при работе над ним
- **Нормативный план — `docs/coach/DEV_PLAN.md`** (единственный источник дорожной карты; чек-листы
  C0–C9, агент обновляет статусы в том же коммите, что и код). `decision_module_design.md` —
  SUPERSEDED (историческая деривация порогов/скиллов, не руководство).
- Архитектура — **гибрид** (решение владельца 23.08.2026): LLM рассуждает и предлагает, скиллы —
  детерминированные read-only tools, safety — жёсткий фильтр поверх. Инварианты (DEV_PLAN §1):
  `Prescription` создаётся только через `safety.clamp()` (обязательное поле `safety`); числа для
  пользователя рендерит детерминированный `render.py`, не проза LLM; LLM не пишет в БД; нет данных →
  потолок безопасности опускается; всё работает без API-ключа (`NullLLM` + fallback).
- Человекочитаемый источник порогов — `docs/coros_health_metrics.md`; **исполняемое зеркало —
  `src/coach/config.py`** (именованные константы; `recovery_view` и skills читают ТОЛЬКО отсюда,
  анти-дрейф-тесты сверяют).
- LLM-бэкенды: `get_llm()` = ключ → **мост подписки** (прод; **постоянный режим** — решение
  владельца 25.08.2026, корпоративная подписка; `bin/coach_llm_bridge.py`, ограничение —
  tool-цикл неактивен) → NullLLM/fallback. Решения и причины — `docs/coach/ARCHITECTURE.md`.
- **Недельный план** (`weekly_plan.py` + детерминированные числа `planning.py`, вс 19:00 после
  отчёта, команда `/plan`): строки `recommendations` со `status` planned→confirmed/adjusted;
  утренний вердикт подтверждает план дня. **Метрики разбора M1** — `analysis/session_metrics.py`
  (время в зонах, дисциплина лёгкого, потолки качества, каденс, RPE, план-vs-факт; флаги — только
  из `computed.flags`, `numeric_check.py` сверяет числа прозы с карточкой). Контекст/дедуп/история
  вынесены в `turn_context.py`.
- **Сон — из скриншота** (Coros API длительность/фазы не отдаёт): пользователь шлёт фото экрана
  сна в Telegram → мост `/vision` (Read-tool) → `vision.py`/`sleep_ingest.py` → колонки `sleep_*`
  в `DailyMetrics`; **API-ключ НЕ нужен** (через мост подписки); скриншот удаляется из чата,
  напоминание в 10:00 (`sleep_reminder.py`), команда `/sleep`.
- **Чек-листы C0–C9 и D0–D8 закрыты 25.08.2026. Дальше (§9 DEV_PLAN): гигиена ✅ 29.08
  (#251/#247/#256/#258), недельный план ✅ (#269), метрики M1/M2.2 ✅ (#268), сон ✅ (#257).
  Осталось: персонализация (#244/#246, ждёт накопления insights), правило «недосып→осторожнее»
  (#254, данные сна теперь есть), план к цели/гонке (#243), M2.1 интервалы, M3 (ПАНО/VDOT).**

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
| План и архитектура коуча | `docs/coach/DEV_PLAN.md`, `docs/coach/ARCHITECTURE.md` |
| Открытое задание: ориентир темпа/дистанции (#264) | `docs/coach/TASK_pace_estimate_fallback.md` |
| Руководство: детерминированные метрики разбора (#268) | `docs/coach/METRICS_GUIDE.md` |
| Расширенный контекст + история спринтов + карта `src/` | `AGENTS.md` |
