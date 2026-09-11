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
Контекст пользователя: цель — сбросить вес и вернуться к прошлым результатам; боится
перетренированности. Колено (травма на излёте: дискомфорт первые 400–800 м, к 5 км уходит) было
контекстом на старте (08.2026); **с 10.09.2026 травмы/проблемы — данные, а не константы промпта**:
`coach/concerns.py` ведёт активные проблемы в `UserModel.params_json["concerns"]` (без миграции),
LLM только сообщает факт (`CoachTurn.concern`), код снимает проблему с контроля без боли и упоминаний
за `CONCERN_EXPIRE_DAYS` = 14 дн.; в промптах/профиле колено не захардкожено.
Ключевая проблема данных: **4 оценки RPE из 36 тренировок (11%)** — кнопки не работают, обратную
связь собираем разговором и лёгкими тапами. Ничего про боль в БД нет — добавляем.

## 1. Архитектурные инварианты (нарушать нельзя ни в одном коммите)

Принцип: **LLM владеет рассуждением; детерминированный код владеет фактами (tools), границами
(safety) и числами, которые видит пользователь.** Это сознательная замена rules-first из
прежний rules-first дизайн decision_module_design (06.2026, удалён — история git; решение владельца 23.08.2026).

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
   `db: Session` обязательным keyword-only параметром; код коуча бренд-независим (в логике
   `src/coach/**` нет `coros`; единственное исключение — `vision.py`: промпт распознавания скриншота
   сна конкретного приложения, при новом бренде — параметризовать; упоминания в комментариях и
   ссылки на `docs/coros_health_metrics.md` — не код).

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

## 3. Контракты (`src/coach/contracts.py`, один файл, ~170 строк)

- `SkillResult` += `unit: str | None` (иначе LLM спутает единицы), `as_of: date | None`
  (защита от «сегодня HRV 62» по позавчерашним данным). `evidence` остаётся `str` —
  шесть `*_structured()` в `recovery_view.py` уже отдают строку; число есть в `value`.
