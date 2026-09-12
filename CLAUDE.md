# CLAUDE.md — инструкции для разработки Running Coach

Основной и единственный файл инструкций для агента. Кратко и по делу; глубокие темы — в `docs/*`
(индекс — таблица в конце). `AGENTS.md` — заглушка для инструментов, история — `CHANGELOG.md`.

## Что это за проект
Персональный AI-тренер для бега. Парсит TCX/FIT-файлы (Garmin, Coros, Polar, Suunto), анализирует
тренировки (тип, сегменты, пульсовые зоны от ПАНО/max_hr, GPS-очистка + квалиметрия),
синхронизируется с Coros. Интерфейсы:
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
   В `BACKLOG.md` — только открытое; закрытые строки при чистке уезжают в `docs/archive/BACKLOG_closed.md`
   (нумерация сквозная — новый номер = максимум по обоим файлам + 1).
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
   - По умолчанию `tests/conftest.py` выставляет `os.environ["DATABASE_URL"] = "sqlite:///:memory:"` ДО импорта `src.*`.
   - Единственное исключение (одобрено 05.08.2026): opt-in PG-режим через **отдельную** переменную
     `TEST_PG_URL` (не `DATABASE_URL`!) — только localhost/CI (hard fail иначе), схема строится
     через `alembic upgrade head` (ловит дрейф миграций), схема пересоздаётся на старте сессии.
     Прод-контейнер никогда не выставляет `TEST_PG_URL`.
   - НИКОГДА `os.environ.setdefault("DATABASE_URL", ...)` (no-op в контейнере → тесты пишут в прод);
     в тестах env (в т.ч. `SECRET_KEY`) — только явное `os.environ[...] = ...` (#233), CI-гвард `setdefault` по `src/`.
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
| `src/coach/` | `bot`; при правке `config.py`/порогов и разборов — `app`+`bot` (web читает `services/recovery_view`→coach/config, app-scheduler исполняет разборы) |
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
Это **on-demand делегирование, не обязательный конвейер**.
Зови их, когда окупается; наследуют этот `CLAUDE.md` автоматически:
- **`db-safety-reviewer`** (read-only) — ПЕРЕД принятием правок `startup.py`, `domain/models/**`,
  `alembic/**`, `tests/conftest.py`, sync-слоя или всего, что может потерять данные/сломать миграции.
- **`test-writer`** — написать поведенческие pytest-тесты на готовых фабриках (`tests/helpers.py`) + DI.

## Модуль коуча (гибридный ИИ-тренер) — при работе над ним
- **Нормативный план — `docs/coach/DEV_PLAN.md`** (единственный источник дорожной карты; чек-листы
  C0–C9, агент обновляет статусы в том же коммите, что и код). Прежний rules-first дизайн —
  SUPERSEDED и удалён (06.2026, история git); его §7 — `docs/coach/DESIGN_personalization.md`.
- Архитектура — **гибрид** (решение владельца 23.08.2026): LLM рассуждает и предлагает, скиллы —
  детерминированные read-only tools, safety — жёсткий фильтр поверх. Инварианты (DEV_PLAN §1):
  `Prescription` создаётся только через `safety.clamp()` (обязательное поле `safety`); числа для
  пользователя рендерит детерминированный `render.py`, не проза LLM; LLM не пишет в БД; нет данных →
  потолок безопасности опускается; всё работает без API-ключа (`NullLLM` + fallback).
- Человекочитаемый источник порогов — `docs/coros_health_metrics.md`; **исполняемое зеркало —
  `src/coach/config.py`** (именованные константы; `services/recovery_view.py` и skills читают ТОЛЬКО отсюда;
  документ и код сверяются вручную при правке порога — `tests/test_coach_config.py` проверяет
  только согласованность констант).
- LLM-бэкенды: `get_llm()` = ключ → **мост подписки** (прод; **постоянный режим** — решение
  владельца 25.08.2026, корпоративная подписка; `bin/coach_llm_bridge.py`, ограничение —
  tool-цикл неактивен) → NullLLM/fallback. Решения и причины — `docs/coach/ARCHITECTURE.md`.
- **Недельный план** (`weekly_plan.py` + детерминированные числа `planning.py`; с 11.09 строки плана и утреннее
  подтверждение — `planning_rows.py`, доступность/отмены — `planning_availability.py`, имена реэкспортируются из
  `planning`; вс 19:00 после отчёта, команда `/plan`): строки `recommendations` со `status` planned→confirmed/adjusted;
  утренний вердикт подтверждает план дня. **Показ сохранённого плана — read-only**
  (`week_view.py`, `/week`, флаг `show_week_plan`; `weekly_plan` в чате не персистится,
  а рендерится сохранённый план — инцидент 02.09.2026; прошедшие дни — ✓ факт связанной
  тренировки / ✗ пропущен, не «план с сегодняшними зонами»). `/plan` гасит будущие строки
  прежнего плана (`status='superseded'`, читатели фильтруют); **среди недели `/plan` = остаток
  текущей недели** (с сегодня, если не бегали, по вс; `planning_window.py`, `remaining_*`,
  `days_ahead_allowed`, #293); беговых дней ≤ `run_days_max`
  (адаптивно: max за прошлые недели + 1, в [3, 6], `enforce_run_days`). **Метрики разбора — insights (`INSIGHTS_SCHEMA_VERSION` = 10)**: `services/workout_insights.py`
  композирует `session_metrics` (M1) + `effort`/`gap` + `hr_baseline` + `data_checks`
  (кросс-чеки с часами) + `intervals` (HRR) + `week_structure`/downhill/session_rpe (M4);
  baseline — `services/insights_baseline.py`; флаги — только из `computed.flags`,
  `numeric_check.py` сверяет числа прозы с карточкой и с 11.09 (v2) вырезает предложение с чужим числом
  (применяется в `chat_flow._llm_chat_turn`; выключатель `COACH_NUMERIC_TRIM_PROSE` в `llm/config.py`, хвост
  «Числа — в карточке ниже»). **Автоподнятие max_hr (#237, 11.09)**: тренировки батча пересчитываются по новому
  максимуму до разбора коучем (`services/hr_max.reanalyze_batch_after_raise`, из синка и web-загрузки). Контекст/дедуп/история —
  в `turn_context.py`.
- **Сон — из скриншота** (Coros API длительность/фазы не отдаёт): пользователь шлёт фото экрана
  сна в Telegram → мост `/vision` (Read-tool) → `coach/vision.py`/`services/sleep_ingest.py` → колонки `sleep_*`
  в `DailyMetrics`; **API-ключ НЕ нужен** (через мост подписки); скриншот удаляется из чата,
  напоминание в 10:00 (`telegram/jobs/sleep_reminder.py`), команда `/sleep`.
- **Тренировки по сегментам (M2.1, 01.09.2026)**: `WorkoutProposal.segments` +
  `WorkoutSegment`/`RecoverySpec` (`contracts.py`) вместо свободной строки `structure` (та — legacy,
  читается для совместимости). Числа проставляет детерминированно `segments.py`
  (`enrich_and_clamp_segments`: потолок пульса из зон `zone_ceiling_hr`, ориентир темпа из истории,
  честная деградация «мало данных»/«по ощущениям»; per-segment clamp под safety), рендер —
  `render_segments.py` (компактная карточка, общий итог времени считается ИЗ сегментов; `compact_segments`
  — структура одной строкой для карточки недели `render_week.py` и короткой карточки дня).
  **Решения владельца 02.09.2026:** в карточках — пульс в уд/мин, зона только без max_hr (исключение 06.09: ускорения 15–20 с — по усилию, «5×20 сек свободно (отдых 2 мин трусцой)», без потолка пульса; компактная строка включает отдых; длительность структурного дня — из суммы сегментов в `finalize`);
  ровная пробежка (разм/бег/зам, один блок — `is_monotone`) структуру не сохраняет и не показывает,
  сегменты — только ускорения/интервалы или блоки с разным пульсом. Нормативный
  темп по зонам (VDOT/ПАНО) — #273 закрыт; экспорт тренировки в Coros — BACKLOG #272.
- **Устойчивость к сбою LLM-моста (01.09.2026)**: `LLMTransientError` + ретрай `post_with_retry`
  (`llm/bridge_client.py`, `vision.py`) на транзиентные 502/timeout/сеть (константы
  `COACH_BRIDGE_RETRIES`/`COACH_MORNING_RETRY_*` — `llm/config.py`); при недоступности моста утренний
  вердикт — детерминированный со назначением (`orchestrator.handle_chat` kind="morning"), не
  generic-«базовый режим» (реализация — `chat_flow.py`); отложенный upgrade-повтор `_morning_upgrade_job` (`telegram/jobs/coach_morning.py`).
- **Ярлык тренировки (04.09.2026)**: `training_type` = `analysis/type_resolution.resolve_training_type`
  (сырой `training_type_auto` + план дня; «план — назначение, факт — интенсивность»), применяется в
  `workout_insights_context.apply_type_resolution` (реэкспорт из `workout_insights`); `training_type_source`
  auto|plan|manual, override главнее;
  история переразмечена `services/type_resolution_backfill.relabel_sessions`.
- **Гейт болезни (#322, 07.09.2026)**: LLM только сообщает факт (`CoachTurn.illness`: sick/recovered,
  kind, days_ago), сроки считает код — `coach/illness.py` (состояние в `UserModel.params_json["illness"]`,
  без миграции): болен → правило 21 safety `allow_training=false`; выздоровел → пауза
  `ILLNESS_PAUSE_DAYS[kind]` (гайд 50, нижняя граница), `/plan` исключает закрытые даты, чат/утро
  отбрасывают назначение (`blocked_reason`), `project_state` несёт `day_offset` — дни после паузы открыты.
- **Статус подопечного и лестница качественных дней (12.09.2026, решение владельца)**: персона НЕ говорит
  «после долгого перерыва» — фазу `returning`/`stabilizing`/`stable` считает `coach/training_status.py`
  (полные недели с ≥ 2 пробежками, `STATUS_STABLE_WEEKS` = 4; пауза ≥ 6 дн рвёт серию, пауза ≥ 14 дн держит
  `returning`, пока не пройдёт столько же дней) и кладёт блоком `athlete_status (computed)` в today-контекст
  (всегда; `turn_context.status_phase(extras)` → `build_system_blocks(profile, phase)`). Дайджест гайдов по фазе:
  `key_rules_returning:` (гайды 46/47/61) — только при `returning`. `hard_days_max` в `week_targets` — из
  `coach/quality_ladder.py` (1→3 по переносимости качественных: RPE/боль/`hr_vs_baseline.z`/флаги/утреннее
  восстановление; константы `QUALITY_LADDER_*`, `PLAN_QUALITY_DAYS_CAP` = 3); safety главнее.
- **Полевой тест ПАНО (M3.2, 12.09.2026, решение владельца)**: коуч сам ставит 30-мин тест первым качественным
  днём при `stable` без свежего полевого ПАНО (`lthr_field.is_due` → `week_targets["lthr_test_due"]` → `place_test`
  в `weekly_plan`, тип `race`, маркер `target_json["lthr_test"]`); число считает `analysis/lthr_test.py` (средний
  пульс последних 20 из 30 мин, блок `computed["lthr_test"]`), подтверждение — кнопки `lthr:set:N` из разбора или
  `/lthr N`; запись `params_json["lthr_field"]` без миграции, `latest_lthr` предпочитает её Coros (180 дн), после
  смены якоря пересчёт 28 дней. Константы `LTHR_TEST_*`/`LTHR_FIELD_MAX_AGE_DAYS`; гайд 31.
- **Актуальные проблемы — concerns (10.09.2026)**: колено НЕ захардкожено. LLM сообщает факт
  (`CoachTurn.concern`: new/ongoing/resolved, kind injury|long_break|other, location, label), код ведёт
  `UserModel.params_json["concerns"]` (`coach/concerns.py`, без миграции) и снимает проблему без боли > 0
  и упоминаний `CONCERN_EXPIRE_DAYS` = 14 дн. Тап боли > 0 продлевает/заводит травму (`refresh_from_pain`).
  Пока активна — блок `concerns (params)` в today-контексте (в кэшируемый профиль не кладём), вечерний
  вопрос 21:00 называет её и **без активной проблемы не шлётся** (решение владельца), подпись строки боли
  после RPE — `pain_prompt_label`, `missing: pain` — только при активной травме. Болезнь — отдельно (`illness`).
- **Safety по содержимому (04.09.2026)**: `safety.effective_workout_type` классифицирует
  предложение по рабочим сегментам (отрезки > `STRIDE_MAX_SEC` в Z3+ = tempo/interval), ярлык
  «easy» гейты интенсива не обходит; длительная — качественный день для правила 12; правила 16–20
  (P0 04.09): перекос Z3+ за 7 дней, `easy_run_too_hard` ×2, `quality_volume_exceeded` (+48 ч),
  `downhill_load_high` (+24 ч, колено), монотонность Фостера (`coach/load_monotony.py`); шкала
  Recovery % — Coros §12 (20/70/90). Планирование: `long_run_hold`, `detraining_return` (пауза ≥ 14 дн).
  **Даунгрейд (06.09.2026)**: урезанные tempo/interval/race → `easy`, не `long` (`_downgrade`); потолки
  недели видят вердикт до промпта (`planning_safety.apply_safety_to_targets`, `hard_days_max=0`), карточка
  называет замену и причину (`render_week._clamp_notes`). **Прогноз правил 16/17 по дню плана (07.09.2026, #315)**: доля Z3+ — `hard_share_by_day`, флаги — план
  считает, с какого дня окно флагов `easy_run_too_hard` очистится (`easy_too_hard_counts_by_day`,
  `quality_reopens_at`) → `quality_allowed_from_days_ahead`, каждый день финализируется по
  `project_state`; шапка «интенсив не раньше Чт». Объём плоский (`volume_held_by_safety`, беговых дней не больше
  прошлой недели) **только при правилах усталости/здоровья** (`planning_safety.volume_hold`, 12.09.2026); блок лишь по
  распределению нагрузки (`INTENSITY_ONLY_SAFETY_RULES`: 16/17 и родня) объём не держит — `volume_growth_kept`; доля длительной `long_run_max_pct` (40 % при < 40 км (12.09) или
  ≤ 4 пробежек), лёгкий день ≥ `PLAN_EASY_MIN_MINUTES` 30 мин; допуск лёгкой пробежки
  `EASY_RUN_Z3_TOLERANCE_PCT` 20 % или средний пульс выше потолка Z2.
- **Планирование недели (P1 04.09.2026)**: прошлые недели — `planning_window.local_week_volumes`
  (локальная дата, полные недели); утро подтверждает последнюю действующую строку дня (в т.ч.
  `proposed` из чата); окно доступности — `available_weekdays` → `planning.set_availability`,
  `week_targets.availability`/`days_ahead_allowed`, отмены подопечного переживают `/plan`;
  `target.hr_ceiling` фиксируется при `finalize`. **Потолок длительной — кодом** (06.09.2026): `planning_safety.cap_long_run`
  при финализации плана (км по `predicted`, минуты по `long_run_min_max`), просьбы подопечного
  за 7 дней — `turn_context.recent_athlete_requests` в контексте плана. **Объём недели — кодом** (`cap_week_volume`, лёгкие дни ужимаются до `target_km`);
  при закрытом интенсиве по усталости/здоровью объём плоский (`target_km = prev_week_km`, 06.09.2026; с 12.09 — не для правил 16/17);
  элементы плана несут `segments` (ускорения доходят до карточки).
- **Отмена дней подопечным (03–04.09.2026)**: `CoachTurn.unavailable_days_ahead` →
  `planning.cancel_days` (rest-строки `adjusted` с маркером `UNAVAILABLE_RATIONALE`, прежние
  строки `superseded`); детерминированный гвард `blocked_by_unavailable` — чат/утро на такой день
  тренировку не назначают (инцидент 04.09); обратный путь `available_again_days_ahead` →
  `reopen_days`. Обсуждение целей недели после отчёта — не назначение (промпт `proposal`).
  **Текст-триггер `/plan` не теряется (07.09.2026)**: реплика «переделай план, сегодня не смогу»
  едет `athlete_text` в `generate_weekly_plan` — сохраняется как chat-сообщение, LLM видит её в
  контексте, `unavailable_days_ahead`/`available_*` из ответа применяет код
  (`_apply_availability_from_turn` + `cancel_days` после гашения прежнего плана).
- **Недельный отчёт v2 (C8.1, 03.09.2026)**: вс 19:00 и `/report` — проза LLM (интерпретация: один
  сигнал прогресса, одно слабое место, направление) + детерминированная карточка «Итоги недели»
  (`week_report.py` считает числа по локальной дате, `highlights`/`concerns` предвыбирает код;
  `render_week_report.py`); те же числа получает план следующей недели. Пороги — `coach/config.py`,
  зеркало — `docs/coach/METRICS_GUIDE.md §12`.
- **База знаний (E2/E2.1)**: гайды `src/coach/knowledge/guides/` — seed 00–30, Фицджеральд 40–42/60, Дэниелс
  44–46/61, **Швец 47–50 (07.09.2026: ходьба→бег и возврат после паузы, день гонки, погода/покрытие/
  самоконтроль, болезнь и паузы)**; `key_rules` → дайджест в system[0] (≤ 64 строк, по фазе статуса — 12.09; гвард
  `test_guide_queries.py`), проза — чанки по запросам `knowledge/loader.review_guides_queries` (боль → тип →
  жара) и `plan_guides_queries` (при `detraining_return` — гайды 47 + 61). Новые книги — `books/`
  (gitignored), черновики — `books/_distilled/<книга>/`, ревью перед переносом; в гайдах —
  раздел «Что устарело — не применять».
- **Статусы дорожной карты — только в DEV_PLAN §9** (C0–C9, D0–D8, E0–E3, F0–F7 закрыты к 01.09.2026, E2.1 — 07.09;
  здесь не дублируются). Открыто: персонализация #244/#246 (спека — `docs/coach/DESIGN_personalization.md`,
  ждёт накопления insights), план к цели/гонке #243 (ТЗ зафиксировано, ждёт даты старта),
  M3.2 полевой тест ПАНО (за владельцем). Базовая линия HR↔GAP — v2 (#259/#289, 08.09.2026:
  темп. поправка в фите, сессионная σ, прайор −8, `detraining_shift_bpm`; замер —
  `bin/research_hr_baseline_slope.py`). **Температура (зима, 08.09.2026)**: источник — Open-Meteo, датчик
  часов только фолбэк с адаптивной поправкой (`services/watch_temp_bias.py`) и гвардом ложной жары;
  `cold_flag` → контекст-флаг `cold` + гайд 49; сдвиг пульса ниже +10 °C не экстраполируется до #301.

## Где продолжать (обновляется при смене фокуса)
- **⏩ ТЕКУЩАЯ ТОЧКА ВОЗОБНОВЛЕНИЯ — `docs/coach/TASK_2026-09-12_status_and_lthr.md`, раздел «СЛЕДУЮЩИЙ ШАГ»**:
  решения владельца 12.09.2026 выполнены полностью (статус подопечного + лестница качественных дней, длительная
  40 % до 40 км, рост объёма при интенсиве закрытом правилами 16/17, полевой тест ПАНО M3.2). Всё задеплоено,
  тесты зелёные, закоммичено и запушено 12.09. Дальше — наблюдения п.2 документа и BACKLOG (#337).
- **Порядок работ — `BACKLOG.md`, раздел «Приоритеты»** (P0 безопасность → P1 нагрузка/планы → P2
  данные → P3 приложение). Состояние на 11.09.2026: P0 и P1 закрыты, кроме #243 (ждёт даты
  старта); в P2 открыты только #222 (нужна размеченная выборка), #109/#113 (с ней же), #288/#284 (хвосты
  аудита усреднений), #255/#301 (осадки, мороз).
  10.09 — concerns (`coach/concerns.py`, колено не захардкожено) и аудит документации (README,
  DEV_PLAN §4/§9, ARCHITECTURE, METRICS_GUIDE приведены к коду); 08.09 закрыты #253/#302/#259/#289.
  11.09 — техдолг закрыт: #328/#332 (датонезависимые тесты), #233/#330 (гигиена тестов, CI 3.13), #329 (разнос
  `planning` → `planning_rows`/`planning_availability`, `orchestrator` → `chat_flow`, `workout_insights` →
  `workout_insights_context`, `analysis/utils` → `pace_series`; старые имена реэкспортируются). Тем же днём —
  #331 (отдых в `/week`), #247 v2 (обрезание прозы), #237 (пересчёт батча после автоподнятия max_hr); вечером —
  #236/#327/#274/#252/#333/#239 и аудит 07.2026 (6 устаревших строк закрыты, 6 багов: #78/#114/#120/#106/#127/#124).
  Всё запушено и задеплоено 11.09. **12.09** — статус подопечного из данных (`training_status.py`) и
  лестница качественных дней (`quality_ladder.py`), персона без «после перерыва», дайджест по фазе; BACKLOG #335/#336.
  Дальше: P3 (#116 — решение владельца, #126 — нужен уникальный индекс,
  #125, #84/#85 толстые роуты) или фичи (#255 осадки, #309 тренды в web, #248 override типа в web/`/stats`).
- **Что менялось последним — верх `CHANGELOG.md`** (записи за день идут сверху, новые выше старых).
- Стартер сессии — `~/go.sh` (вне репозитория): статусный блок в его шапке обновляется вместе с
  крупными изменениями; запускает `claude` из корня проекта.

## Документация
| Тема | Файл |
|------|------|
| Правила кода и именование | `docs/CODE_GUIDELINES.md` |
| Архитектура/структура | `docs/ARCHITECTURE.md` |
| Ошибки | `docs/ERROR_HANDLING.md` |
| Тесты | `docs/TESTING.md` |
| Логирование/аудит | `docs/LOGGING.md` |
| Чеклисты | `docs/CHECKLIST_FEATURE.md`, `docs/CHECKLIST_MIGRATION.md`, `docs/CHECKLIST_NEW_PROVIDER.md` |
| Метрики здоровья (пороги) | `docs/coros_health_metrics.md` |
| Бэклог (открытые пункты) | `BACKLOG.md` |
| План и архитектура коуча | `docs/coach/DEV_PLAN.md`, `docs/coach/ARCHITECTURE.md` |
| Ориентир темпа/дистанции — ступени A→B→C (#264, ✅ 04.09.2026) | `docs/coach/TASK_pace_estimate_fallback.md` |
| Рабочий чек-лист 12.09.2026: длительная/объём/тест ПАНО (WP1–WP3, ⏩ в работе) | `docs/coach/TASK_2026-09-12_status_and_lthr.md` |
| Метрики разбора и физиология (#268, F-серия: §6.1 GPS/§7 замыкания/§10/§11 M4) | `docs/coach/METRICS_GUIDE.md` |
| Дизайн персонализации (#244/#246, не реализовано) | `docs/coach/DESIGN_personalization.md` |
| Архив (аудит усреднений 01.09, закрытые пункты BACKLOG) — не ведётся | `docs/archive/README.md` |
| История изменений и спринтов (источник) | `CHANGELOG.md` |
