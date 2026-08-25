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
  LLM обязан видеть, чего не знает; += `signals: dict` — сырьё для чистой safety-функции
  (hrv_status, rhr_status, recovery_pct, ati_cti_ratio, acwr_ratio, consecutive_hard_days,
  pain_level, pain_days; заполняется в `state.py`, LLM в tool `get_athlete_state` НЕ отдаётся —
  модель видит вердикт, не сырьё).
- Новые: `SafetyVerdict(allow_training, max_zone, max_duration_min, allowed_types,
  earliest_next_hard, triggered, reasons)`; `WorkoutProposal(workout_type, target_zone,
  duration_min, distance_km, structure, rationale)`.
- `Prescription` += `safety: SafetyVerdict` (обязательное), `clamped: bool`,
  `source: "llm"|"fallback"`, `earliest: datetime | None`, `proposal: WorkoutProposal | None`
  (что предлагали до урезания). `when` остаётся `date`. Класс объявлен
  `@dataclass(kw_only=True)` — все поля keyword-only, назначение не собрать позиционно.
- `skills/base.py`: модульные функции, не классы — `SkillFn` Protocol + `SKILL_KEYS`
  (6 state-скиллов: fatigue, recovery, load, distribution, progress, pain).
  Сигнатура state-скилла: `evaluate(user_id: int, *, db: Session) -> SkillResult`.
  `skills/workout.py` — per-session разбор, ВНЕ SKILL_KEYS, своя сигнатура
  `evaluate_session(user_id, session_id, *, db)`.

## 4. Граница безопасности P1

`rules/p1_safety.py :: evaluate_safety(state, *, now=None) -> SafetyVerdict` +
`safety.py :: clamp(proposal, verdict, state, *, now=None, source="fallback")
-> tuple[Prescription, bool]` (`now` — параметр ради реплеябельности, `source` пишется в
`Prescription.source`). clamp может только **сужать**:
даунгрейд по лестнице `rest < recovery < easy < long < tempo < interval < race`, усечение зоны и
длительности (дистанция пересчитывается вниз пропорционально), hard-тип при
`now < earliest_next_hard` → `easy`. Любое срабатывание → `clamped=True` +
`ReasoningStep(rule="p1_safety", ...)`. При `clamped=True` рендер добавляет фиксированный
не-LLM-блок «⚠️ Ограничение по безопасности: …».

Триггеры v1 (пороги — только из `coach/config.py`):

| # | Триггер (сигнал из `state.signals`) | Действие |
|---|---|---|
| 0 | `no_data` — нет метрик вовсе (`state.as_of is None`) | `max_zone=2`, без hard-типов и `long` (инвариант §1.5) |
| 1 | `rhr_status == "critical_elevated"` (Δ ≥ `RHR_CRITICAL_DIFF`, порог применяется в `recovery_view.rhr_anomaly`) | `allow_training=False` |
| 2 | HRV `very_low` | `max_zone=2`, без `HARD_TYPES` и `long` (allowed `{rest,recovery,easy}`) |
| 3 | HRV `low` | `max_zone=2`, без `HARD_TYPES` (tempo/interval/race) |
| 4 | `recovery_pct < RECOVERY_PCT_MODERATE` | `max_zone=2` |
| 5 | ati/cti > `ATI_CTI_HIGH` (1.5) | `max_zone=3`, без `interval` |
| 6 | ACWR > `INJURY_RISK_THRESHOLDS['load_ratio_high']` (1.5) | `max_zone=3` |
| 7 | `consecutive_hard_days >= 4` | `max_zone=2` |
| 8 | `pain_level >= PAIN_STOP_LEVEL` (5) | `allow_training=False` |
| 9 | `pain_level >= PAIN_CAUTION_LEVEL` (3) или боль ≥ `PAIN_PERSIST_DAYS` дней подряд | `max_zone=2`, `max_duration_min=40`, без `HARD_TYPES` |
| 10 | `recovery_hours_left > 0` | `earliest_next_hard` |

