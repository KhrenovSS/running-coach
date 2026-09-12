# Рабочий документ: решения владельца 12.09.2026 — статус подопечного, длительная, объём, тест ПАНО

**Назначение:** точка возобновления работы после перерыва (лимиты подписки). Агент: прочитай этот файл,
`git status`, верх `CHANGELOG.md` — и продолжай с раздела «СЛЕДУЮЩИЙ ШАГ». Выполнил пункт → поставь `[x]`
и дату **в том же коммите**. Правила проекта — `CLAUDE.md` (коммит/пуш только по команде владельца;
backup перед деплоем; ~400 строк/файл; тесты `.venv/bin/python -m pytest -q`).

---

## ⏩ СЛЕДУЮЩИЙ ШАГ (остановка 12.09.2026 ~16:00 МСК — кончились лимиты подписки)

**Вся разработка WP1–WP3 закончена, протестирована (1063 теста зелёные), задеплоена в прод
(app+bot, бэкап `backups/backup_2026-09-12_15-35-21.sql.gz`) и 12.09.2026 закоммичена одним коммитом
в `main` и запушена (по команде владельца). Тремя коммитами разделить не удалось: `llm/prompts.py`,
`coach/config.py`, `planning.py`, `weekly_plan.py` и все доки несут правки всех трёх пакетов сразу —
промежуточные коммиты не собирались бы. Рабочее дерево чистое.**

Начинать отсюда:

1. **Проверить наблюдения п.2** (план вс 13.09, статус `stable` с 14.09, появление «🧪 Тест ПАНО» в `/plan`,
   кнопки подтверждения ПАНО после пробежки, `/lthr N`).
