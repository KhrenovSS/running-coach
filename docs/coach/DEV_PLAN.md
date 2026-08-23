# DEV_PLAN — гибридный ИИ-коуч (нормативный план разработки)

> **СТАТУС: ДЕЙСТВУЮЩИЙ. Это единственный нормативный документ дорожной карты модуля коуча.**
> Утверждён владельцем 23.08.2026. Все остальные md (README, AGENTS, decision_module_design)
> либо ссылаются сюда, либо помечены SUPERSEDED. **Дублировать дорожную карту в других файлах
> запрещено** — дубли расходятся и дезинформируют агента.
>
> Агент, ведущий разработку: работай по чек-листам §9, обновляй статусы (⬜→✅) **в том же
> коммите, что и код**. При расхождении этого файла с реальностью — сначала исправь файл.

## 0. Цель продукта

«Беговой старший товарищ» в Telegram: видит, как пользователь переносит нагрузки, и подстраивает
их — бег в удовольствие + медленный устойчивый прогресс (темп растёт, пульс/усталость падают).
Сценарии: утренний вердикт, разбор тренировки, свободный чат, план на недели.
Контекст пользователя: цель — сбросить вес и вернуться к прошлым результатам; **колено** — травма
почти прошла (дискомфорт первые 400–800 м, к 5 км уходит), боится перетренированности.
Ключевая проблема данных: **4 оценки RPE из 36 тренировок (11%)** — кнопки не работают, обратную
связь собираем разговором и лёгкими тапами. Ничего про боль в БД нет — добавляем.

## 1. Архитектурные инварианты (нарушать нельзя ни в одном коммите)

Принцип: **LLM владеет рассуждением; детерминированный код владеет фактами (tools), границами
(safety) и числами, которые видит пользователь.** Это сознательная замена rules-first из
`decision_module_design.md` (решение владельца 23.08.2026).

1. **Два типа.** `WorkoutProposal` — предложение (от LLM или fallback). `Prescription` — только
   результат `safety.clamp()`; поле `safety: SafetyVerdict` обязательное, без дефолта.
2. **Единственный конструктор.** `Prescription(...)` создаётся только в `safety.py::clamp()`
   (уточнено в C2: это строже исходной формулировки «prescriber/fallback» — те лишь вызывают
   clamp) — source-гвард `tests/coach/test_no_prescription_bypass.py`.
3. **Числа рендерятся детерминированно.** Карточка тренировки — всегда шаблон `render.py` из
   заклэмпленного `Prescription`. Проза LLM идёт над карточкой и не называет чисел (правило промпта;
   гарантия — карточка, не проза).
4. **LLM не пишет в БД.** Все tools read-only — source-гвард `tests/coach/test_tools_readonly.py`.
   Записи делает оркестратор из провалидированного structured output.
5. **Незнание = опасность.** Нет данных → потолок безопасности опускается, а не снимается.
6. **Каждый ход персистится целиком**, включая предложение LLM **до** урезания
   (`recommendations.proposal_json`) — иначе дрейф советов не измерить.
7. **Всё работает без ключа.** `NullLLM` + `fallback.py`: детерминированный вердикт/разбор/ответ.
   Весь тестовый набор зелёный при отсутствующем `ANTHROPIC_API_KEY`; ни один тест не ходит в сеть.
8. Дисциплина CLAUDE.md действует полностью: ~400 строк/файл, пороги только из `coach/config.py`,
   `db: Session` обязательным keyword-only параметром, ни одного `coros` в `src/coach/**`.

## 2. Судьба каркаса Этапа 0 (что удаляем и почему)

| Файл | Судьба | Причина |
|---|---|---|
| `src/coach/engine.py` | удалить (C2) | каскада правил нет; точка сборки — `prescriber.finalize()` |
| `src/coach/rules/base.py` | удалить (C2) | одно правило → иерархия ABC = мёртвый вес |
| `rules/p2_recovery_timing.py` | удалить (C2) | число считает скилл `recovery`; инвариант «нельзя hard, пока recovery_hours_left > 0» → P1 (`earliest_next_hard`) |
| `rules/p3_training_logic.py` | удалить (C2) | 80/20 и цикл 3:1 — рассуждение по литературе: guides + tool `get_weekly_summary` |
| `rules/p4_plan_goal.py` | удалить (C2) | нет `race_date` и шаблонов планов → BACKLOG |
| `rules/p5_personal.py` | удалить (C2) | `lessons` пуста, продюсера нет; предпочтения — в профильный блок промпта → BACKLOG |
| `knowledge/rag.py` | удалить (C5) | при 1M контекста и ~10 guides эмбеддинги — техдолг |
| `knowledge/distill.py` | удалить (C5) | офлайн-инструмент, место в `bin/`, когда появятся книги → BACKLOG |
| `llm/coach.py` | удалить (C6) | заменяется `llm/agent.py` + `llm/prompts.py` |
| `personalization/` (весь) | удалить (C5) | 4 RPE из 36 — калибровать нечего; вернём, когда фидбек накопится → BACKLOG |
| `rules/p1_safety.py` | **реализовать** (C2) | граница, через которую проходит 100% назначений |