Константы границы в `coach/config.py`: `PAIN_SCALE_MAX=10`, `PAIN_CAUTION_LEVEL=3`,
`PAIN_STOP_LEVEL=5`, `PAIN_PERSIST_DAYS=3`, `SAFETY_MAX_ZONE_DEFAULT=5`,
`SAFETY_MAX_DURATION_CAUTION_MIN=40`, `TYPE_INTENSITY_ORDER`, `HARD_TYPES`, `EASY_TYPES`,
`TYPE_MIN_ZONE` (минимальная зона типа — clamp даунгрейдит тип, не влезающий под потолок),
`ATI_CTI_HIGH=1.5`, `ACWR_ACUTE_DAYS=7`, `ACWR_CHRONIC_DAYS=28`, `ACWR_CHRONIC_MIN_DAYS=14`,
`RHR_BASELINE_DAYS=30`, `RHR_BASELINE_MIN_POINTS=7`.

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

**Обогащение контекста:** оркестратор перед каждым ходом инлайнит в today-блок результаты
`get_recent_workouts {limit:5}` и `get_weekly_summary {weeks:4}` (`build_today_block(...,
extras=)`). В API-режиме это сокращает tool round-trip'ы; **в режиме моста (см. §8) tool-цикл
неактивен, и обогащение — основной источник фактов для модели.**

## 6. Миграция `p9q0r1s2t3u4_coach_pain_chat_wellness` (down_revision `o8p9q0r1s2t3`)

Только аддитивно: `training_feedback` += `pain_level INTEGER NULL` (0–10), `pain_location VARCHAR(30) NULL`,
`pain_phase VARCHAR(20) NULL` (start/middle/end/after/none); новая `wellness_reports`
(user_id, report_date UNIQUE(user_id, report_date), pain_level, pain_location, soreness, mood,
sleep_quality_self, note); новая `coach_messages` (user_id, created_at, role,
kind chat|morning|evening|review|plan|weekly, text, meta_json, tokens_in, tokens_out, cost_usd,
Index(user_id, created_at)); `recommendations` += `proposal_json`, `safety_json`, `clamped`, `source`.
`downgrade()` пишется, в шапке предупреждение: откат необратимо удаляет данные о боли.

Новый `src/services/repositories_coach.py` (все методы `*, db: Session`): `latest_metrics`,
`metrics_series` (whitelist полей), `weight_series`, `last_sessions`, `session_with_feedback`,
`consecutive_hard_days`, `baseline_rhr`, `acwr`, `turns_today`, `recent_messages`, `save_message`,
`metric_days_count`, `sessions_count`. История боли живёт НЕ в репозитории, а в
`skills/pain.py::recent_pain_by_day/consecutive_pain_days` (union feedback+wellness).
`acwr()` исправляет BACKLOG #219 (дни отдыха = 0, а не исключаются; мало данных →
`ratio=None`, не 0.0); старый `HealthRepository.load_ratio` удалён.
Индексы новых таблиц: составной `(user_id, created_at)`/UNIQUE + одиночный `user_id`
(одиночный сохранён сознательно — стиль всех таблиц проекта).

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

`CoachLLM` Protocol; `get_llm()` — приоритет **API-ключ → мост подписки → NullLLM**:
`AnthropicLLM` (при `ANTHROPIC_API_KEY`), **`BridgeLLM`** (при `COACH_LLM_BRIDGE_URL` —
host-мост `bin/coach_llm_bridge.py` + systemd `running-coach-llm-bridge.service` + `.env.bridge`;
headless `claude -p` под подпиской владельца, модель `BRIDGE_MODEL`, по умолчанию `sonnet` —
бережём лимиты), иначе `NullLLM` (→ `LLMUnavailableError` → `fallback.py`).
Ограничения режима моста: tool-цикл неактивен (компенсация — обогащение §5), prompt-cache
между ходами не гарантирован, `cost_usd` считается по ценам opus → в мосте величина условная
(реальная цена — лимиты подписки). API-режим: модель `claude-opus-5`, `max_tokens=4000`,
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
- ✅ **C3 — Миграция** (код; ⚠️ накат на прод — отдельный шаг, см. ниже): модели + миграция §6 +
  скилл `pain` (SKILL_KEYS += pain, боль доезжает до signals и P1). db-safety-reviewer: **GO**
  (server_default kind + дубль-индекс поправлены по ревью). Проверка: полный набор тестов зелёный в SQLite и
  `TEST_PG_URL` (alembic head, дрейфа нет).
