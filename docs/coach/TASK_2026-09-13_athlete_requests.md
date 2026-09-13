# Просьбы подопечного об изменении тренировки: коуч соглашается без проверки

**Статус:** ⬜ открыто, найдено 13.09.2026. Правки НЕ начаты (лимиты Fable исчерпаны).
Пункты BACKLOG — #338–#343.

## §0. Задача для Fable (решение владельца 13.09.2026)

Когда лимиты обнулятся — это первое, с чего начинается работа. **Fable проводит СВОЙ независимый
разбор инцидента и предлагает решение**, а не исполняет готовый дизайн.

Этот документ — свод фактов и трейсов (что произошло, где какой ограничитель, чем воспроизвести),
**а не утверждённый дизайн**. §5 — черновик направлений, записанный по горячим следам; принимать
его как данность не нужно, спорить с ним можно и нужно.

Порядок работы:

1. Проверить факты §1–§3 самостоятельно — по коду и по проде (SQL готовы в §6). Если что-то в
   разборе неверно или неполно — поправить документ.
2. Сделать свой анализ первопричины: почему просьба подопечного вообще не проходит оценку, и где
   в архитектуре (safety / prescriber / контекст LLM / промпт) правильное место для неё —
   с учётом инвариантов DEV_PLAN §1.
3. Предложить решение владельцу **до** правок: что меняется, что при этом ломается, как ведёт себя
   карточка, какие тесты. Дождаться решения.
4. После одобрения — правки, тесты, деплой, `CHANGELOG.md` в том же коммите.

Рамка требования владельца — §4: уменьшить/перенести/отменить подопечный уже может, «предложить
больше» должно оцениваться. Тренер оценивает и свои предложения, и просьбы подопечного.

---

## §1. Инцидент 13.09.2026 (прод, user_id = 2)

План недели от 07.09 ставил на вс 13.09 длительную 50 мин. Тремя репликами в чате подопечный
поднял её до 10 км, и коуч согласился на каждую.

| Время (MSK) | Реплика подопечного | Что стало со строкой дня | `recommendations.id` |
|---|---|---|---|
| 07.09 18:30 | — (план недели) | `long · 50 мин` (≈7.1 км), status `planned` | 76 |
| 08:13 | «Напомни план на сегодня» | `easy · 50 мин` ⚠️ переписано | 79 |
| 08:15 | «я могу пробежать не 50 минут, а час?» | `long · 60 мин` (≈8.6 км) | 80 |
| 08:16 | «а ещё чуть больше… чтобы вышло 10 км можно?» | `long · 72 мин · 10.0 км` (≈10.3 км) | 81 |
| 09:30 | утренний вердикт | подтвердил 72 мин, status → `confirmed` | 81 |
| 10:46 | факт синхронизировался | 10.1 км / 71 мин, ср. пульс 133, макс 142 | session 48 |

**Сохранённый вердикт safety на 08:16** (`recommendations.id = 81`, `safety_json`):

```json
{"allow_training": true, "max_zone": 5, "max_duration_min": null,
 "allowed_types": ["rest", "recovery", "easy", "long"],
 "earliest_next_hard": "2026-09-15T08:15:35+03:00",
 "triggered": ["sleep_short", "quality_volume_exceeded"]}
```

То есть закрыт был только интенсив (сон 5.8 ч + превышение качественного объёма 48 ч назад).
Объём не ограничивался ничем: `max_duration_min = null`.

**Почему результат всё-таки вышел здравым** (важно: это совпадение, а не проверка):

- доля длительной в неделе 0.38 при потолке 0.40 (`workout_insights.computed_json.long_run`:
  `{"flag": false, "share_of_week": 0.38}`);
- объём недели 26.3 км против 25.3 / 25.4 в двух предыдущих;
- прошлые длительные — 10.5 км (23.08), 8.6 (30.08), 8.4 (03.09), то есть 10 км для этого
  подопечного не скачок;
- ср. пульс 133 при потолке карточки 138 — дисциплина соблюдена.