## 3. Контракты (`src/coach/contracts.py`, один файл, ~120 строк)

- `SkillResult` += `unit: str | None` (иначе LLM спутает единицы), `as_of: date | None`
  (защита от «сегодня HRV 62» по позавчерашним данным). `evidence` остаётся `str` —
  шесть `*_structured()` в `recovery_view.py` уже отдают строку; число есть в `value`.
- `AthleteState` += `user_id`, `as_of`, `missing: list[str]` (например `['sleep','stress','rpe']`) —
  LLM обязан видеть, чего не знает.
- Новые: `SafetyVerdict(allow_training, max_zone, max_duration_min, allowed_types,
  earliest_next_hard, triggered, reasons)`; `WorkoutProposal(workout_type, target_zone,
  duration_min, distance_km, structure, rationale)`.
- `Prescription` += `safety: SafetyVerdict` (обязательное), `clamped: bool`,
  `source: "llm"|"fallback"`, `earliest: datetime | None`, `proposal: WorkoutProposal | None`
  (что предлагали до урезания). `when` остаётся `date`.
- `skills/base.py`: модульные функции, не классы — `SkillFn` Protocol + `SKILL_KEYS`.
  Сигнатура скилла: `evaluate(user_id: int, *, db: Session) -> SkillResult`.

## 4. Граница безопасности P1

`rules/p1_safety.py :: evaluate_safety(state) -> SafetyVerdict` + `safety.py :: clamp()`.
`clamp(proposal, verdict, state) -> tuple[Prescription, bool]` может только **сужать**:
даунгрейд по лестнице `rest < recovery < easy < long < tempo < interval < race`, усечение зоны и
длительности (дистанция пересчитывается вниз пропорционально), hard-тип при
`now < earliest_next_hard` → `easy`. Любое срабатывание → `clamped=True` +
`ReasoningStep(rule="p1_safety", ...)`. При `clamped=True` рендер добавляет фиксированный
не-LLM-блок «⚠️ Ограничение по безопасности: …».

Триггеры v1 (пороги — только из `coach/config.py`):

| Триггер | Действие |
|---|---|
| RHR Δ ≥ `RHR_CRITICAL_DIFF` (10) | `allow_training=False` |
| HRV `very_low` | `max_zone=2`, allowed `{rest,recovery,easy}` |
| HRV `low` | `max_zone=2`, без `interval/tempo` |
| `recovery_pct < RECOVERY_PCT_MODERATE` | `max_zone=2` |
| ati/cti > 1.5 | `max_zone=3`, без `interval` |
| ACWR > `INJURY_RISK_THRESHOLDS['load_ratio_high']` (1.5) | `max_zone=3` |
| `consecutive_hard_days >= 4` | `max_zone=2` |
| `pain_level >= PAIN_STOP_LEVEL` (5) | `allow_training=False` |
| `pain_level >= PAIN_CAUTION_LEVEL` (3) или боль ≥ `PAIN_PERSIST_DAYS` дней подряд | `max_zone=2`, `max_duration_min=40` |
| `recovery_hours_left > 0` | `earliest_next_hard` |

Новые константы (C1): `PAIN_CAUTION_LEVEL=3`, `PAIN_STOP_LEVEL=5`, `PAIN_PERSIST_DAYS=3`,
`SAFETY_MAX_ZONE_DEFAULT=5`, `SAFETY_MAX_DURATION_CAUTION_MIN=40`, `HARD_TYPES`,
`TYPE_INTENSITY_ORDER`, `ACWR_CHRONIC_MIN_DAYS=14`.

## 5. Tools для LLM (7, все read-only)

Скилл ≠ tool: все state-скиллы едут внутри `get_athlete_state` — добавление скилла не меняет схем
и не рушит prompt cache. Реестр `tools/registry.py`: `TOOLS` — явный кортеж (порядок фиксирован,
перестановка обнуляет кэш), схемы с `additionalProperties: false` + `required`, `"strict": True`.

