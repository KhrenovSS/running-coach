# ARCHITECTURE (ADR) — гибридный ИИ-коуч

> Архитектурные решения и их причины. Дорожная карта и контракты — в [`DEV_PLAN.md`](DEV_PLAN.md)
> (не дублируются здесь). Обновлять при изменении решений, карту модулей — при добавлении файлов.

## Решение 1: гибрид вместо rules-first

Исходный rules-first дизайн decision_module_design (06.2026; удалён, история git) предписывал: детерминированный движок правил P1–P5 решает
все числа, LLM только пересказывает. Владелец пересмотрел это 23.08.2026: **LLM рассуждает и
предлагает; детерминированный код владеет фактами (read-only tools), границей (safety.clamp)
и числами, которые видит пользователь** (рендер карточки — только из заклэмпленного
`Prescription`). Причина: каскад if/else упирается в потолок собственных правил, а рассуждение
по методической литературе — сильная сторона модели. Гарантия безопасности при этом усилилась:
она перенесена с дисциплины на **тип** (`Prescription` требует `SafetyVerdict` и собирается
только в `safety.py::clamp()`, source-гвард в тестах).

## Решение 2: ручной tool-loop, не SDK tool_runner

`client.beta.messages.tool_runner` генерирует схему из сигнатуры и вызывает функцию сам —
некуда прокинуть request-scoped `Session` (глобал/contextvar нарушают §8 CLAUDE.md, ловится
`tests/test_session_ownership.py`). Ручной цикл в `llm/agent.py` даёт DI сессии, лимит
итераций (`COACH_MAX_TOOL_ITERATIONS`) и тривиальный мок (`ScriptedLLM`).

## Решение 3: LLM-мост через подписку Claude Code

У владельца нет API-ключа (корпоративная подписка). Третий бэкенд `BridgeLLM` →
host-сервис `bin/coach_llm_bridge.py` (systemd `running-coach-llm-bridge.service`, :8765,
токен в `.env.bridge`) → headless `claude -p --tools "" --max-turns 1`. Ограничения принятые:
- **tool-цикл неактивен** (харнесс не отдаёт невыполненный tool_use) — компенсировано
  обогащением today-блока (recent_workouts + weekly_summary в каждом ходе);
- prompt-cache между ходами не гарантирован (каждый вызов — новая CLI-сессия);
- `cost_usd` в `coach_messages` считается по ценам opus — в мосте величина условная,
  реальная цена — лимиты подписки (`BRIDGE_MODEL=sonnet` по умолчанию их бережёт).
**25.08.2026 — мост утверждён владельцем как постоянный режим** (корпоративная подписка,
маржинальная стоимость токенов нулевая); ограничения компенсированы обогащением контекста
(D-серия), латентность до 150 с спрятана в фоновые треды/джобы. Остаток: проза guides доезжает
дайджестом — BACKLOG #242; личный ключ = `ANTHROPIC_API_KEY` в `.env` (#241 ⏸), код не меняется.
**30.08.2026 — `/vision`** — осознанное исключение из «no tools» ради сна из скриншота без
API-ключа: Read-tool ограничен temp-каталогом (`--add-dir`), файл удаляется в `finally`.
Альтернатива (перехват трафика приложения COROS) отвергнута владельцем.
**01.09.2026 — устойчивость к транзиентному сбою моста** (инцидент 502 утром): транзиентные
ответы → `LLMTransientError` + ретрай с backoff; утренний вердикт без моста — детерминированный
со назначением, добор LLM-вердикта отложенной джобой. Реализация и константы — DEV_PLAN §8.

## Решение 4: отложенный разбор — статус в БД, не очередь в памяти (D-серия, 24.08.2026)