**Что при этом сломалось:** `plan_vs_actual.volume_ratio` = **0.98**, потому что факт сравнивался
с уже переписанным назначением (72 мин), а не с плановыми 50 мин (реальное отношение ≈ 1.42).
Сигнал «подопечный перевыполнил план» не возник.

---

## §2. Карта ограничителей: что режет clamp и чего он не режет

`safety.clamp()` (`src/coach/safety.py:112`) — единственный конструктор `Prescription`
(инвариант DEV_PLAN §1, единственный call-site — `prescriber.py:129`). Режет:

| Шаг | Строки | Что ограничивает |
|---|---|---|
| 1–2 | `safety.py:126-140` | `allow_training=false` / `proposal=None` → `rest` |
| 2b | `:154-163` | переклассификация по сегментам (`effective_workout_type`) — интенсивность |
| 3 | `:164-170` | даунгрейд ТИПА по `allowed_types` + `max_zone` |
| 4 | `:172-195` | интенсив раньше `earliest_next_hard` → `easy` |
| 5 | `:197-204` | ЗОНА ≤ `max_zone` |
| 5b | `:206-242` | целевой ТЕМП: санити, сброс при санкциях, замедление по `pace_ctx` |
| **6** | **`:243-254`** | **ДЛИТЕЛЬНОСТЬ — единственная ветка про объём:** `duration > verdict.max_duration_min` |

`distance_km` самостоятельно не проверяется никогда: только пропорционально ужимается вслед за
урезанной длительностью (`:253`). Предложение `distance_km = 30, duration_min = None` не трогает
даже эту ветку — условие `duration is not None` (`:246`) не выполняется.

### 21 правило safety (`src/coach/rules/p1_safety.py:53-311`)

| # | Строки | `triggered` | Что ограничивает |
|---|---|---|---|
| 0 | 69–74 | `no_data` | интенсивность + запрет типов hard и `long` |
| 1 | 77–81 | `rhr_critical` | запрет тренировки целиком |
| 2 | 85–90 | `hrv_very_low` | интенсивность + запрет hard и `long` |
| 3 | 91–95 | `hrv_low` | интенсивность |
| 4 | 100–110 | `recovery_low` / `recovery_fatigued` | интенсивность |
| 5 | 114–119 | `ati_cti_high` | интенсивность |
| 6 | 123–127 | `acwr_high` | интенсивность (ближайший к «скачку нагрузки» сигнал, но смотрит назад и объём не трогает) |
| 7 | 131–134 | `hard_streak` | интенсивность |
| 8 | 139–142 | `pain_stop` | запрет целиком |
| **9** | **143–149** | `pain_caution` | интенсивность + **`max_duration = 40 мин`** ← объём |
| 10 | 154–163 | `recovery_hours` | тайминг интенсива |
| 11 | 169–176 | `poor_interval_recovery` | тайминг интенсива |
| 12 | 182–191 | `hard_days_too_close` | тайминг интенсива |
| 13 | 195–201 | `post_race_recovery` | интенсивность |
| 14 | 206–211 | `detraining` | интенсивность (объёмный потолок после паузы живёт в `week_targets`, не здесь) |
| **15** | **216–228** | `sleep_very_short` | интенсивность + **`max_duration = 40 мин`** ← объём |
| 16 | 234–240 | `week_intensity_overload` | интенсивность |
| 17 | 244–250 | `easy_runs_too_hard` | интенсивность |
| 18 | 254–261 | `quality_volume_exceeded` | тайминг интенсива |
| 19 | 265–273 | `downhill_load` | интенсивность + тайминг |
| 20 | 278–284 | `monotony_high` | интенсивность |
| 21 | 289–297 | `illness` | запрет целиком |

**Вывод:** объём трогают ровно 2 правила из 21 (9 и 15), оба дают одно и то же значение
`SAFETY_MAX_DURATION_CAUTION_MIN = 40` мин. Правила «слишком длинная тренировка относительно
истории» нет вообще. Правило 10 % (`LOAD_PROGRESSION`) применяется только при расчёте `target_km`
недели (`planning.py:148-149`), как safety-гейт не работает.