2. **Дальше по BACKLOG**: открыт #337 (зоны в web `/settings` от %max_hr, не от ПАНО), #243 (план к гонке,
   ждёт даты старта), P3 (#116, #126, #125, #84/#85) или фичи (#255 осадки, #309 тренды в web, #248).

**Ничего недоделанного в коде нет** — прод, `main` и рабочее дерево совпадают, тесты зелёные.

---

## 0. Что сделано 12.09.2026 (три пакета, один коммит: задеплоено, закоммичено в main, запушено)

**Пакет A — статус подопечного и лестница качественных дней** ✅ (в общем коммите; строка сообщения:
`feat(coach): статус подопечного из данных (training_status) и лестница качественных дней (quality_ladder) вместо статичной персоны и PLAN_QUALITY_DAYS_MAX`)

- [x] `src/coach/training_status.py` — фаза `returning`/`stabilizing`/`stable` из полных недель с пробежками и пауз;
  блок `athlete_status (computed)` в today-контексте (+ `zone_anchor` с 12.09); `src/coach/quality_ladder.py` —
  `hard_days_max` 1→3 по переносимости; персона без «после долгого перерыва» (`llm/prompts.py`); дайджест
  `key_rules_returning` по фазе (`knowledge/loader.py`, гайды 46/47/61); `PLAN_QUALITY_DAYS_MAX` удалена.

**Пакет B — длительная и объём недели** ✅ (в общем коммите; строка сообщения:
`feat(coach): длительная 40 % до 40 км/нед, рост объёма при интенсиве, закрытом только правилами 16/17 (#335, #336)`)

- [x] `LONG_RUN_LOW_VOLUME_KM` 30 → 40; причина `cap_long_run` и карточка отчёта — от одной формулы
  `long_run_max_pct`; #335 (мёртвая константа) и #336 (гайд 45) закрыты в архив.
- [x] `planning_safety.volume_hold` + `INTENSITY_ONLY_SAFETY_RULES`: объём плоский только при усталости/здоровье;
  блок правилами 16/17 объём не держит (`volume_growth_kept`), шапка «рост · без интенсива (safety)».

**Пакет C — полевой тест ПАНО, M3.2** ✅ (в общем коммите; строка сообщения:
`feat(coach): полевой тест ПАНО (M3.2) — автоназначение при stable, расчёт по треку, подтверждение кнопкой, latest_lthr с полевым приоритетом`)

- [x] `src/coach/lthr_field.py` (хранение `params_json["lthr_field"]`, `is_due`, `test_proposal` race 15+30+10,
  `place_test`, маркер `target.lthr_test`, `reanalyze_recent` 28 дн), `src/analysis/lthr_test.py` (ПАНО = средний
  пульс последних 20 из 30 мин, дрейф, темп, покрытие), блок `computed["lthr_test"]` (schema v11),
  `orchestrator.lthr_test_followup` (карточка + кнопки), `src/telegram/handlers/lthr.py` (`/lthr N`, `^lthr:`),
  `latest_lthr` с полевым приоритетом, гайд 31, `lthr_test_due` в плане.

**Файлы (49):** 37 изменённых + 12 новых — `src/coach/{training_status,quality_ladder,lthr_field}.py`,
`src/analysis/lthr_test.py`, `src/telegram/handlers/lthr.py`, `src/coach/knowledge/guides/31_lthr_field_test.md`,
тесты `tests/{test_lthr_field,coach/test_training_status,coach/test_quality_ladder,coach/test_lthr_plan}.py`,
этот документ. Полный список — `git status`.

**Проверено:** `pytest -q` → 1063 passed; `create_app()` ок; гварды (`from src.database`, `except: pass`,
`PLAN_QUALITY_DAYS_MAX`) → 0; прод read-only: user 2 → `stabilizing`, `long_run_max_pct` 0.40,
`volume_hold` True (сегодня `hrv_low` — верно), `lthr_test_due` False, якорь зон `coros` 156.

## 1. Решения владельца (12.09.2026) — зафиксированы, не пересматривать без него

| # | Решение | Значение |
|---|---|---|
| Р1 | Порог статуса `stable` | 4 полные недели подряд с ≥ 2 пробежками, пауза ≥ 6 дн рвёт серию (реализовано) |
| Р2 | Качественных дней в неделю | лестница 1→3 по переносимости, не константа (реализовано) |
| Р3 | Цели в персоне («сбросить вес…») | оставить как есть |
| Р4 | Доля длительной | **40 % до 40 км/нед, дальше 30 %** (сейчас порог 30 км) — WP1 |
| Р5 | Объём при закрытом интенсиве | **рост +10 % сохраняется**, если закрыт только правилами распределения (16/17…); плоский — только при усталости/здоровье — WP2 (отменяет решение 06.09) |
| Р6 | ПАНО 156 Coros | **полевой тест**; коуч **сам** ставит тест первым качественным днём при `stable` и открытом интенсиве — WP3 |

## 2. Открытые наблюдения (без правок, проверить руками)

- [ ] После статуса `stable` (с 14.09) и открытого интенсива в ближайшем `/plan` появится «🧪 Тест ПАНО» (race, 15+30+10);
  после пробежки — карточка с кнопками «Принять N / Оставить как есть»; `/lthr N` — ручной ввод. Проверить в Telegram.
- [ ] Дайджест key_rules при `returning` = 64 строки — ровно гвард `DIGEST_LINES_MAX`; следующий гайд потребует поднять гвард или ужать правила.

- [ ] Вс 13.09 19:00 план придёт со статусом `stabilizing`, лестница 1 (качественных за 4 нед — 0). С 14.09 статус `stable`.
- [ ] `/plan`, `/week`, утренний вердикт — без падений после деплоя 12.09 (логи `docker compose logs bot`).

## 3. WP1 — доля длительной 40 % до 40 км (+ #335/#336). Оценка: 1–2 ч

- [x] (12.09) `src/coach/config.py` — `LONG_RUN_LOW_VOLUME_KM = 40.0` (комментарий: решение владельца 12.09), docstring `long_run_max_pct`.
- [x] (12.09) `src/coach/config.py` — удалить `LOAD_PROGRESSION["max_monthly_increase_pct"]` (#335, не используется; `grep -rn max_monthly src tests docs`).
- [x] (12.09) `src/coach/planning_safety.py` (`cap_long_run`, ~:198/:201, docstring :173) — причина «потолок N % недельного объёма» из `targets["long_run_max_pct"]`, не «30 %».
- [x] (12.09) `src/coach/render_week_report.py` (~:101) — сравнивать с `long_run_max_pct(this["km"], this["runs"])`, не с `LONG_RUN_MAX_PCT_WEEK`.
- [x] (12.09) #336: `src/coach/knowledge/guides/45_training_structure_daniels.md` — `long_run_max_pct_of_week: 25` из `key_rules` в прозу («Дэниелс 25 %; код — 30/40 %»).
- [x] (12.09) Тесты: `tests/coach/test_methodology_caps.py` (+35 км → 0.40, 40 км → 0.30), `tests/coach/test_weekly_plan.py:~376` (строка причины), `tests/coach/test_render_week_report.py`, `test_guide_queries.py`.
- [x] (12.09) Доки: `docs/coach/METRICS_GUIDE.md:~132-135, ~394`; `CLAUDE.md` («40 % при < 30 км» → 40 км); `docs/coach/DEV_PLAN.md:~607`; `docs/coach/ARCHITECTURE.md:~203`; BACKLOG — #335/#336 закрыть (перенести в `docs/archive/BACKLOG_closed.md`).

## 4. WP2 — объём плоский только при усталости/здоровье. Оценка: 2–3 ч

Ключи правил safety (`src/coach/rules/p1_safety.py`, `triggered.append`): распределение нагрузки —
`week_intensity_overload`(16), `easy_runs_too_hard`(17), `quality_volume_exceeded`(18), `downhill_load`(19),
`hard_days_too_close`(12), `poor_interval_recovery`(11), `recovery_hours`(10). Всё остальное (`no_data`,
`rhr_critical`, `hrv_very_low`, `hrv_low`, `recovery_low`, `recovery_fatigued`, `ati_cti_high`, `acwr_high`,
`hard_streak`, `pain_stop`, `pain_caution`, `post_race_recovery`, `detraining`, `sleep_very_short`, `sleep_short`,
`monotony_high`, `illness`) — усталость/здоровье → объём плоский.

- [x] (12.09) `src/coach/config.py` рядом с `HARD_TYPES`: `INTENSITY_ONLY_SAFETY_RULES = (…7 ключей выше…)`.
- [x] (12.09) `src/coach/planning_safety.py` `apply_safety_to_targets` (~:140-163): `_volume_hold(verdict)` =
  `not verdict.triggered or any(t not in INTENSITY_ONLY_SAFETY_RULES for t in verdict.triggered)`; блок
  «target_km = prev_km / run_days_max ≤ prev_runs / пересчёт long_run_km_max» — только при hold; иначе
  `out["volume_growth_kept"] = "intensity_only"`. Ветка `quality_from_days_ahead` — та же логика.
- [x] (12.09) `src/coach/llm/prompts.py` PLAN_PROMPT (~:290) — строка про `volume_growth_kept`: «объём растёт по прогрессии, лечим темп лёгких, не километры».
- [x] (12.09) Тесты: `tests/coach/test_quality_reopen.py:~62` → `target_km == 27.9`, без `volume_held_by_safety`; `:~113` → «мезоцикла (рост)»;
  новые кейсы рядом с `tests/coach/test_planning.py::test_apply_safety_holds_volume_flat` (~:575): `["recovery_fatigued"]` → hold,
  `["easy_runs_too_hard"]` → рост и `run_days_max` не урезан, смесь → hold, пустой `triggered` → hold; анти-дрейф в
  `tests/test_coach_config.py` (список ⊆ ключей p1_safety).
- [x] (12.09) Доки: `CLAUDE.md` (~:196-197 «при плоском объёме…», ~:207 «объём плоский при закрытом интенсиве» → новое правило),
  `docs/coach/DEV_PLAN.md:~593-595, ~607-608`, `docs/coach/ARCHITECTURE.md:~200-204`, CHANGELOG (Р5 отменяет 06.09).
- [x] (12.09) Прогон (1052 теста зелёные, прод read-only: `long_run_max_pct` 0.40 → 11.2 км; сегодня hold=True из-за `hrv_low` — верно) и деплой
  (backup `backup_2026-09-12_15-16-58`, build app bot, up -d).
- [x] (12.09) Закоммичено (общий коммит, строка B): `feat(coach): длительная 40 % до 40 км/нед, рост объёма при интенсиве, закрытом только правилами 16/17 (#335, #336)`.

## 5. WP3 — полевой тест ПАНО (M3.2), автоназначение. Оценка: 1–2 дня

Факты из разведки: единственная точка якоря зон — `src/services/repositories.py::latest_lthr` (40+ потребителей);
ручного override ПАНО нет ни в `users`, ни в `params_json`; паттерн «предложить → кнопки → записать → аудит →
пересчитать» — `src/services/hr_max.py` + `src/telegram/handlers/hr_max.py`; типа «тест» нет — использовать `race`
(в `HARD_TYPES`, `TYPE_MIN_ZONE=4`, `_KEEP_TYPES`, 72 ч восстановления); свободный текст на карточку — только
`WorkoutSegment.effort` (80 симв.); трек — `trackpoints_json` через `workout_insights._parse_trackpoints`
(секунды от старта), окно по времени — `analysis/intervals._window_hrs`, учёт пауз — цикл `session_metrics.time_in_zones`;
связь план↔факт — `workout_insights_context._plan_for_session` (пишет `linked_session_id`, возвращает dict плана).

### 5a. Хранение и якорь
- [x] (12.09) `src/coach/lthr_field.py`: `params_json["lthr_field"]` = `{value, measured_at, session_id, method: test30|manual, pace_s_km, quality, updated_at}`
  (паттерн `illness.py`); `field_lthr(user_id, db, today)` (моложе `LTHR_FIELD_MAX_AGE_DAYS = 180`), `is_due(..., phase)`
  (нет/устарело и `phase == "stable"`), `set_field_lthr(...)` + `AuditService.log_settings_changed(changes={"lthr_field": …})`.
- [x] (12.09) `src/services/repositories.py::latest_lthr` — сначала поле, затем Coros; `workout_insights.zone_anchor` → `"lthr_field"`.
- [x] (12.09) Пересчёт после смены якоря: обобщить `hr_max.reanalyze_batch_after_raise` (или соседняя функция) для сессий за `LTHR_REANALYZE_DAYS = 28`.
- [x] (12.09) `/lthr <уд/мин>` — `src/telegram/handlers/lthr.py`, регистрация в `src/telegram/main.py` (~:78): валидация
  `LTHR_SANITY_MIN < v < max_hr`, `method="manual"`, пересчёт, ответ с потолками Z1–Z4 (`zone_ceiling_hr`).
- [x] (12.09) Константы в `coach/config.py` + анти-дрейф `tests/test_coach_config.py`; зеркало `docs/coros_health_metrics.md` §18, METRICS_GUIDE M3.2.

### 5b. Назначение теста коучем
- [x] (12.09) `lthr_field.test_proposal(days_ahead) -> WorkoutProposal`: `race`, сегменты warmup 15 мин Z2 → work 30 мин Z4
  `effort="ровно, максимум, который удержишь все 30 мин; без финишного рывка"` → cooldown 10 мин Z1; маркер
  `prescription.target["lthr_test"] = True` после `finalize`, до `save_prescription` (Prescription создаётся только в `clamp`!).
- [x] (12.09) `src/coach/planning.py::week_targets` — `"lthr_test_due": lthr_field.is_due(...)`.
- [x] (12.09) `src/coach/weekly_plan.py` (после `enforce_run_days`, до `_finalize`): при `lthr_test_due` и `hard_days_max ≥ 1` —
  `lthr_field.place_test(items, targets)`: первый hard-элемент → тест; нет hard — заменить лёгкий день (не длительную)
  на первый допустимый (`quality_allowed_from_days_ahead`). `PLAN_PROMPT`: строка про `lthr_test_due`.
- [x] (12.09) Утро: `confirm_or_adjust_morning` — маркер переживает `_proposal_from_row`; вердикт режет race → adjusted easy, `due` остаётся.
- [x] (12.09) `render_week`: строка с маркером — «🧪 Тест ПАНО» (если файл > 400 строк — оставить «🏁», строка в BACKLOG).
- [x] (12.09) Гайд новый гайд 31 «полевой тест ПАНО» в `src/coach/knowledge/guides/` (seed): протокол 30 мин (ПАНО ≈ средний пульс последних 20 мин), условия
  (ровно, без жары/ветра, recovery ≥ 70 %, ≥ 48 ч после интенсива), ре-тест при смене формы; `key_rules` ≤ 3 (дайджест ≤ 64).

### 5c. Распознавание по треку и подтверждение
- [x] (12.09) `src/analysis/lthr_test.py`: `lthr_from_test(times_sec, hrs, dists, pauses_sec, *, max_hr) -> dict` — окно 30 мин с
  максимальным средним пульсом по времени (учёт пауз), ПАНО = среднее последних `LTHR_TEST_WINDOW_MIN = 20` мин, темп окна,
  `quality` ok/rough (дрейф ≤ `LTHR_TEST_DRIFT_MAX_BPM = 8` между 10-й и 30-й мин, покрытие HR ≥ 90 %), санити; деградация `available=false`.
  `_window_hrs`/`_hr_at` в `analysis/intervals.py` сделать публичными.
- [x] (12.09) `src/services/workout_insights.py`: `computed["lthr_test"]` (+ ветка без трекпоинтов), только при `plan.get("lthr_test")`
  (маркер пробросить через `_plan_for_session`); `INSIGHTS_SCHEMA_VERSION` 10 → 11.
- [x] (12.09) `src/coach/orchestrator.on_workout_completed`: при `available` — карточка «🧪 Полевой тест ПАНО: N уд/мин (Coros M), темп …»
  + кнопки `lthr:set:N` / `lthr:ignore` (паттерн `hr_max._confirm_buttons`, `telegram_notify`).
- [x] (12.09) `telegram/handlers/lthr.py::lthr_callback` (`^lthr:`), session-bound user (уроки #236), `set_field_lthr`, пересчёт 28 дн, ответ с потолками.
- [x] (12.09) `training_status.context_block` — `zone_anchor` (`lthr_field`/`coros`/`max_hr`).

### Тесты и доки WP3
- [x] (12.09) `tests/test_lthr_field_test.py` (свой диапазон chat_id, вписать в `docs/TESTING.md:~104`): `lthr_from_test` на синтетике
  (`build_long_trackpoints(duration_min=55)` + постобработка HR 130→160→120), rough при дрейфе, `available=false`;
  `latest_lthr` предпочитает поле, падает на Coros после 180 дн; `/lthr` пишет и аудирует.
- [x] (12.09) `tests/coach/test_lthr_plan.py`: `lthr_test_due` только при stable без поля; `place_test` меняет hard, не длительную;
  маркер в строке и после `_proposal_from_row`; вердикт режет → adjusted easy, `due` остаётся.
- [x] (12.09) Гварды: `test_no_prescription_bypass`, `test_session_ownership`, `test_coach_config`, `test_guide_queries`.
- [x] (12.09) Доки: CHANGELOG; `CLAUDE.md` (строка про ПАНО-тест и якорь поле → Coros → max_hr); `DEV_PLAN.md` M3.2 → ✅, §9;
  `METRICS_GUIDE.md` M3.2 (протокол/формула/константы); `ARCHITECTURE.md` (карта модулей, Решение 7); `coros_health_metrics.md` §18;
  BACKLOG: web `/settings` показывает зоны от %max_hr (`settings.py:39-43`), не от ПАНО.
- [x] (12.09) Прогон (1063 теста зелёные; прод read-only: `lthr_test_due` False при `stabilizing`, якорь coros 156, полевого нет)
  и деплой app+bot (бэкап перед деплоем — см. `backups/`, самый свежий 12.09).
- [x] (12.09) Закоммичено (общий коммит, строка C): `feat(coach): полевой тест ПАНО (M3.2) — автоназначение при stable, расчёт по треку, подтверждение кнопкой, latest_lthr с полевым приоритетом`.

## 6. Верификация (для каждого пакета)
1. `.venv/bin/python -m pytest -q`; `set -a; . ./.env; set +a; .venv/bin/python -c "from src.startup import create_app; create_app()"`;
   `grep -rn "from src.database" src/ | wc -l` → 0; `grep -rn "PLAN_QUALITY_DAYS_MAX\|max_monthly_increase_pct" src/ tests/` → 0.
2. Read-only прогон на проде во временном контейнере с новым кодом (миграций нет, БД только SELECT):
   `docker compose run --rm --no-deps -e PYTHONPATH=/app -v $PWD/src:/app/src:ro -v $PWD/logs:/app/logs app python /app/logs/<скрипт>.py`
   (скрипт положить в `logs/`, удалить после). Ожидания: WP1 — `week_targets(2)["long_run_max_pct"] == 0.40` при ~28 км;
   WP2 — `apply_safety_to_targets` при вердикте только с правилом 17 → `target_km` растёт, `volume_held_by_safety` нет;
   WP3 — `lthr_test_due` False пока `stabilizing`, `latest_lthr(2) == 156` без поля.
3. Деплой: `bin/backup_db.sh` → `docker compose build app bot && docker compose up -d app bot` (`src/coach|services|analysis|telegram` → оба).

## 7. Что НЕ трогаем
Пороги safety-правил; `EASY_RUN_Z3_TOLERANCE_PCT`; прогрессия +10 %/мезоцикл 3+1; `detraining_return`; схема БД (миграций нет).