`get_athlete_state {}` · `get_safety_verdict {}` · `get_recent_workouts {limit 1..20}` ·
`get_workout_detail {session_id}` (ownership-проверка внутри) ·
`get_metrics_series {metric enum, days 7..180}` (whitelist, никакого getattr от LLM) ·
`get_weekly_summary {weeks 1..16}` (здесь живёт бывший P3) · `search_guides {query, top_k 1..5}`.

Tool-loop — **ручной** (`llm/agent.py`), не `tool_runner`: runner'у некуда прокинуть
request-scoped `Session` (глобал/contextvar нарушают §8 CLAUDE.md). Лимит `COACH_MAX_TOOL_ITERATIONS=6`.

## 6. Миграция `p9q0r1s2t3u4_coach_pain_chat_wellness` (down_revision `o8p9q0r1s2t3`)

Только аддитивно: `training_feedback` += `pain_level SMALLINT NULL`, `pain_location VARCHAR(30) NULL`,
`pain_phase VARCHAR(20) NULL` (start/middle/end/after/none); новая `wellness_reports`
(user_id, report_date UNIQUE(user_id, report_date), pain_level, pain_location, soreness, mood,
sleep_quality_self, note); новая `coach_messages` (user_id, created_at, role,
kind chat|morning|evening|review|plan|weekly, text, meta_json, tokens_in, tokens_out, cost_usd,
Index(user_id, created_at)); `recommendations` += `proposal_json`, `safety_json`, `clamped`, `source`.
`downgrade()` пишется, в шапке предупреждение: откат необратимо удаляет данные о боли.

Новый `src/services/repositories_coach.py` (все методы `*, db: Session`): `latest_metrics`,
`metrics_series` (whitelist полей), `last_sessions`, `session_with_feedback`,
`consecutive_hard_days`, `baseline_rhr`, `acwr`, `pain_history`, `turns_today`, `recent_messages`,
`save_message`. `acwr()` исправляет BACKLOG #219 (дни отдыха = 0, а не исключаются; мало данных →
`ratio=None`, не 0.0); старый `HealthRepository.load_ratio` удаляется (потребителей вне тестов нет).

## 7. Telegram: сбор боли и фидбека

- **Известный дефект:** catch-all `MessageHandler` в `main.py` занят `handle_weight_message`,
  который молча `return`'ит. Решение — роутер `handlers/coach.py::handle_text`: сначала приоритет
  флоу веса (`_is_awaiting_weight`), затем гейт `settings.coach_enabled`, затем бюджет → коуч.
- **После тренировки:** тап RPE → reply_markup того же сообщения меняется на
  `Колено: [🚫 не беспокоило] [🟡 немного] [🔴 мешало]` → при боли строка
  `Когда? [старт][середина][конец][после]`. Хороший день = 2 тапа. Шкалы 0–10 для боли нет —
  вернёт отклик к 11%.
- **Вечером 21:00** (гейт по инициативе): «Колено сегодня?» `[всё ок][ныло][болело]` →
  `WellnessReport`; пропускается, если боль уже записана из тренировки.
- **Свободный текст о боли:** NLP-экстракции нет; LLM возвращает `log_suggestion`, рендер добавляет
  кнопку `[записать дискомфорт 2/10]` — запись только по явному тапу.
- **Инициатива:** `UserModel.params_json['initiative'] ∈ {off, low, normal, high}`, команда
  `/coach_settings`, старт на `high`. `off` = только по запросу.
- **Утренний вердикт — 09:30** (10:00 занято `daily_recovery_check_job`).

## 8. LLM-слой, кэш, лимиты

`CoachLLM` Protocol; `get_llm()` → `AnthropicLLM` при ключе, иначе `NullLLM`
(→ `LLMUnavailableError` → `fallback.py`). Модель `claude-opus-5`, `max_tokens=4000`,
`thinking={"type":"adaptive"}`, `output_config={"effort": "low"|"medium", "format":
{"type":"json_schema","schema": CoachTurn}}`. **Не использовать** (удалено из API, вернёт 400):
`temperature`, `budget_tokens`, assistant prefill, устаревший `output_format`.
Ошибки SDK ловить цепочкой от частного к общему; `except Exception`/`except: pass` запрещены.