**Единственная абсолютная граница** — валидация схемы LLM (`src/coach/llm/schemas.py:40-41`):
`duration_min ∈ [10, 240]`, `distance_km ∈ [1, 60]` — одинаковая для всех подопечных,
без привязки к истории. Запрос «30 км» проходит её свободно.

---

## §3. Потолки объёма есть — но не в том пути

| Механизм | Где | Call-sites |
|---|---|---|
| `planning.week_targets` (`target_km`, `long_run_km_max`, `long_run_min_max`, `hard_days_max`, `run_days_max`) | `planning.py:97-214` | `weekly_plan.py:125,157` |
| `planning_safety.cap_long_run` | `planning_safety.py:184-237` | `weekly_plan.py:294` |
| `planning_safety.cap_week_volume` | `planning_safety.py:243-296` | `weekly_plan.py:307` |
| `planning_safety.apply_safety_to_targets` | `planning_safety.py:128-182` | `weekly_plan.py:185` |

Все четыре вызываются **только** из `generate_weekly_plan`, то есть в `/plan`. Ad-hoc путь
(`chat_flow.py:213 → prescriber.finalize → clamp`) и утренний путь
(`planning_rows.confirm_or_adjust_morning:170 → finalize`) не используют ни один из них.

### Обходы, которые останутся даже после переноса кэпа

1. **Ярлык.** `cap_long_run` стартует с `if proposal.workout_type != "long"` (`planning_safety.py:195`)
   — назвав день `easy`, LLM обходит потолок длительной по построению.
   `effective_workout_type` (`safety.py:79`) переклассифицирует по зонам сегментов, но не по объёму.
2. **Сегменты.** Структурная длительная выше потолка получает только текстовую заметку, а не
   урезание (`planning_safety.py:197-205`), и исключена из `cap_week_volume` (`_SCALABLE_TYPES`
   = `easy`/`recovery` без сегментов, `:289-292`).
3. **Рост длительности после clamp.** `prescriber.py:169-177` переписывает `volume["duration_min"]`
   суммой сегментов уже ПОСЛЕ clamp — длительность может вырасти относительно предложенной,
   и повторно ни через safety, ни через кэпы не проходит.

### Чего LLM не видит в чат-ходе

`turn_context.build_extras` (`turn_context.py:58-161`) кладёт `recent_workouts`, `weekly_summary`
(объёмы недель), `recent_reviews`, `planned_workouts`, `illness`, `concerns`, `athlete_status`.
**Не кладёт `week_targets`** — он добавляется только в `weekly_plan.py:199`. То есть
`long_run_km_max`, `target_km`, `remaining_km`, `hard_days_max` модели в чате недоступны.

`SAFETY_CONTRACT` (`llm/prompts.py:47-54`) описывает `allow_training`, `max_zone`, `allowed_types`,
`earliest_next_hard` — **про объём ни слова**. Все потолки объёма расписаны в `PLAN_PROMPT`,
который в чат-ходе не используется.

---

## §4. Требование владельца к целевому поведению (13.09.2026)

> «Должна быть возможность как уменьшить тренировку / перенести / отменить, так и предложить
> пробежать больше. Но тренер на то и тренер, что оценивает и свои предложения по плану
> тренировок, и мои предложения. Нельзя слепо на всё соглашаться.»

Асимметрия сегодня:

- **Меньше / перенести / отменить — работает детерминированно.** `CoachTurn.unavailable_days_ahead`
  → `planning.cancel_days`, обратный путь `available_again_days_ahead` → `reopen_days`, гвард
  `blocked_by_unavailable` (`chat_flow.py:190`), постоянное окно `available_weekdays`.
- **Больше — не проверяется ничем.** Решение целиком за LLM, без чисел в контексте и без
  ограничителя на выходе.

Оценка должна применяться симметрично: и к предложению коуча, и к просьбе подопечного.

---

## §5. Направления решения — ЧЕРНОВИК, не утверждённый дизайн

Записано по горячим следам 13.09.2026, чтобы не начинать с нуля. Проектирование — за Fable (§0):
принимать как данность не нужно, это только то, что видно из кода.

