# ARCHITECTURE (ADR) — гибридный ИИ-коуч

> Архитектурные решения и их причины. Дорожная карта и контракты — в [`DEV_PLAN.md`](DEV_PLAN.md)
> (не дублируются здесь). Обновлять при изменении решений, карту модулей — при добавлении файлов.

## Решение 1: гибрид вместо rules-first

Исходный `decision_module_design.md` предписывал: детерминированный движок правил P1–P5 решает
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
Переезд на личный ключ = `ANTHROPIC_API_KEY` в `.env` (BACKLOG #241) — код не меняется.

## Остаточный риск: проза может исказить число

Детерминированно гарантирована только **карточка** (числа из `Prescription` после clamp) и
блок «⚠️ Ограничение по безопасности». Проза LLM инструктирована не называть чисел тренировки,
но это правило промпта, не гарантия. Numeric-consistency checker — BACKLOG.

## Карта модулей `src/coach/` (фактическая, C0–C8)

```
coach/
├── config.py          # ЕДИНСТВЕННЫЙ исполняемый источник порогов (метрики ← coros-док,
│                      #   safety/pain ← DEV_PLAN §4); анти-дрейф-тесты test_coach_config
├── contracts.py       # SkillResult, AthleteState(+signals), SafetyVerdict,
│                      #   WorkoutProposal, Prescription(kw_only, safety обязателен), ReasoningStep
├── state.py           # assess_state → AthleteState (скиллы + скоры + signals + missing)
├── util.py            # effective_training_type (override > авто), safe_div, clamp_value
├── safety.py          # clamp() — ЕДИНСТВЕННЫЙ конструктор Prescription (только сужает)
├── prescriber.py      # finalize(): proposal → evaluate_safety → clamp → persist
├── fallback.py        # табличное предложение без LLM (readiness → easy/recovery/rest)
├── render.py          # детерминированный рендер карточек — числа только отсюда
│                      #   (+ render_weekly — дайджест-fallback недельного отчёта, C8)
├── orchestrator.py    # morning_verdict, handle_chat (LLM+fallback), on_workout_completed
│                      #   (C8: LLM-разбор, proposal отбрасывается), weekly_report (C8),
│                      #   get/set_initiative; ChatReply
├── rules/p1_safety.py # evaluate_safety(state) — 11 триггеров границы (чистая функция)
├── skills/            # base(SkillFn, SKILL_KEYS=6) + fatigue, recovery, load,
│                      #   distribution, progress, pain (state) + workout (per-session)
├── tools/             # registry (7 read-only tools, фикс. порядок), context(ToolContext),
│                      #   serialize, state_tools, history_tools, knowledge_tools
├── knowledge/         # loader (front-matter без PyYAML, key_rules_digest, keyword-поиск)
│   └── guides/        #   4 seed-руководства (Лидьярд, 80/20, прогрессия, колено)
└── llm/               # client (CoachLLM Protocol + get_llm: ключ→мост→Null), config,
                       #   schemas (CoachTurn), prompts (2 кэш-блока + today), agent
                       #   (ручной tool-loop), anthropic_client, bridge_client, null
```

Смежное: `src/services/repositories_coach.py` (CoachRepository — выборки для скиллов/state,
честный ACWR), `src/telegram/handlers/{coach,pain}.py`,
`src/telegram/jobs/coach_{morning,evening,weekly}.py` (09:30 / 21:00 / вс 19:00),
`src/services/sync/activities.py::_coach_reviews` (post-sync разборы в daemon-треде:
гейт initiative, LLM только для самой свежей тренировки батча),
`src/domain/models/coach.py` (5 таблиц) + `WellnessReport` в `health.py`,
миграция `p9q0r1s2t3u4`, `tests/coach/` (13 модулей + fakes).