Кэш (порядок `tools` → `system` → `messages`): `system[0]` — персона + контракт безопасности +
формат + дайджест `key_rules` (**брейкпойнт 1**); `system[1]` — профиль пользователя
(**брейкпойнт 2**); волатильное (дата, `AthleteState`, `SafetyVerdict`, реплика) — только в
последнем user-блоке. В `system[0]/[1]` ни дат, ни timestamp, ни UUID; схемы с `sort_keys=True`;
набор tools между запросами не меняется. Тест — `test_prompt_stability.py`.
История: окно 8 сообщений из `coach_messages`; guides в промпт целиком не инлайнятся
(проза — через `search_guides`, ≤3 чанка × ≤400 слов).
Лимиты: `COACH_MAX_TURNS_PER_DAY=40`, `COACH_MAX_TOOL_ITERATIONS=6`; каждый ход пишет usage и
`cost_usd` в `coach_messages.meta_json`. Ожидаемая стоимость ≈ $3–10/мес при `initiative=high`.

## 9. Чек-листы коммитов (агент обновляет статус в том же коммите)

- ✅ **C0 — этот документ + сверка руководящих md.** `docs/coach/DEV_PLAN.md`; правка секции коуча
  в `CLAUDE.md`; `AGENTS.md` («следующий шаг» → ссылка сюда); `README.md` (секция «8 этапов» →
  3–5 строк + ссылка); дисклеймер SUPERSEDED в `decision_module_design.md`; BACKLOG #9.
  Проверка: grep-набор из §11.3; `pytest -q` зелёный.