Разбор v2 ждёт фидбека пользователя (тап RPE/боли) или таймаута ~30 мин. Синк живёт в двух
контейнерах (`app`-scheduler и бот), PTB job_queue — только в боте, процессы рестартуют.
Поэтому «очередь» — это строка `workout_insights.status` (pending → running → done/none/
expired/error) с атомарным claim (`UPDATE ... WHERE status='pending'`, rowcount==1):
синк из любого контейнера только создаёт строки, исполняет разбор только бот (хендлеры
тапов + периодическая джоба). Переживает рестарты, дедуп гарантирован БД, in-memory
состояния нет. Та же строка — персистентный итог разбора: `computed_json` **schema v7** (детерминированные
метрики: кардиодрейф Pa:HR, GAP/уклон, отклонение от базовой линии HR↔темп, heat, время в
зонах, потолки качества, план-vs-факт; с 01.09 также кросс-чеки с часами `device_check`/
`lap_check`, HRR интервалов `interval_recovery`, структура недели `week_structure`,
`detraining`, `downhill`, `session_rpe`; при `gps_unreliable` pace-производные блоки честно
гасятся `reason:"gps_unreliable"`) +
`assessment_json`/`carry_forward` (структурированная оценка LLM, записывает оркестратор из
провалидированного output — инвариант «LLM не пишет в БД» сохранён). Недельные/месячные
отчёты и утренний вердикт читают итоги, не пересканируя сырьё.

## Остаточный риск: проза может исказить число