1. **Показать модели числа.** Положить компактный срез `week_targets` (`target_km`, `done_km`,
   `remaining_km`, `long_run_km_max`, `hard_days_max`) в `build_extras` для kind `chat`/`morning`
   и добавить в `SAFETY_CONTRACT` абзац про объём. Дёшево и обратимо, но гарантии не даёт.
2. **Детерминированный кэп ad-hoc пути**, симметричный `/plan`: `cap_long_run`/`cap_week_volume` —
   чистые функции, принимают `(proposal, prescription, targets)`, так что переиспользуются как есть;
   вопрос в том, где их звать (после `finalize` в `chat_flow` + `planning_rows`, с повторной
   финализацией урезанного предложения) и что показывать в карточке («⚠️ Урезано: …»).
3. **Закрыть обходы** из §3: ярлык `easy` с объёмом длительной, сегменты (сейчас только заметка),
   рост длительности после clamp.
4. **Сохранить исходный план как базу сравнения**, чтобы `plan_vs_actual` и `week_plan_review`
   не теряли дрейф после перезаписи строки дня (см. #341).
5. **Отделить вопрос от назначения**: «напомни план» не должен переписывать строку дня (см. #342).

Инварианты DEV_PLAN §1 не нарушать: `Prescription` создаётся только через `safety.clamp()`,
числа для пользователя рендерит `render.py`, LLM в БД не пишет.

---

## §6. Как воспроизвести (read-only, проверено на проде 13.09.2026)

БД наружу не публикуется — только через контейнер; пароль не нужен под `-U running_coach`.

```bash
cd /home/nimda/projects/running-coach

# Диалог коуча за сутки (role/kind/текст; kind='morning' role=user — шаблонный промпт, не человек)
docker compose exec -T db psql -U running_coach -d running_coach -P pager=off -c "
SELECT id, created_at AT TIME ZONE 'Europe/Moscow' AS msk, role, kind, left(text, 400)
FROM coach_messages WHERE created_at > now() - interval '36 hours' ORDER BY id;"

# Строки плана и их перезапись в течение дня
docker compose exec -T db psql -U running_coach -d running_coach -P pager=off -c "
SELECT id, for_date, workout_type, status, source, clamped, volume_json,
       predicted_json->>'distance_km' AS pred_km,
       created_at AT TIME ZONE 'Europe/Moscow' AS msk
FROM recommendations WHERE for_date >= date '2026-09-07' ORDER BY for_date, id;"

# Вердикт safety и предложение LLM ДО clamp
docker compose exec -T db psql -U running_coach -d running_coach -t -P pager=off -c "
SELECT id, jsonb_pretty(safety_json::jsonb), jsonb_pretty(proposal_json::jsonb)
FROM recommendations WHERE for_date = date '2026-09-13' ORDER BY id;"

# План vs факт и доля длительной в разборе
docker compose exec -T db psql -U running_coach -d running_coach -t -P pager=off -c "
SELECT jsonb_pretty((computed_json::jsonb)->'plan_vs_actual'),
       jsonb_pretty((computed_json::jsonb)->'long_run')
FROM workout_insights WHERE session_id = 48;"

# История объёмов по неделям
docker compose exec -T db psql -U running_coach -d running_coach -P pager=off -c "
SELECT (date_trunc('week', begin_ts AT TIME ZONE 'Europe/Moscow'))::date AS week,
       count(*) runs, round(sum(total_distance_km)::numeric,1) km,
       round(max(total_distance_km)::numeric,1) max_km
FROM training_sessions WHERE begin_ts > now() - interval '10 weeks' GROUP BY 1 ORDER BY 1;"
```

**Чего в проде нет:** дампа промпта и сырого ответа LLM. Мост намеренно не логирует содержимое
(`bin/coach_llm_bridge.py:91`), в `coach/llm/` логируется только длина нераспарсенного ответа
(`anthropic_client.py:95`). Восстановить точный промпт можно лишь пересборкой тем же кодом
(`turn_context.build_extras` + `llm/prompts.py`), и то неточно — `build_extras` считает состояние
«на сейчас», а не на момент хода.