- `AthleteState` += `user_id`, `as_of`, `missing: list[str]` (например `['sleep','stress','rpe']`) —
  LLM обязан видеть, чего не знает; += `signals: dict` — сырьё для чистой safety-функции
  (hrv_status, rhr_status, recovery_pct, ati_cti_ratio, acwr_ratio, consecutive_hard_days,
  pain_level, pain_days; с 01.09 также poor_interval_recovery, days_since_quality,
  quality_days_7d, post_race_days_left, days_off — сырьё правил 11–14; с 02–07.09 также
  sleep_duration_min (правило 15), recovery_ready_at (#306 — якорь срока интенсива от начала
  последней тренировки), hard_share_7d, easy_too_hard_7d, quality_volume_exceeded_recent,
  downhill_load_recent, monotony_7d, trained_days_7d (правила 16–20),
  illness_block_days/illness_status/illness_pause_until (правило 21, `illness.illness_signals`);
  заполняется в `state.py`/`_week_signals`, LLM в tool `get_athlete_state` НЕ отдаётся —
  модель видит вердикт, не сырьё. `day_offset` в сигналы добавляет не state, а
  `planning_safety.project_state` — день плана, по которому финализируется каждый день недели,
  там же по дню подменяются `easy_too_hard_7d`/`hard_share_7d`, #315).
- Новые: `SafetyVerdict(allow_training, max_zone, max_duration_min, allowed_types,
  earliest_next_hard, triggered, reasons)`; `WorkoutProposal(workout_type, target_zone,
  duration_min, distance_km, target_pace_min_km, structure, segments, rationale, for_days_ahead)`.
- **Сегменты тренировки (M2.1 назначения, 01.09.2026)**: `WorkoutSegment(role, repeat, amount_kind,
  amount_value, target_zone, pace_target_min_km, effort, recovery)` и `RecoverySpec(until_hr,
  duration_min, distance_km, target_zone)` — качественная структура от LLM; числа проставляет
  детерминированно `segments.py` (§4). Строковая `WorkoutProposal.structure` — legacy (старые записи,
  читается для совместимости). Также `PaceClampContext(expected_hr, safe_pace_min_km, zone_ceiling_bpm)`
  — прекомпьют для safety-ветки темпа (clamp остаётся без БД).
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

**Посегментный слой (M2.1 назначения, 01.09.2026)**: если предложение содержит `segments`,
после скалярного `clamp()` их обогащает и клэмпит `src/coach/segments.py::enrich_and_clamp_segments`
(вызов из `prescriber.finalize` ПОСЛЕ clamp, симметрично `predict_volume`): per-segment
`zone = max(1, min(zone, verdict.max_zone))`, потолок пульса из зоны (`zone_ceiling_hr` —
с 01.09 от LTHR-лестницы при валидном lthr), ориентир темпа из истории
(`expected_pace_at_hr`); нет истории на потолке зоны → нормативный темп от порогового
`ltsp` (`pace_hint = ltsp + LTSP_ZONE_OFFSET_S[зона]`, `pace_source="threshold"`, F4/M3.1);
иначе честные пометки `pace_missing`/`hr_missing`;
если итоговый тип понижен по лестнице интенсивности — сегменты сбрасываются (их числа недостоверны,
как drop-on-clamp для строковой `structure`). Результат кладётся в `prescription.target["segments"]`;
рендер — `render_segments.py` (общий итог времени тренировки считается ИЗ сегментов).
**02.09.2026 (решения владельца):** монотонная структура (разминка/бег/заминка, ≤1 ровного блока —
`render_segments.is_monotone`) не сохраняется и не показывается — ровная пробежка целиком
«пульс до N · время»; в карточках пульс в уд/мин, ярлык зоны — только без max_hr.

Триггеры v1 (пороги — только из `coach/config.py`):

| # | Триггер (сигнал из `state.signals`) | Действие |
|---|---|---|
| 0 | `no_data` — нет метрик вовсе (`state.as_of is None`) | `max_zone=2`, без hard-типов и `long` (инвариант §1.5) |
| 1 | `rhr_status == "critical_elevated"` (Δ ≥ `RHR_CRITICAL_DIFF`, порог применяется в `recovery_view.rhr_anomaly`) | `allow_training=False` |
| 2 | HRV `very_low` | `max_zone=2`, без `HARD_TYPES` и `long` (allowed `{rest,recovery,easy}`) |
| 3 | HRV `low` | `max_zone=2`, без `HARD_TYPES` (tempo/interval/race) |
| 4 | `recovery_pct` — шкала Coros §12 (#249, 04.09.2026), два шага: `< RECOVERY_PCT_MODERATE` (20, Exhausted) → `recovery_low`; иначе `< RECOVERY_PCT_READY` (70, Fatigued) → `recovery_fatigued`; ≥ 70 — молчит | `recovery_low`: `max_zone=2`, без `HARD_TYPES`; `recovery_fatigued`: без `HARD_TYPES` |
| 5 | ati/cti > `ATI_CTI_HIGH` (1.5) | `max_zone=3`, без `interval` |
| 6 | ACWR > `INJURY_RISK_THRESHOLDS['load_ratio_high']` (1.5) | `max_zone=3` |
| 7 | `consecutive_hard_days >= 4` | `max_zone=2` |
| 8 | `pain_level >= PAIN_STOP_LEVEL` (5) | `allow_training=False` |
| 9 | `pain_level >= PAIN_CAUTION_LEVEL` (3) или боль ≥ `PAIN_PERSIST_DAYS` дней подряд | `max_zone=2`, `max_duration_min=40`, без `HARD_TYPES` |
| 10 | `recovery_hours_left > 0` | `earliest_next_hard` |
| 11 | `poor_interval_recovery` — плохой HRR в недавнем разборе (F3, окно `HRR_POOR_RECOVERY_LOOKBACK_DAYS`) | `earliest_next_hard` ≥ +`HRR_POOR_RECOVERY_EXTRA_H` (48 ч) |
| 12 | `days_since_quality < QUALITY_MIN_GAP_DAYS` или `quality_days_7d > QUALITY_MAX_PER_WEEK` (M4.1; длительная — тоже качественный день, 04.09) | `hard_days_too_close`: `earliest_next_hard` ≥ +max(1, `QUALITY_MIN_GAP_DAYS` − `days_since_quality`) дн. |
| 13 | `post_race_days_left > 0` — восстановление после гонки, 1 лёгкий день/3 км (M4.1) | `max_zone=2`, без `HARD_TYPES` |
| 14 | `days_off ≥ DETRAINING_MIN_DAYS_OFF` (6) — возврат после паузы (M4.3) | `max_zone=2`, без `HARD_TYPES` |
| 15 | `sleep_duration_min` < `SLEEP_SHORT_MIN`/`SLEEP_VERY_SHORT_MIN` (#254, скриншот сна за сегодня; нет данных → молчит) | без `HARD_TYPES`; при <5 ч ещё `max_zone=2`, ≤40 мин |
| 16 | `hard_share_7d > HARD_SHARE_OVERLOAD` (0.30 — доля времени Z3+ за `HARD_SHARE_LOOKBACK_DAYS` 7 дн; считается только при ≥ `HARD_SHARE_MIN_MINUTES_7D` 60 мин зон; гайд 10, 04.09.2026) | `week_intensity_overload`: `max_zone=2`, без `HARD_TYPES` |
| 17 | `easy_too_hard_7d ≥ EASY_TOO_HARD_WEEK_FLAGS` (2 флага `easy_run_too_hard` в разборах за `EASY_TOO_HARD_LOOKBACK_DAYS` 7 дн; #289, гайд 10) | `easy_runs_too_hard`: `max_zone=2`, без `HARD_TYPES` |
| 18 | `quality_volume_exceeded_recent` — флаг `quality_volume_exceeded` в разборе за `QUALITY_VOLUME_LOOKBACK_DAYS` 3 дн (#289, гайд 44) | `quality_volume_exceeded`: `earliest_next_hard` ≥ +`QUALITY_VOLUME_EXTRA_H` (48 ч) |
| 19 | `downhill_load_recent` — флаг `downhill_load_high` в разборе за `DOWNHILL_LOOKBACK_DAYS` 2 дн (#289, гайд 46 — колено) | `downhill_load`: `max_zone=3`, `earliest_next_hard` ≥ +`DOWNHILL_EXTRA_H` (24 ч) |
| 20 | `monotony_7d > MONOTONY_HIGH` (2.0) и `trained_days_7d ≥ MONOTONY_MIN_TRAIN_DAYS` (5) — монотонность Фостера (#308, `coach/load_monotony.py`) | `monotony_high`: без `HARD_TYPES` |
| 21 | `illness_block_days` задан и `day_offset < illness_block_days` (#322, гайд 50; `illness_status` sick → до сообщения о выздоровлении, recovered → до `illness_pause_until` = `ILLNESS_PAUSE_DAYS[kind]`; `day_offset` — день плана из `planning_safety.project_state`, вне плана 0) | `illness`: `allow_training=False` |

Константы правил 11–21: `HRR_POOR_RECOVERY_EXTRA_H/LOOKBACK_DAYS`, `SLEEP_SHORT_MIN`,
`SLEEP_VERY_SHORT_MIN`, `PAIN_FRESH_DAYS` (свежесть боли — фикс 02.09), `HARD_SHARE_OVERLOAD=0.30`,
`HARD_SHARE_LOOKBACK_DAYS=7`, `HARD_SHARE_MIN_MINUTES_7D=60`, `EASY_TOO_HARD_WEEK_FLAGS=2`,
`EASY_TOO_HARD_LOOKBACK_DAYS=7`, `QUALITY_VOLUME_LOOKBACK_DAYS=3`, `QUALITY_VOLUME_EXTRA_H=48`,
`DOWNHILL_LOOKBACK_DAYS=2`, `DOWNHILL_EXTRA_H=24`, `MONOTONY_HIGH=2.0`, `MONOTONY_MIN_TRAIN_DAYS=5`,
`ILLNESS_PAUSE_DAYS={cold:14, flu:14, angina:21, pneumonia:30, other:7}` — `coach/config.py`;
`QUALITY_MAX_PER_WEEK`, `QUALITY_MIN_GAP_DAYS`, `POST_RACE_KM_PER_EASY_DAY`,
`DETRAINING_MIN_DAYS_OFF` — `src/config/constants.py` (чистая математика M4).
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
`get_workout_detail {session_id}` (ownership внутри; + `gps_quality`, `zone_minutes`
посекундные из `computed_json` c fallback на сегменты, зоны от LTHR) ·
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
  `Колено?/Боль или дискомфорт? [🚫 не беспокоило] [🟡 немного] [🔴 мешало]` (подпись — из активной
  проблемы, `coach/concerns.py`) → при боли строка
  `Когда? [старт][середина][конец][после]`. Хороший день = 2 тапа. Шкалы 0–10 для боли нет —
  вернёт отклик к 11%.
- **Вечером 21:00** (гейт по инициативе; **только при активной проблеме** — concerns, 10.09.2026):
  «Голеностоп сегодня?» `[всё ок][ныло][болело]` → `WellnessReport`; пропускается, если боль уже
  записана из тренировки; без активной проблемы не шлётся.
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
**Устойчивость к сбою моста (01.09.2026)**: транзиентные ответы моста (HTTP 502/503/504, timeout,
сетевой отказ) → подкласс `LLMTransientError(LLMUnavailableError)` (`src/exceptions.py`) и ретрай
с backoff `post_with_retry` (`llm/bridge_client.py`, применён и в `vision.py`; константы
`COACH_BRIDGE_RETRIES`/`COACH_BRIDGE_RETRY_BACKOFF_S` в `llm/config.py`). Постоянные (401/400,
нет ключа) — обычный `LLMUnavailableError`. Утренний вердикт при сбое — детерминированный со
назначением (`orchestrator.handle_chat` kind="morning" → `morning_verdict()`), не generic-«базовый
режим»; при транзиентном сбое `morning_verdict_job` ставит отложенный `_morning_upgrade_job`
(`run_once`, добор LLM-вердикта когда мост поднимется; `COACH_MORNING_RETRY_*`); `ChatReply.retriable`.
Мост-endpoints: `/complete` (текст, `--tools "" --max-turns 1`) и `/vision` (#257: картинка
base64 → temp-файл на хосте → `claude -p --allowedTools Read --add-dir <tmp>` — исключение из
«no tools», Read разрешён только на temp-каталог; для распознавания сна из скриншота).
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
  в `CLAUDE.md`; `AGENTS.md` («следующий шаг» → ссылка сюда); `README.md` (секция прежнего поэтапного плана →
  3–5 строк + ссылка); дисклеймер SUPERSEDED в decision_module_design (файл удалён 02.09.2026, история git); BACKLOG #9.
  Проверка: гвард `tests/test_docs_links.py` (бывший ручной grep-набор — §11, п. 3); `pytest -q` зелёный.
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
  при записанной боли, только при активной проблеме); feedback: после RPE-тапа строка боли
  (подпись из concerns) в том же сообщении
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
  Переезд на личный ключ = строка в `.env` — **не планируется** (решение владельца
  25.08.2026: корпоративная подписка, мост — постоянный режим; #241 ⏸).
- ✅ **C7 — Включение LLM** (код; включение — env моста): `jobs/coach_morning.py` (09:30,
  гейт initiative ∈ {normal, high}), `/coach_settings` (4 уровня инициативы кнопками).
  Критерий кэша (`cache_read_input_tokens > 0`) в режиме моста неприменим — заменён на
  «ходы записаны с cost_usd». **Live e2e пройден 23.08 из контейнера бота**: SOURCE=llm,
  проза + карточка «Лёгкий бег Z2 35 мин» + earliest + вопрос про колено (с 10.09 — только при
  активной проблеме, `concerns.py`); usage/cost в
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
  `test_session_ownership`): мост до 150 с не держит sync/progress. Проверка: тесты
  зелёные (334 на момент C8) (+10 в `tests/coach/test_review_weekly.py`), импорт app/bot OK.
  Live-критерий (`/sync` → разбор вторым сообщением; `off` → тишина) — при деплое.
- ✅ **C8.1 — Недельный отчёт v2 (03.09.2026)**: `coach/week_report.py` (числа недели по локальной
  дате: объём, доля лёгкого ВРЕМЕНИ по зонам, качество/длительная, баллы нагрузки, экономичность
  = средний `hr_vs_baseline.delta_bpm`, ACWR, цели недели, сверка с планом, `highlights`/`concerns`
  по порогам config) + `render_week_report.py` (карточка «Итоги недели», строки без данных
  опускаются) + `WEEKLY_PROMPT` «интерпретация, не пересказ» + `/report`. Джоб вс 19:00 считает
  числа один раз для отчёта и плана (`generate_weekly_plan(week_report=)`). Решения владельца:
  полная карточка, только тренировки (без HRV/RHR/сна), сравнение — прошлая + среднее 4 нед +
  ряд 6 недель. Монотонность/страйн (#308) — ✅ 04.09.2026 (`coach/load_monotony.py`,
  `monotony`/`strain` в `week_report`, правило 20 safety). Открыто: тренды в web (#309).
- ✅ **C9 — Финальная сверка доков (23.08.2026)**: три параллельных аудита нашли 55+
  несоответствий — все исправлены. Создан `docs/coach/ARCHITECTURE.md` (ADR: гибрид, ручной
  tool-loop, мост и его ограничения, остаточный риск прозы + полная карта модулей).
  Сверены: CLAUDE.md (самопротиворечие шапки устранено, Python 3.13, мост, up -d),
  AGENTS.md (сессии 06.08/23.08, карты src/), README.md (коуч в возможностях/командах/env/
  systemd-секция, анти-протухание чисел), docs/{ARCHITECTURE,TESTING,ERROR_HANDLING,LOGGING}.md,
  BACKLOG (#240 закрыт; #243–#250 заведены), coros-док (обратная ссылка на config),
  комментарии config/contracts. Grep-набор (ныне гвард `tests/test_docs_links.py`, §11 п. 3)
  перекалиброван и чист.

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
- ✅ **30.08.2026 — #257 РЕШЁН иначе (перехват API отклонён владельцем):** сон вводится
  из **скриншота** экрана сна (Telegram фото → мост `/vision`, Read-tool → `vision.py` →
  `sleep_ingest.save_sleep_shot`). Колонки `DailyMetrics.sleep_duration_min/deep/light/rem/
  awake_min`, `sleep_score`, `sleep_extra`(JSON), `sleep_source='coros_screenshot'` (миграции
  `r1s2t3u4v5w6`, `s2t3u4v5w6x7`). `state.missing` убирает `'sleep'` при наличии данных.
  Скриншот удаляется из чата, напоминание в 10:00 (`sleep_reminder.py`), `/sleep`. API-ключ
  НЕ требуется (через мост подписки). Следующее — правило безопасности #254 «недосып→осторожнее».

Зависимости: D0→D1→(D2 ∥ D3 ∥ D4)→D5→D6→D7; D8 — параллелен после разведки.

- ✅ 🛑 **Накат D-серии на прод — выполнен 25.08.2026** (одобрен владельцем):
  backup 3,0M → stop bot → build app+bot → `up -d app` (миграция
  `alembic_version=q0r1s2t3u4v5`, workout_insights создана) → данные целы
  (37/5/105/32) → **`up -d bot`** (все джобы зарегистрированы, вкл. сборщик
  отложенных разборов каждые 10 мин; первый прогон без ошибок; мост active).
  Live-проверка v2 — следующая реальная тренировка: `/sync` → RPE-тап → тап
  боли → разбор ~через 2 мин с метриками (дрейф/GAP/жара) и фидбеком;
  без тапов → разбор через ~30-40 мин; утро → вердикт учитывает carry_forward.

### E-серия — дистилляция книг владельца в базу знаний (#245+#242, утв. 25.08.2026)

Владелец предоставит 3–6 книг (`books/`, gitignored — копирайт; форматы EPUB/FB2/TXT/MD/
PDF-текст). Книги → конспекты-гайды своими словами (числовые правила в каждый промпт,
проза — чанками в контекст); готовые планы из книг → plan-гайды (объёмы в % от текущего
недельного объёма), тренер адаптирует через safety.

- ✅ **E0 — приём книг (25.08.2026)**: `books/` + README + .gitignore (исходники не в git);
  extras-группа `distill` в pyproject (ebooklib/pypdf/bs4 — только локально).
- ✅ **E1 — `bin/distill_books.py` (25.08.2026)**: извлечение текста (epub/fb2/pdf/txt) →
  map-конспекты окнами ~12К слов → reduce в guide-файлы (формат loader: front-matter +
  key_rules + `## `-чанки; планы — `60_plans_*` в % от объёма) через мост (:8765).
  Черновики → `books/_distilled/<книга>/` — 🛑 ручное ревью перед переносом в guides/.
  E2E-прогон на синтетической книге: 3 корректных черновика, загрузчик парсит,
  план переведён в проценты.
- ✅ **E2 — дистилляция реальных книг (25.08.2026)**: Фицджеральд «Бег по правилу
  80/20» + Дэниелс «От 800 метров до марафона» (Ноукс — дайджест Smart Reading,
  пропущен). 8 гайдов: методика `40–42` (Фиц) / `44–46` (Дэн), планы `60/61` —
  измерение интенсивности, зоны+VDOT, структура недели/сезона, кросс-тренинг,
  техника/возврат после травмы, готовые планы в % от объёма. Ревью (агент+владелец):
  без цитат, key_rules урезаны до 49 строк (ориентир ≤50; автоматического гварда нет), темы дополняют seed.
  WEEKLY_PROMPT доработан под plan-гайды. Тесты коуча — 125 passed.
  Доработан `bin/distill_books.py`: FB2-экстрактор берёт только `<body>` (было —
  тянул base64-картинки, до 88% «объёма» → модель отклоняла окна по AUP `[bio]`);
  + retry/бэкофф и чекпойнт map-конспектов в `_notes/` (возобновляемый прогон).
- ✅ **E2.1 — вторая партия книг (07.09.2026)**: Швец «Я бегу марафон» (1983, оздоровительный
  бег) → гайды `47_walk_run_entry` (вход и возврат через ходьбу→бег, пятиэтапная программа,
  регулярность, порог привычки), `48_race_day` (раскладка гонки, «стена» с 30 км, питьё, финиш),
  `49_conditions_selfcheck` (ветер/мороз/жара, покрытие и обувь, крепатура vs связки, пульс через
  10 мин после бега), `50_illness_pauses` (сроки перерыва после болезни, температура, застолье,
  скрининг). В каждом — раздел «Что устарело — не применять» (питьё «терпеть до 22 км», голодание,
  2–3 марафона в месяц, ледяной душ после бега, бег с температурой и т. п.). Лаймон «Марафон» —
  художественный рассказ, отклонён. Гайды написаны агентом по полному инвентарю книги без
  map/reduce `distill_books.py` (REDUCE знает только 4 seed-темы → дублировал бы 40–46).
  Подключение: `_TYPE_GUIDE_TERMS["race"]` → гайд 48; флаг жары в разборе → третий запрос
  (гайд 49); план недели при `detraining_return` → `plan_guides_queries` (гайды 47 + 61;
  `build_extras.guides_query` принимает список). Дайджест — 60 строк (ориентир поднят до ≤ 60,
  гвард `tests/coach/test_guide_queries.py`). Детерминированный гейт болезни — ✅ 07.09.2026 (#322:
  `coach/illness.py`, `ILLNESS_PAUSE_DAYS`, правило 21 safety, `CoachTurn.illness`).
- ✅ **E3 — чанки методики инлайном (#242, 25.08.2026)**: `_build_extras` +=
  `method_guides` — для разбора запросы из фактов (`knowledge/loader.review_guides_queries`:
  боль отдельным запросом + тип тренировки, по 1 чанку, максимум 2), для weekly —
  «объём прогрессия неделя план». Промпты REVIEW/WEEKLY вынесены в `llm/prompts.py`
  (лимит 400 строк orchestrator).

### F-серия — сырые данные и физиология (утв. 01.09.2026)

Итог аудита сырых данных 01.09.2026 (`docs/archive/AUDIT_averaging_2026-09-01.md` + эмпирика
40 raw-FIT): COROS PACE 4 отдаёт мощность/running dynamics (METRICS_GUIDE §10 исправлен),
lap-сообщения (готовая разметка интервалов) и timer-события (точный moving-time)
игнорируются, `lthr`/`ltsp` уже в БД, но зоны — от %max_hr. Решения владельца 01.09:
полный пакет парсера; M3 в план (стоп-поинт показа зон); M4 — все 4 пакета.
Формулы/пороги — METRICS_GUIDE §5/§8/§11 (сюда не дублировать).

- ✅ **F0 — фундамент корректности (01.09.2026)**: #277 время выброшенных GPS-дельт
  исключено из avg_pace (`analysis/__init__.py`; №37: 8:04→7:58, остаток разницы с
  gross-часами честен — device-дистанция содержала фейковые метры); #278/#283 —
  `km_len_m` в per_km, дистанционно-взвешенные средние GAP, дробные км в quality_volume,
  хвостовые огрызки <500 м вне HR-baseline (`gap.py`, `session_metrics.py`,
  `hr_baseline.py`, `BASELINE_MIN_KM_LEN_M`); #279 — разрывы записи >`RECORDING_GAP_MAX_SEC`
  (30 c) не в зонах/длительности, Z4-отрезок рвётся на паузе и HR-дропауте (`segment.py`,
  `session_metrics.py`); #280 max HR = медианный пик; #281 зоны 80/20 и LLM-контекста —
  посекундные из computed_json с сегментным fallback (`repositories.py`, `history_tools.py`);
  #282 cad==0 вне средних. `INSIGHTS_SCHEMA_VERSION`=5. Проверка: №40/33 без изменений
  чисел, №37 честнее, полный pytest.
- ✅ **F1 — парсер FIT v2 (01.09.2026, #285)**: `extract_fit_activity` (`fit_parser.py`) —
  лапы → `laps_json`, timer-паузы + session-эталоны → `device_summary`, каналы
  pw/st/vo/vr/sl опциональными ключами трекпоинтов; `extract_fit_trackpoints` —
  совместимая обёртка; миграция `u4v5w6x7y8z9` (additive); `reanalyze` от сырья
  заполняет новые колонки (кэш-путь не трогает). Проверка: №42 — 16 лапов
  (7 повторов с HR), паузы 88/238 c из файла `8541566f`, №40 device=пайплайн до метра.
- ✅ **F2 — кросс-чек с часами (01.09.2026, #286)**: `_device_check` (workout_insights) —
  расхождение дистанции/времени с эталоном часов >5% (`DEVICE_MISMATCH_PCT`) → флаг
  `device_mismatch` → `suspect_data`; при gps_unreliable не считается. Точные паузы
  лежат в `device_summary.pauses` (сырьё для F3); разрывы записи из зон/длительности
  уже исключает F0-гейт (паузы <30 c — сознательный допуск).
- ✅ **F3 — M2.1 разбора (HRR, 01.09.2026)**: `src/analysis/intervals.py` — границы из
  структурных лапов F1 (fallback — осцилляции для interval; при gps_unreliable мусорный
  темп в fallback не подаётся — лапы работают, HRR по времени+HR); пик с лагом
  [t−15, t+15] (пульс пикует после конца работы), повтор с ростом HR через 60 c
  пропускается (неточная граница); `hrr60`/`min_hr`/тренд пиков; флаг
  `poor_interval_recovery` — только по повторам с пиком Z4+ (Z3-стриды не «плохое
  восстановление»). Замыкание §7: сигнал `poor_interval_recovery`
  (`InsightRepository.recent_flag`, окно 4 дня) → `evaluate_safety` правило 11 →
  `earliest_next_hard` ≥ +48 ч. FlagValue/промпт дополнены; `INSIGHTS_SCHEMA_VERSION`=6.
  Заодно #270: `workout_insights.py` 506→324 строк (`insights_baseline.py`,
  `analysis/data_checks.py`). Эмпирика: №42 — 8 повторов от лапов, hard-медиана 13 →
  флага нет (стриды в порядке); №33 — граница осцилляций неточна → честный `few_reps`
  (не ложный флаг). Проверка `511724f0`: пики Z2 на км-границах → повторы отсеяны ✓.
- ✅ **F7 (частично, 01.09.2026)**: `data_checks.lap_check` — телеметрия per_km vs
  авто-лапы часов (>2% → warning-лог), в `computed.inputs.lap_check`. Сверка GAP vs
  Coros Effort Pace — отложена (эталон сохранён в `device_summary.effort_pace_ms`).
- ✅ **F5 — M4.1 структура недели (01.09.2026)**: `src/analysis/week_structure.py` —
  ≤3 качественных/7 дней, ≥1 лёгкий день между качественными, восстановление после
  гонки 1 день/3 км; флаги `hard_days_too_close`/`post_race_recovery_violated`.
  Ключевое: «качественный день» = interval/race ЛИБО tempo с avg_hr ≥ 95%·LTHR
  (`is_quality_session`; residual-«tempo» классификатора иначе жёг правило постоянно).
  Замыкание §7: сигналы `_week_signals` (state) → p1 правила 12 (интенсив не раньше
  чем +1–2 дня) и 13 (post-race: max_zone=2 + запрет hard).
- ✅ **F6 — M4.2–4.4 (01.09.2026)**: `gap.downhill_block` — крутые спуски (уклон >3%;
  пороги от эмпирики истории: медиана доли 7.9% → флаг >15% или >2 км) →
  `downhill_load_high`; `week_structure.detraining` — пауза ≥6 дней → флаг
  `detraining_expected` + VDOT-декай-оценка, p1 правило 14 (мягкий возврат:
  max_zone=2); `session_rpe` (Foster: RPE×минуты) в computed; `wellness_trend`
  (7 vs 28 дней mood/soreness/pain/sleep_quality_self) в weekly summary — без новых
  вопросов пользователю. Схема insights v7 (на 10.09.2026 `INSIGHTS_SCHEMA_VERSION = 10`
  в `src/services/workout_insights.py`: v8 — пол GAP-фактора на спусках #298, v9 — базовая линия
  v2 #259/#289, v10 — путь «холод»/адаптивная поправка датчика; история пересчитывается лениво).
- ✅ **F4 — M3.1 зоны/темпы от LTHR/LTSP (01.09.2026)**: 🛑 стоп-поинт пройден — владельцу
  показано сравнение на истории (доля лёгкого 72% → 47%, 31/42 тренировок сдвигаются;
  Z2-потолок 144 → 139) — решение «включить полностью + пересчитать историю».
  `hr_zones.zone_bounds/get_zone/get_band/zone_ceiling_hr(+lthr)` — лестница Фицджеральда
  (≤81/89/100/105% LTHR, «зона X» внутри Z3), fallback %max_hr при отсутствии/невалидном
  lthr; классификация: recovery ≤81%·lthr, easy ≤89%·lthr, interval-подтверждение ≥ lthr;
  lthr прокинут по пайплайну (parse_fit/parse_tcx/sync/uploads/reanalyze → process_trackpoints
  → зоны/сегменты/классификация) и коучу (insights, потолки карточек render/prescriber/
  segments/numeric_check, history_tools, zone_distribution); резолверы `latest_lthr`/`latest_ltsp`
  (repositories, окно 45 дней); `lthr`/`ltsp` в METRIC_FIELDS. Нормативный темп сегментов
  от `ltsp` (#273): нет истории на потолке зоны → pace_hint = ltsp + LTSP_ZONE_OFFSET_S[зона]
  («правило шести секунд»), `pace_source="threshold"` — «мало данных» для ускорений закрыт.
  M3.2 (полевой тест ПАНО — валидация lthr Coros) — за владельцем.

Зависимости: F0 → F1 → (F2 ∥ F3 ∥ F7) → F4 → (F5 ∥ F6). Осталось: M3.2 (полевой тест ПАНО —
за владельцем), F7-часть «GAP vs Coros Effort Pace»; хвосты §7 METRICS_GUIDE закрыты 04.09.2026
правилами 17–20 (#289 — остаток только поправка `hr_vs_baseline` при detraining).

Literal-перечень флагов assessment — `schemas.FlagValue` (append-only, 21 значение, зеркало в
`prompts.py`); LLM сама ставит только `SUBJECTIVE_FLAGS` (pain/great_session),
детерминированные сливает `orchestrator._merged_flags` из `computed.flags`.

### P0/P1 — безопасность и планирование (ревизия приоритетов владельцем 04.09.2026)

Полный список и порядок — `BACKLOG.md` «Приоритеты». Закрыто 04.09.2026 (детали — CHANGELOG за день):
- ✅ **P0**: шкала Recovery % Coros §12 (#249), замыкания флагов разбора на safety — правила 17–19
  + `long_run_hold`/`detraining_return` в плане (#289, остаток — поправка `hr_vs_baseline`),
  монотонность/страйн Фостера (#308, правило 20), ранний пик пульса на медленном темпе (#238);
  safety классифицирует предложение по сегментам (`effective_workout_type`), длительная —
  качественный день (правило 12), перекос Z3+ за 7 дней (правило 16).
- ✅ **P1**: локальные недели в `week_targets` (#220), утро подтверждает последнюю строку дня
  (#292/#305), окно доступности `available_weekdays` + отмены переживают `/plan` (#294), потолок пульса
  в назначении (#295), ступени ориентира темпа A→B→C (#264) + темповые км-точки (#263),
  moving-time (#286), проза отчёта по `is_quality` (#311). #259 — ✅ 08.09.2026: базовая линия
  HR↔GAP v2 (`analysis/hr_baseline.py`: фит без температурного сдвига, сессионная σ `sigma_bpm`,
  прайор наклона −8 при выходе из [−15, −4], `BASELINE_VERSION` 2; `detraining_shift_bpm` — остаток
  #289 закрыт). Открыто: #243 (план к гонке — ТЗ зафиксировано, ждёт даты старта).
- ✅ Смежное 03–04.09: недельный отчёт v2 (C8.1 выше), отмена дней подопечным + гвард
  `blocked_by_unavailable`, ярлык тренировки по плану дня (`analysis/type_resolution.py`, миграция
  `v5w6x7y8z9a0`, переразметка 27/44).

### 06–10.09.2026 — потолки кодом, прогноз правил, болезнь, данные (детали — CHANGELOG по дням; записей за 05.09 нет)

- ✅ **06.09 — потолок длительной и объёма недели — кодом**: `planning_safety.cap_long_run` при финализации
  плана (км по `predicted.distance_km`, допуск `LONG_RUN_CAP_TOLERANCE_KM` 0,3 км; минуты по
  `long_run_min_max` 150; повторный `finalize`, строка «⚠️ Длительная урезана…», `meta.long_run_capped`) и
  `cap_week_volume` (лёгкие/восстановительные дни пропорционально до `target_km`, допуск
  `WEEK_VOLUME_TOLERANCE_PCT` 5 %, дни с сегментами фиксированы, `meta.week_volume_capped`); при закрытом
  интенсиве `apply_safety_to_targets` ставит `target_km = prev_week_km` (`volume_held_by_safety`, шапка «объём
  без роста») — решение владельца 06.09; цикл финализации — два прохода; `recent_athlete_requests` (7 дн) в
  контексте плана.
- ✅ **06.09 — ускорения по усилию и честный даунгрейд**: `is_stride`-сегменты (15–20 с) не клэмпятся по
  зоне/пульсу, усилие `STRIDE_DEFAULT_EFFORT` «свободно», компактная строка включает отдых («5×20 сек
  свободно (отдых 2 мин трусцой)»), длительность структурного дня — из суммы сегментов; `safety._downgrade`:
  урезанные tempo/interval/race → `easy`, не `long` (инцидент 06.09 «Длительный бег 40 мин»); карточка недели
  называет замену и причину по дням (`render_week._clamp_notes`); элементы плана несут `segments`
  (`segments_from_schema`); ускорения при `hard_days_max = 0` допустимы.
- ✅ **07.09 — прогноз правил 16/17 по дню плана (#315)**: `planning_safety.hard_share_by_day` /
  `easy_too_hard_counts_by_day` → `quality_reopens_at` → `quality_allowed_from_days_ahead`, каждый день плана
  финализируется по `project_state`; шапка «интенсив не раньше Чт (safety)»; `HARD_SHARE_LOOKBACK_DAYS = 7`.
  Смежно (методика): `EASY_RUN_Z3_TOLERANCE_PCT` 10 → 20 % + критерий среднего пульса выше Z2,
  `long_run_max_pct` 40 % при < 30 км/нед или ≤ 4 пробежек, `PLAN_EASY_MIN_MINUTES` 25 → 30, при плоском
  объёме `run_days_max` не больше прошлой недели.
- ✅ **07.09 — гейт болезни (#322)**: `CoachTurn.illness` (`IllnessReport`: sick/recovered, kind, days_ago),
  `coach/illness.py` (`params_json["illness"]`, без миграции; `record_illness`, `blocked_reason`),
  `ILLNESS_PAUSE_DAYS[kind]` (ОРЗ/грипп 14, ангина 21, пневмония 30, другое 7 дн.), правило 21 safety,
  `week_targets` исключает даты паузы из `days_ahead_allowed`, `project_state` несёт `day_offset`.
- ✅ **07.09 — E2.1 гайды Швеца 47–50** (см. E-серию выше): `plan_guides_queries`, дайджест ≤ 60 строк,
  гвард `tests/coach/test_guide_queries.py`.
- ✅ **07.09 — `/plan` с текстом-триггером** (инцидент 07.09): реплика «переделай план, сегодня не смогу» едет
  `athlete_text` в `generate_weekly_plan`, сохраняется как chat-сообщение, LLM видит её в контексте,
  `_apply_availability_from_turn` + `planning.cancel_days` применяют отмены после гашения прежнего плана,
  `meta.cancelled_days`.
- ✅ **08.09 — базовая линия HR↔GAP v2 (#259/#289)**: замер `bin/research_hr_baseline_slope.py` (pooled OLS
  −7.97 ≈ эмпирика −8); `fit_hr_pace_baseline` фитит HR без температурного сдвига, σ — сессионная
  `sigma_bpm` (3.4 вместо км-RMSE 5.5), наклон вне [−15, −4] → прайор −8 (`method=prior`),
  `BASELINE_VERSION` 2 (v1 пересчитывается при чтении); `detraining_shift_bpm` в ожидании `hr_vs_baseline`
  (`week_structure.detraining`, `DETRAINING_LOOKBACK_DAYS` 90, кап 20 %); `BASELINE_Z_FLAG` 1.5 → 2.0,
  `RPE_BASELINE_Z_MAX` 1.0 → 1.5; insights v9.
- ✅ **08.09 — готовность к зиме**: датчик температуры часов — только фолбэк с адаптивной поправкой
  `services/watch_temp_bias.recent_watch_bias` (медиана «часы − погода» за 45 дн) и гвардом ложной жары
  (`WATCH_HEAT_CONFIRM_MARGIN_C` 5); `cold_flag` при t ≤ `COLD_TEMP_THRESHOLD_C` 0 → контекст-флаг `cold` +
  гайд 49; метки Open-Meteo — UTC; insights v10; сдвиг пульса в мороз не расширен (#301).
- ✅ **08.09 — набор/спуск высоты с гистерезисом (#253)**: `calc_elevation` — `ELEV_HYSTERESIS_M` 2 м
  (×1.03 к `total_ascent_m` часов на 39 тренировках); `device_check` сверяет набор с часами
  (`DEVICE_ELEV_MISMATCH_PCT` 25 %, хвост #285); `bin/backfill_elevation.py`.
- ✅ **08.09 — сегменты по структурным лапам часов (#302)**: `analysis/segment_laps.py` (`lap_windows` /
  `lap_segments`), дистанция и время — из лапа, лап-сегменты авторитетны в `process_trackpoints(laps=)`,
  санити темпа лапа `LAP_PACE_SANITY_MIN/MAX_MIN_KM` 3:00–15:00, `computed.inputs.segmentation_source`;
  новый #327.
- ✅ **10.09 — актуальные проблемы подопечного (concerns)**: `coach/concerns.py` (`params_json["concerns"]`,
  `record_concern` / `refresh_from_pain` / `expire` / `resolve`, `CONCERN_EXPIRE_DAYS` 14), `CoachTurn.concern`
  (`ConcernReport`), `context_block` → `extras["concerns (params)"]`; колено убрано из профиля
  (`turn_context.profile`), промпта, `skills/pain.py`, вечернего вопроса (только при активной проблеме) и
  `handlers/pain.py` (`pain_location` — из активной травмы или `unspecified`); новый #328.

### Дальше (приоритеты, согласованы владельцем 25.08.2026)

Мост — постоянный LLM-режим (корпоративная подписка, #241 ⏸). Этапы:
1. **Обкатка v2** на живых тренировках (1–2 недели): конвейер отложенного разбора,
   качество прозы/assessment, первый недельный отчёт вс 19:00; хотфиксы промптов.
2. **Гигиена**: ✅ закрыта 29.08.2026 — #251, #247 (v1 детект), #242, #256, #258 (история без мимикрии).
3. **Персонализация** — когда insights накопятся (3–4 недели данных): #244
   (lessons-продюсер из assessment/computed), #246 (EWMA-калибровка, PredictionLog
   прогноз↔факт).
   Метрики разбора M1 + план-vs-факт (M2.2) ✅ 29.08 (#268, `analysis/session_metrics.py`).
4. **План к цели**: #243 — решение владельца 04.09.2026: до выбора старта подготовка нейтральная;
   после — план к дате, прогноз результата, тактика, «быстро или легко» через safety
   (race_date + целевой результат → многонедельный план,
   недельный отчёт сверяет факт с планом). **Фундамент готов ✅ 29.08:** недельный
   персистентный план #269 (§12, `weekly_plan.py`/`planning.py`); осталось race_date
   и многонедельный горизонт. **02.09 — карточка сохранённого плана по запросу**
   (`week_view.py`, `/week`, флаг `CoachTurn.show_week_plan`; `weekly_plan` в чате →
   карточка сохранённого плана вместо молчаливого дропа; инцидент 02.09 09:35).
   **02.09 (вечер)** — `/plan` гасит прежний план (`superseded`), адаптивный потолок
   беговых дней `run_days_max` (§12); хвост — #294 (окно доступности); #293 (`/plan` среди недели) ✅ 02.09.
5. **Данные**: **#257 сон ✅ 30.08 — решён иначе: скриншот сна → мост `/vision` →
   `DailyMetrics.sleep_*` (см. D8 ниже и CHANGELOG 30.08)**; правило «недосып→осторожнее»
   #254 (данные сна теперь есть); #232 (repair performance), #249 (recovery-шкала 20/70/90),
   #255 (осадки в разбор). **M2.1 разбора (HRR) и M3.1 (зоны/темпы от LTHR/LTSP) —
   ✅ 01.09.2026 (F3/F4); осталось M3.2 — полевой тест ПАНО (за владельцем); не путать
   M2.1 разбора с НАЗНАЧЕНИЕМ по сегментам (`segments.py`, в коде «M2.1»).**

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

### Инцидент 01.09 (утро) — мост недоступен, вердикт деградировал — закрыт
Мост дважды отдал `502 claude CLI exit=1` (Claude временно недоступен, восстановился сам).
Утренний вердикт (09:30) ушёл в общий чат-fallback `handle_chat` и **потерял назначение на день**
(выдал generic-карточку состояния), хотя рядом была детерминированная `morning_verdict()`.
Скриншот сна (07:35) не распознался — оба без повтора. Исправлено: `handle_chat(kind="morning")`
в fallback вызывает `morning_verdict()` (состояние + назначение через safety); ретрай транзиентных
сбоев моста (`post_with_retry`, `LLMTransientError`) в `/complete` и `/vision`; отложенный
upgrade-повтор утренней джобы (`_morning_upgrade_job`); аудит отправки вердикта. См. CHANGELOG 01.09.

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
3. **Гвард «один план»** — с 02.09.2026 автоматический: `tests/test_docs_links.py` проверяет, что
   формулировки отменённого rules-first плана (список `FORBIDDEN_PHRASES` в тесте) не встречаются в
   `*.md` вне `docs/archive/` и CHANGELOG, что все
   ссылки на документы резолвятся и каждый файл `docs/` есть в таблице CLAUDE.md. «rules-first» в
   набор не входит: допустим в контексте «пересмотрен/отменён».

4. **Перевешивание catch-all** — самое рискованное изменение: после C4 каждый текст = обращение к
   коучу (после C7 — платное). Митигация: приоритет веса, `turns_today`, `COACH_ENABLED`.
5. **Проза LLM может исказить число** — гарантирована только карточка. Numeric-checker v1 —
   ✅ 29.08.2026 (`coach/numeric_check.py`: сверка чисел прозы с карточкой, детект); v2 — обрезание
   предложения с чужим числом — ✅ 11.09.2026 (за две недели наблюдений 0 расхождений из 83 ответов;
   выключатель `COACH_NUMERIC_TRIM_PROSE`).
6. **Мульти-брендовость:** код коуча бренд-независим — в логике `src/coach/**` нет `coros`;
   исключение — `vision.py` (промпт распознавания скриншота сна конкретного приложения; при новом
   бренде — параметризовать). Комментарии/ссылки на `docs/coros_health_metrics.md` — не нарушение.
7. `training_type_override` в остальном приложении не слит с `training_type` → BACKLOG, не «заодно».

## 12. Принятые допущения (менять по слову владельца)
- **Зоны — от ПАНО (01.09.2026)**: лестница 81/89/100/105% LTHR (Coros, окно свежести
  45 дней), fallback %max_hr при отсутствии/невалидном lthr; история пересчитана
  (решение владельца). LTHR часов не валидирован полевым тестом — M3.2.

- Боль — 3 кнопки: `PAIN_LEVELS = (0 «не беспокоило», 2 «немного», 5 «мешало»)`;
  третья = `PAIN_STOP_LEVEL` → немедленный вердикт «Отдых». Колонка Integer держит шкалу 0–10.
  Боль вне тренировки — callback `pain:today:{level}` → wellness_reports. Утренний вердикт — 09:30.
- Недельный план ПЕРСИСТИТСЯ построчно (29.08.2026, `src/coach/weekly_plan.py`):
  вс 19:00 после отчёта — строки `recommendations` со `status='planned'` на пн–вс
  (`for_days_ahead` 1..7), карточка недели — `coach_messages kind='plan'`; утренний вердикт
  подтверждает день (`status='confirmed'`, UPDATE) или осознанно заменяет (`'adjusted'`,
  новая строка); числа недели (target_km, мезоцикл 3:1, потолки) — детерминированный
  `src/coach/planning.py`, LLM их не считает. Перепланирование — `/plan`: вс вечером — вся
  следующая неделя; **среди недели — остаток текущей** (#293, 02.09.2026: с сегодня, если
  пробежки ещё не было, по вс; `planning_window.plan_window`/`week_done`; лимиты минус
  сделанное — `remaining_*`, окно `days_ahead_allowed`; день 0 → `adjusted`);
  строки прежнего плана с первого планируемого дня без факта гасятся `status='superseded'`
  (`planning.supersede_future_rows`, 02.09.2026) — читатели их не видят.
  Беговых дней ≤ `run_days_max` (max за прошлые недели + 1, в [3, 6]) — `enforce_run_days`
  урезает лишние лёгкие дни детерминированно (решение владельца 02.09.2026). В `/week`
  прошедшие дни — факт связанной тренировки (✓) или пропуск (✗), план не «меняется» задним числом.
  Многонедельный план к гонке (#243) — по-прежнему только прозой до реализации.
- Инициатива стартует на `high`.
- Шкала Recovery % — Coros §12, приведена ✅ 04.09.2026 (#249): `RECOVERY_PCT_FRESH=90` /
  `RECOVERY_PCT_READY=70` / `RECOVERY_PCT_MODERATE=20` (`coach/config.py`; правило 4 §4 — два шага).
  `LOAD_RATIO_HIGH=1.2` — display-ярлык UI, не трогаем; для ACWR — отдельный
  `INJURY_RISK_THRESHOLDS['load_ratio_high']=1.5`.
- LLM: три бэкенда за `CoachLLM` Protocol; в проде — мост подписки
  (`BRIDGE_MODEL=sonnet` по умолчанию) — **постоянный режим** (решение владельца
  25.08.2026: корпоративная подписка); API-режим (`claude-opus-5`) остаётся опцией (#241 ⏸).