Детерминированно гарантирована только **карточка** (числа из `Prescription` после clamp) и
блок «⚠️ Ограничение по безопасности». Проза LLM инструктирована не называть чисел тренировки,
но это правило промпта, не гарантия. Numeric-consistency checker — **v1 реализован 29.08.2026**
(`src/coach/numeric_check.py`, #247): детект чисел прозы (км/мин/темп/зоны/пульс) против
карточки → `logger.warning` + `meta.numeric_mismatch`; текст пользователю пока не режется
(обрезание — после наблюдений).

## Решение 5: недельный персистентный план (29.08.2026)

План недели живёт построчно в `recommendations` (не только прозой): вс 19:00 после отчёта
`weekly_plan.generate_weekly_plan` раскладывает неделю по дням (каждый через `clamp`),
`status='planned'`. **Числа недели детерминированы** (`planning.py`: мезоцикл 3:1, прогрессия
≤10%, потолки качества/длительной) — LLM только распределяет в этих рамках (инвариант «числа —
код, не проза»). Утренний вердикт подтверждает план дня (`confirmed`) или осознанно меняет
(`adjusted`). Перепланирование — `/plan`: будущие строки прежнего плана без факта получают
`status='superseded'` и невидимы для всех читателей (`turn_context`, `week_view`,
`workout_insights`). Беговых дней ≤ `run_days_max` (адаптивно от истории, `planning.py`).
Детали — DEV_PLAN §12.

## Решение 6: сон — из скриншота, не через перехват API (30.08.2026)

Coros API длительность/фазы/оценку сна не отдаёт (разведка D8); перехват трафика приложения
владелец отклонил. Решение: пользователь шлёт скриншот экрана сна → мост `/vision` → `vision.py`
(`SleepShot`, строгий JSON) → `sleep_ingest` → `DailyMetrics.sleep_*`/`sleep_extra`. Гибкие
метрики (deep/rem %, sleep stress, bedtime offset, note) — в JSON `sleep_extra` (устойчиво к
вариациям экранов, без миграций). Приватность: скриншот удаляется из чата после распознавания,
байты нигде не персистятся. Ключ не нужен (мост подписки).

## Решение 7: зоны и темпы — от ПАНО (LTHR/LTSP), %max_hr — fallback (F4/M3.1, 01.09.2026)

Coros синкает `lthr`/`ltsp` — они стали якорем всей интенсивности (решение владельца после
показа сравнения лестниц: доля лёгкого 72%→47%). `analysis/hr_zones.zone_bounds` — лестница
Фицджеральда (Z1≤81%, Z2≤89%, Z3≤100%, Z4≤105% LTHR; «зона X» внутри Z3), fallback %max_hr
при отсутствии/невалидном lthr (`lthr_valid`: диапазон (100, max_hr)). Резолверы
`latest_lthr`/`latest_ltsp` (repositories, окно свежести 45 дней) — единственный источник
порога; lthr прокинут по пайплайну (парсеры → process_trackpoints → зоны/сегменты/
классификация) и коучу (insights, потолки карточек `zone_ceiling_hr`, history_tools,
zone_distribution). Классификация: recovery ≤81%·lthr, easy ≤89%·lthr; «качественный день»
M4 — interval/race либо tempo с avg_hr ≥95%·lthr. Нормативный темп сегментов при пустой
истории — `ltsp + LTSP_ZONE_OFFSET_S[зона]` (`pace_source="threshold"`). LTHR часов не
валидирован полевым тестом — M3.2 за владельцем.

## Решение 8: граница безопасности потребляет метрики разбора (F3/F5/F6, 01.09.2026)

Флаги computed_json замыкаются на safety не прозой, а сигналами: `state._week_signals` +
`InsightRepository.recent_flag` → `p1_safety` правила 11–14 (плохой HRR между повторами →
`earliest_next_hard` +48 ч; качественные дни слишком близко → +1–2 дня; после гонки —
1 лёгкий день/3 км → max_zone=2; пауза ≥6 дней → мягкий возврат). Появилась осознанная
зависимость `coach/rules → analysis` (константы правил — `src/config/constants.py`).
Квалиметрия GPS — та же честность на уровне данных: `gps_quality` + оценка дистанции по
шагам, предупреждение рендерит `render_gps_warning` (числа — код, не проза LLM);
`gps_unreliable`/`device_mismatch` идут в assessment как `suspect_data`, ограничений safety
сознательно не дают. Хвосты замыканий — BACKLOG #289.

## Решение 9: недельный отчёт = карточка чисел + интерпретация (C8.1, 03.09.2026)

Отчёт вс 19:00 (и `/report`) состоит из прозы LLM (≤5 предложений: какой была неделя, один сигнал
прогресса, одно слабое место, направление) и детерминированной карточки «Итоги недели»
(`week_report.py` → `render_week_report.py`). Сигналы прогресса/тревоги (`highlights`/`concerns`)
предвыбирает код по порогам `config.py` — LLM выбирает из них, не выдумывает; числа в прозе
запрещены и ловятся `numeric_check.prose_numbers` (лог + meta, #247). Числа недели считаются
один раз в джобе и передаются и отчёту, и плану следующей недели (`generate_weekly_plan(week_report=)`),
чтобы план объяснял, что меняется относительно прошедшей недели. Решение владельца: карточка —
только про тренировки; самочувствие остаётся в утреннем вердикте.

## Решение 10: ярлык тренировки = резолвер(классификатор, план) (04.09.2026)

`training_type` больше не сырой ответ `classify_training`: в разборе (`workout_insights.
apply_type_resolution`) чистый `analysis/type_resolution.resolve_training_type` сводит сырой ярлык
(`training_type_auto`) и назначение дня (`Recommendation`) по принципу **план — назначение, факт —
интенсивность**: интервальная структура и пульс на ПАНО — всегда качество; без них ярлык — из плана
(long/easy/recovery) и никогда не tempo. Источник — `training_type_source` (auto|plan|manual), ручной
override главнее. Обратимо: `training_type = training_type_auto`. Решение владельца 04.09.2026.

## Карта модулей `src/coach/` (фактическая, на 02.09.2026)

```
coach/
├── config.py          # ЕДИНСТВЕННЫЙ исполняемый источник порогов (метрики ← coros-док,
│                      #   safety/pain ← DEV_PLAN §4, метрики M1/план); анти-дрейф test_coach_config
├── contracts.py       # SkillResult, AthleteState(+signals), SafetyVerdict, WorkoutProposal(+segments),
│                      #   WorkoutSegment, RecoverySpec, PaceClampContext, Prescription(kw_only), ReasoningStep
│                      #   (WorkoutProposal.structure — legacy-строка, читается для совместимости)
├── state.py           # assess_state → AthleteState; _missing() (sleep уходит при данных, #257)
├── util.py            # effective_training_type (override > авто), safe_div, clamp_value
├── safety.py          # clamp() — ЕДИНСТВЕННЫЙ конструктор Prescription (when=for_days_ahead)
├── prescriber.py      # finalize(): proposal → evaluate_safety → clamp → persist(status)
├── fallback.py        # табличное предложение без LLM (readiness → easy/recovery/rest)
├── render.py          # детерминированный рендер карточек + render_week_plan (недельный план)
├── render_segments.py # рендер посегментной раскладки + segments_total_min + compact_segments (структура одной строкой)
├── render_week.py     # карточка недели (render_week_plan: план/факт по дням, ~темп, ≈км из прогноза)
├── week_view.py       # read-only показ сохранённого плана недели (/week, show_week_plan)
├── planning_window.py # окно планирования (остаток недели) + week_done (факт недели по локальной дате)
├── segments.py        # enrich_and_clamp_segments: числа сегментам из зон/истории, per-segment clamp (M2.1)
├── orchestrator.py    # morning_verdict (подтверждает план дня), handle_chat, on_workout_completed
├── review_flow.py     # ensure_insights_for_batch, run_pending_review, due_review_sessions
│                      #   (+ слияние флагов из computed), weekly_report; ChatReply
├── turn_context.py    # build_extras / unchanged_today / history (вынос из orchestrator, #266)
├── planning.py        # детерминированные числа недели (мезоцикл 3:1, прогрессия, потолки),
│                      #   week_plan_review, confirm_or_adjust_morning
├── weekly_plan.py     # generate_weekly_plan (вс 19:00, строки recommendations status=planned)
├── numeric_check.py   # #247: сверка чисел прозы LLM с карточкой (детект+лог)
├── vision.py          # #257: SleepShot + extract_sleep (скриншот → мост /vision)
├── rules/p1_safety.py # evaluate_safety(state) — триггеры границы (чистая функция)
├── skills/            # base(SkillFn, SKILL_KEYS=6) + fatigue, recovery, load,
│                      #   distribution, progress, pain (state) + workout (per-session)
├── tools/             # registry (7 read-only tools), context, serialize, state_tools,
│                      #   history_tools (daily_metrics_morning += сон), knowledge_tools
├── knowledge/         # loader (front-matter, key_rules_digest, keyword-поиск)
│   └── guides/        #   методика: Лидьярд/80-20/прогрессия/колено + Дэниелс/Фицджеральд
└── llm/               # client (get_llm: ключ→мост→Null), config, schemas (CoachTurn+weekly_plan),
                       #   prompts (кэш-блоки + today + PLAN/MORNING/REVIEW), agent, anthropic/bridge/null

# Смежное: analysis/session_metrics.py (метрики M1), services/{workout_insights,sleep_ingest,
#   repositories_insights}.py, telegram/{handlers/sleep_photo, jobs/{sleep_reminder,coach_weekly}}.py,
#   bin/coach_llm_bridge.py (/complete + /vision). Миграции сна: r1s2t3u4v5w6, s2t3u4v5w6x7.
```

Смежное: `src/services/repositories_coach.py` (CoachRepository — выборки для скиллов/state,
честный ACWR), `src/services/repositories_insights.py` + `src/services/workout_insights.py`
(D1/D2: очередь+итог разбора; композиция чистой математики `src/analysis/{gap,effort,
hr_baseline}.py` — Minetti-GAP, decoupling Pa:HR, базовая линия HR↔темп),
`src/telegram/handlers/{coach,pain}.py`,
`src/telegram/jobs/coach_{morning,evening,weekly}.py` (09:30 / 21:00 / вс 19:00),
`src/services/sync/activities.py::_coach_reviews` (post-sync разборы в daemon-треде:
гейт initiative, LLM только для самой свежей тренировки батча),
`src/domain/models/coach.py` (6 таблиц, включая `WorkoutInsight`) + `WellnessReport` в
`health.py`, миграции `p9q0r1s2t3u4`/`q0r1s2t3u4v5`, `tests/coach/` (~34 модуля + fakes).