- ✅ **C1 — Фундамент** (без LLM/Telegram): `contracts.py`, `config.py` (+константы §4),
  `skills/base.py`, скиллы `fatigue/recovery/load/distribution/progress/workout` на
  `recovery_view`/`repositories`/`analytics_helpers`, `state.py::assess_state`, `util.py`
  (`effective_training_type` = `override or training_type`), `repositories_coach.py`;
  удалить `HealthRepository.load_ratio` (#219). Проверка: `pytest -q`;
  `python -c "from src.startup import create_app; create_app()"`; тесты скиллов включая
  «нет метрик → unknown/0.0 без исключений».
- ✅ **C2 — Граница**: реализовать `rules/p1_safety.py`; создать `safety.py`, `render.py`,
  `fallback.py`, `prescriber.finalize`; удалить `engine.py`, `rules/base.py`, `p2..p5`;
  поправить `tests/skills/test_scaffold.py`; обновить дерево в `docs/ARCHITECTURE.md`.
  Проверка: `grep -rn "coach.engine|coach.rules.p2|coach.rules.p5" src/ tests/` → 0; табличный
  тест clamp (все триггеры × «interval 10×400 Z5» → разрешённое, `clamped=True`).
- ⬜ **C3 — Миграция** ⚠️ DATA-SAFETY: модели + миграция §6. **Перед накатом: предупредить
  владельца → `bin/backup_db.sh` → `docker compose stop bot` → build/up app → start bot;
  правки моделей прогнать через субагента `db-safety-reviewer`.** Проверка: pytest в SQLite и
  `TEST_PG_URL` (alembic head, дрейфа нет); count(training_feedback) до/после совпадает.
- ⬜ **C4 — Telegram без LLM**: `handlers/{pain,coach}.py`, `jobs/coach_evening.py`,
  `skills/pain.py`; роутер вместо catch-all в `main.py`; `on_workout_completed` в
  `sync/activities.py` под `try/except CoachError` (падение коуча не роняет синк).
  Проверка — smoke на живом токене: `/start`; вес «75.5» сохраняется (старый флоу цел);
  «привет» → детерминированная карточка; RPE-тап → строка боли → тап → `pain_level` в БД;
  `/verdict` работает.
- ⬜ **C5 — Tools**: `tools/*`, `knowledge/loader.py`, 4 seed-guide
  (`00_principles`, `10_easy_80_20`, `20_progression`, `30_knee_and_pain` — во front-matter
  `source: hand-written seed`); удалить `rag.py`, `distill.py`, `personalization/`.
  Проверка: каждый tool json-сериализуем; read-only гвард; `get_athlete_state` на фикстуре
  даёт все ключи скиллов.
- ⬜ **C6 — LLM за интерфейсом**: `llm/{config,schemas,prompts,client,null,anthropic_client,agent}.py`;
  `+anthropic` в pyproject; `ANTHROPIC_API_KEY=` (пустой) в `.env.example`; настройки в
  `src/config/settings.py`. Проверка: цикл агента на `ScriptedLLM`; `test_prompt_stability`;
  без ключа поведение = C4, один WARNING в логах.
- ⬜ 🛑 **СТОП: запросить у владельца `ANTHROPIC_API_KEY`** (Console + биллинг; подписка
  Claude Code API-доступа не даёт; в контейнер — только env-var). Плейсхолдеры запрещены.
- ⬜ **C7 — Включение LLM**: ключ в `.env`, `jobs/coach_morning.py` (09:30), `/coach_settings`,
  выверка seed-guides владельцем. Проверка: живой диалог 3 хода; SQL по `coach_messages` —
  `cache_read_input_tokens > 0` со 2-го хода; ручной тест границы (pain_level=6 + «дай интервалы»
  → карточка «Отдых» + блок ограничения).
- ⬜ **C8 — Разбор + недельный отчёт + инициатива**: `on_workout_completed` через LLM,
  `jobs/coach_weekly.py`, гейт `initiative`. Проверка: `/sync` с новой активностью → разбор +
  кнопки; `initiative=off` → тишина.
- ⬜ **C9 — Финальная сверка доков**: `docs/coach/ARCHITECTURE.md` (ADR: почему гибрид, почему
  ручной tool-loop, остаточный риск прозы — ссылается сюда, не дублирует); сверка
  CLAUDE/AGENTS/docs/ARCHITECTURE (дерево)/docs/TESTING (`tests/coach/`); чистка BACKLOG;
  повторить grep-набор §11.3.

Зависимости: C0 первым; C1–C2 и seed-guides независимы; C3→C4; C5→C6→C7 последовательны.

## 10. Тесты (`tests/coach/`)

Фикстуры — `tests/skills/conftest.py::athlete_with_history` + `tests/helpers.py`.
`fakes.py`: `ScriptedLLM` (записывает `calls`), `FailingLLM`. DI: оркестратор принимает
`llm: CoachLLM | None = None` — как `db`.
Ключевые: `test_skills` (норма + нет данных + пороги из config), `test_state`,
`test_safety_clamp` (табличный; идемпотентность `clamp(clamp(x))==clamp(x)`; при
`allow_training=False` любое предложение → rest), `test_no_prescription_bypass` (source-гвард),
`test_tools` (+ чужая сессия → NotFoundError), `test_tools_readonly` (source-гвард),
`test_agent` (tool_use→tool_result, лимит итераций, невалидный JSON → fallback),
`test_prompt_stability` (побайтная стабильность system-блоков), `test_orchestrator`
(FailingLLM → детерминированный текст; бюджет исчерпан → LLM не вызывается),
`test_pain_flow` (тап → БД → скилл → rest), `test_render`.

## 11. Стоп-поинты, риски, проверки

1. **Data-safety (перед C3):** см. чек-лист C3. `downgrade()` миграции необратимо удаляет данные
   о боли. Пересборка при правке models/services: `app` + `bot`.
2. **Секреты (перед C7):** ключ только от владельца, плейсхолдеры запрещены (§3 CLAUDE.md).
3. **Grep-набор «один план» (гоняется в C0 и C9):**
   `grep -rn "rules-first|LLM — только интерфейс|Следующий шаг — Этап 1" CLAUDE.md AGENTS.md README.md` → 0;
   `grep -c "SUPERSEDED" decision_module_design.md` → 1; `grep -n "8 этапов" README.md` → 0.
4. **Перевешивание catch-all** — самое рискованное изменение: после C4 каждый текст = обращение к
   коучу (после C7 — платное). Митигация: приоритет веса, `turns_today`, `COACH_ENABLED`.
5. **Проза LLM может исказить число** — гарантирована только карточка. Numeric-checker → BACKLOG.
6. **Мульти-брендовость:** ни одного `coros` в `src/coach/**`.
7. `training_type_override` в остальном приложении не слит с `training_type` → BACKLOG, не «заодно».

## 12. Принятые допущения (менять по слову владельца)

- Боль — 3 кнопки (колонка SMALLINT держит 0–10). Утренний вердикт — 09:30.
- Многонедельный план не персистится построчно: `coach_messages` c `kind='plan'`; в БД живёт
  только дневная рекомендация.
- Инициатива стартует на `high`.
- Пороги `RECOVERY_PCT_MODERATE=30` / `LOAD_RATIO_HIGH=1.2` не трогаем (потребители — display-слой
  и тесты; для ACWR — отдельный `INJURY_RISK_THRESHOLDS['load_ratio_high']=1.5`). Приведение шкалы
  к Coros (20/70/90) → BACKLOG.
- LLM: Anthropic `claude-opus-5`; смена провайдера — только через `CoachLLM` Protocol.