- ✅ 🛑 **Накат C3 на прод — выполнен 23.08.2026** (одобрено владельцем): backup 2,9M →
  `stop bot` → build → `up -d app` (миграция применена, `alembic_version=p9q0r1s2t3u4`) →
  данные целы (4/36/2 без изменений) → **`docker compose up -d bot`** (⚠️ именно `up -d`:
  `start` НЕ пересоздаёт контейнер из нового образа — поймано на этом деплое, BACKLOG #240).

- ✅ **C4 — Telegram без LLM** (код; smoke на живом токене — после наката C3+деплоя):
  `handlers/{pain,coach}.py` (роутер текста: вес приоритетом → коуч; /verdict; callbacks
  pain/painphase/wellness), `jobs/coach_evening.py` (21:00, гейт initiative=high, пропуск
  при записанной боли); feedback: после RPE-тапа строка «Колено?» в том же сообщении
  (2 тапа хороший день, 3 — плохой); `on_workout_completed` в `sync/activities.py` под
  `try/except CoachError`; оркестратор: morning_verdict/handle_chat/on_workout_completed
  детерминированные + get/set_initiative. Проверка: полный набор тестов зелёный, импорт бота OK.
  **Smoke на живом токене — при деплое** (совмещён со стоп-поинтом наката C3):
  `/start`; вес «75.5» сохраняется; «привет» → карточка; RPE-тап → строка боли → тап →
  `pain_level` в БД; `/verdict` работает.
- ✅ **C5 — Tools**: `tools/*`, `knowledge/loader.py`, 4 seed-guide
  (`00_principles`, `10_easy_80_20`, `20_progression`, `30_knee_and_pain` — во front-matter
  `source: hand-written seed`); удалить `rag.py`, `distill.py`, `personalization/`.
  Проверка: каждый tool json-сериализуем; read-only гвард; `get_athlete_state` на фикстуре
  даёт все ключи скиллов.
- ✅ **C6 — LLM за интерфейсом**: `llm/{config,schemas,prompts,client,null,anthropic_client,agent}.py`;
  `+anthropic` в pyproject; `ANTHROPIC_API_KEY=` (пустой) в `.env.example`; настройки в
  `src/config/settings.py`. Проверка: цикл агента на `ScriptedLLM`; `test_prompt_stability`;
  без ключа поведение = C4, один WARNING в логах.
- ✅ 🛑 **СТОП пройден иначе (решение владельца 23.08.2026):** API-ключа нет и не будет
  в ближайшее время — LLM подключён **мостом через подписку Claude Code**
  (`bin/coach_llm_bridge.py` + `running-coach-llm-bridge.service` + `BridgeLLM`;
  `get_llm()`: ключ → мост → NullLLM). Ограничение режима: tool-цикл неактивен,
  компенсирован обогащением today-блока (recent_workouts + weekly_summary).
  Переезд на личный ключ = строка в `.env` (BACKLOG #241).
- ✅ **C7 — Включение LLM** (код; включение — env моста): `jobs/coach_morning.py` (09:30,
  гейт initiative ∈ {normal, high}), `/coach_settings` (4 уровня инициативы кнопками).
  Критерий кэша (`cache_read_input_tokens > 0`) в режиме моста неприменим — заменён на
  «ходы записаны с cost_usd». **Live e2e пройден 23.08 из контейнера бота**: SOURCE=llm,
  проза + карточка «Лёгкий бег Z2 35 мин» + earliest + вопрос про колено; usage/cost в
  `coach_messages`. Граница pain=6 → «Отдых» закрыта юнит-тестами (`test_safety_clamp`,
  `test_pain_flow`); живой повтор — по желанию владельца.
- ✅ **C8 — Разбор + недельный отчёт + инициатива (24.08.2026)**: `on_workout_completed`
  через LLM (kind=review, `workout_detail` инлайнится в extras — мост без tool-цикла),
  `weekly_report` + `jobs/coach_weekly.py` (вс 19:00, kind=weekly, effort=plan),
  `render_weekly` (детерминированный дайджест-fallback). Решения владельца: гейты «как утро» —
  LLM-разбор и отчёт при `initiative ∈ {normal, high}`, при `low` — детерминированная карточка
  разбора без LLM, при `off` — тишина; в разборе/отчёте `proposal` жёстко отбрасывается
  (назначение даёт утренний вердикт/чат); из батча синка LLM-разбор — только самой свежей
  тренировки, остальные детерминированно. Разбор ушёл в daemon-тред
  (`sync/activities.py::_coach_reviews`, свой `SessionLocal` — allowlist
  `test_session_ownership`): мост до 150 с не держит sync/progress. Проверка: 334 теста
  зелёные (+10 в `tests/coach/test_review_weekly.py`), импорт app/bot OK.
  Live-критерий (`/sync` → разбор вторым сообщением; `off` → тишина) — при деплое.
- ✅ **C9 — Финальная сверка доков (23.08.2026)**: три параллельных аудита нашли 55+
  несоответствий — все исправлены. Создан `docs/coach/ARCHITECTURE.md` (ADR: гибрид, ручной
  tool-loop, мост и его ограничения, остаточный риск прозы + полная карта модулей).
  Сверены: CLAUDE.md (самопротиворечие шапки устранено, Python 3.13, мост, up -d),
  AGENTS.md (сессии 06.08/23.08, карты src/), README.md (коуч в возможностях/командах/env/
  systemd-секция, анти-протухание чисел), docs/{ARCHITECTURE,TESTING,ERROR_HANDLING,LOGGING}.md,
  BACKLOG (#240 закрыт; #243–#250 заведены), coros-док (обратная ссылка на config),
  комментарии config/contracts. Grep-набор §11.3 перекалиброван и чист.

Зависимости: C0 первым; C1–C2 и seed-guides независимы; C3→C4; C5→C6→C7 последовательны.

### Разбор тренировки v2 (D0–D8, утверждён владельцем 24.08.2026)

Цель: разбор видит фидбек (RPE/боль), рельеф/погоду/дрейф пульса/сон; итог персистится
(`workout_insights`) и влияет на будущее (carry_forward → утренний вердикт; proposal в
разборе снова разрешён — через clamp). Решения владельца: разбор ждёт тапа RPE/боли или
~30 мин; итоги — новая таблица; влияние — оба канала; сон — разведать Coros API.
Дефолты (правятся словом владельца): грейс 120 с после RPE-тапа; TTL pending 24 ч →
expired молча; `low` — детерминированная карточка сразу; `off` — insights пишутся молча;
carry_forward в утреннем контексте — 3 записи / 7 дней.

- ✅ **D0 — этот чек-лист + ADR** «отложенный разбор через статус в БД» в
  `docs/coach/ARCHITECTURE.md`; CHANGELOG.
- ✅ **D1 🛑 — таблица `workout_insights` (код 24.08.2026; накат на прод — отдельно)** (модель + аддитивная миграция `q0r1s2t3u4v5` +
  `src/services/repositories_insights.py::InsightRepository`: upsert/claim(атомарный)/
  reclaim_stale_running/finish/pending_older_than/expire_older_than/recent/for_session).
  Колонки: session_id UNIQUE, status(pending|running|done|none|expired|error), source,
  attempts, claimed_at, reviewed_at, schema_version, computed_json, assessment_json,
  effort_match, carry_forward String(300), coach_message_id. Стоп-поинт data-safety §5 +
  db-safety-reviewer; накат на прод — отдельно (backup → stop bot → up -d app → up -d bot).
- ✅ **D2 — вычислительный слой (24.08.2026)**: константы в `src/config/constants.py`;
  `src/analysis/gap.py` (сглаживание высоты, Minetti-2002, GAP/уклон по км),
  `src/analysis/effort.py` (moving-сэмплы, cardiac drift/decoupling Pa:HR, heat_flag),
  `src/analysis/hr_baseline.py` (OLS HR↔GAP-темп, хранение в
  `UserModel.params_json['hr_pace_baseline']`), `src/services/workout_insights.py`
  (compute_workout_metrics/upsert/get_or_compute/refresh_baseline, INSIGHTS_SCHEMA_VERSION);
  хуки: `_coach_reviews` (computed при создании строк), `reanalyze` (инвалидация).
  Все ветки деградируют в applicable/available=false без исключений.
- ✅ **D3 — CoachTurn.assessment (24.08.2026)**: `ReviewAssessment{effort_match, causes[], flags[],
  carry_forward}` (enum-списки — финализировать до мержа), `ChatReply.assessment/
  assistant_message_id`, `InsightRepository.finish` из оркестратора (LLM в БД не пишет),
  OUTPUT_CONTRACT+.
- ✅ **D4 — контекст разбора (24.08.2026)**: `get_workout_detail` v2 (полные сегменты: duration_min,
  avg_cadence, elevation_gain/loss; temperature/weather_code дельтой; глобально
  elevation_loss/weather_code/avg_cadence; блок `daily_metrics_morning` через
  `CoachRepository.metrics_for_date`), extras += `workout_computed`.
- ✅ **D5 — отложенный механизм (24.08.2026)**: `src/coach/review_flow.py` (ensure_insights_for_batch,
  run_pending_review c атомарным claim, due_review_sessions), рефакторинг `_coach_reviews`
  (только создаёт строки), `jobs/coach_review.py` (каждые 10 мин: pending>30 мин, re-claim
  running>15 мин, expire>24 ч), триггеры: терминальный тап боли (сразу), RPE-тап
  (run_once 120 с). Исполняет разбор только бот.
- ✅ **D6 — proposal в разборе (24.08.2026)**: `allow_proposal=True` (отмена C8-отброса; weekly-drop
  остаётся), REVIEW_PROMPT v2 (workout_computed + daily_metrics_morning + assessment
  обязателен + proposal при необходимости коррекции).
- ✅ **D7 — каналы влияния (24.08.2026)**: extras morning/chat/weekly/review += `recent_reviews`
  (3 итога / 7 дней: effort_match/flags/carry_forward) + последняя Recommendation
  (for_date>=today) в утренний контекст; weekly читает insights.
- ✅ **D8 🛑 — сон: разведка выполнена 25.08.2026, СОН НЕДОСТУПЕН.** Read-only
  разведка (`bin/coros_probe_sleep.py`, одобрена владельцем) по всем трём штатным
  endpoint'ам (`dashboard/query`, `analyse/dayDetail/query`, `analyse/query`):
  API отдаёт только HRV во сне (`avgSleepHrv`/`sleepHrvBase`/`sleepHrvIntervalList` —
  уже синкается). Длительности/фаз/оценки сна нет → поля не добавляем, разбор
  опирается на HRV/RHR/recovery утра дня тренировки (`daily_metrics_morning`, D4);
  `'sleep'` в `state.missing` остаётся честным. Отдельный sleep-endpoint
  неофициального API — BACKLOG #257.

Зависимости: D0→D1→(D2 ∥ D3 ∥ D4)→D5→D6→D7; D8 — параллелен после разведки.

## 10. Тесты (`tests/coach/`)

Фикстуры — `tests/coach/conftest.py` (сознательный дубль `athlete_with_history` с
уникальными chat_id 92xxx: in-memory БД живёт всю pytest-сессию, drop_all запрещён §6 CLAUDE.md)
+ `tests/helpers.py`.
`fakes.py`: `ScriptedLLM` (записывает `calls`), `FailingLLM`. DI: оркестратор принимает
`llm: CoachLLM | None = None` — как `db`. `test_bridge_client` — BridgeLLM на
`httpx.MockTransport`: JSON в фенсах → parsed, ошибки/таймаут → LLMUnavailableError,
приоритет get_llm (ключ > мост > Null).
Ключевые: `test_skills` (норма + нет данных + пороги из config), `test_state`,
`test_safety_clamp` (табличный; идемпотентность `clamp(clamp(x))==clamp(x)`; при
`allow_training=False` любое предложение → rest), `test_no_prescription_bypass` (source-гвард),
`test_tools` (+ чужая сессия → NotFoundError), `test_tools_readonly` (source-гвард),
`test_agent` (tool_use→tool_result, лимит итераций, невалидный JSON → fallback),
`test_prompt_stability` (побайтная стабильность system-блоков), `test_orchestrator`
(FailingLLM → детерминированный текст; бюджет исчерпан → LLM не вызывается),
`test_pain_flow` (тап → БД → скилл → rest), `test_render`.

### Инцидент 23.08 (первый день в проде) — закрыт хотфиксом
Пользователь получил тишину: LLM отдал rest с нулевыми объёмами → схема отвергла → fallback;
fallback-карточка содержала голый `_` (`tired_rate`) → Telegram BadRequest → ловился только
CoachError → сообщение погибло. Исправлено: `send_md_safe` (Markdown → plain-повтор) во всех
точках отправки коуча + широкий except (бот не имеет права молчать); backticks вокруг
значений в рендере; схема терпима к нулям/null у rest; `asyncio.to_thread` для LLM-вызовов
(синхронный мост морозил event loop бота до 150 с); `days_ago` в брифах тренировок (модель
путала «сегодня/вчера» по ISO-датам); `earliest` конвертируется в часовой пояс пользователя.

## 11. Стоп-поинты, риски, проверки

1. **Data-safety (перед C3):** см. чек-лист C3. `downgrade()` миграции необратимо удаляет данные
   о боли. Пересборка при правке models/services: `app` + `bot`.
2. **Секреты (перед C7):** ключ только от владельца, плейсхолдеры запрещены (§3 CLAUDE.md).
3. **Grep-набор «один план» (гоняется в C0 и C9; перекалиброван в C9):**
   `grep -rn "LLM — только интерфейс\|Следующий шаг — Этап 1\|8 этапов" CLAUDE.md AGENTS.md README.md` → 0;
   `grep -c "SUPERSEDED" decision_module_design.md` → 1.
   «rules-first» из набора исключён: паттерн ловил собственные тексты об отмене; допустим
   ТОЛЬКО в контексте «пересмотрен/отменён».

4. **Перевешивание catch-all** — самое рискованное изменение: после C4 каждый текст = обращение к
   коучу (после C7 — платное). Митигация: приоритет веса, `turns_today`, `COACH_ENABLED`.
5. **Проза LLM может исказить число** — гарантирована только карточка. Numeric-checker → BACKLOG.
6. **Мульти-брендовость:** ни одного `coros` в `src/coach/**`.
7. `training_type_override` в остальном приложении не слит с `training_type` → BACKLOG, не «заодно».

## 12. Принятые допущения (менять по слову владельца)

- Боль — 3 кнопки: `PAIN_LEVELS = (0 «не беспокоило», 2 «немного», 5 «мешало»)`;
  третья = `PAIN_STOP_LEVEL` → немедленный вердикт «Отдых». Колонка Integer держит шкалу 0–10.
  Боль вне тренировки — callback `pain:today:{level}` → wellness_reports. Утренний вердикт — 09:30.
- Многонедельный план не персистится построчно: `coach_messages` c `kind='plan'`; в БД живёт
  только дневная рекомендация.
- Инициатива стартует на `high`.
- Пороги `RECOVERY_PCT_MODERATE=30` / `LOAD_RATIO_HIGH=1.2` не трогаем (потребители — display-слой
  и тесты; для ACWR — отдельный `INJURY_RISK_THRESHOLDS['load_ratio_high']=1.5`). Приведение шкалы
  к Coros (20/70/90) → BACKLOG.
- LLM: три бэкенда за `CoachLLM` Protocol; в проде сейчас — мост подписки
  (`BRIDGE_MODEL=sonnet` по умолчанию); API-режим — `claude-opus-5`. Переезд на ключ — #241.
