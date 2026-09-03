# BACKLOG — Running Coach

Открытые пункты: идеи, фиксы, вопросы. **Правило:** заметил мелочь → строка сюда, обратно к задаче;
не чини «заодно». Закрытые пункты переносятся в `docs/archive/BACKLOG_closed.md` при чистке
(последняя — 02.09.2026: 209 закрытых строк; нумерация сквозная, следующий свободный номер — #304).
Статусы: ⬜ открыто · 🟡 частично · 🔶 частично закрыто · ⏸ не планируется.

## Исходный список (аудит и спринты 06–07.2026)

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 1 | [Фикс] | AUDIT-006 Telegram TODO: `sync_runner.py` вызывает `sync_activities_for_user`/`sync_health_for_user` напрямую вместо `run_sync_for_user`. Миграция на `run_sync_for_user_all_brands(chat_id)`. | `src/telegram/sync_runner.py:8-12` | ⬜ Sprint 12b |
| 5 | [Фикс] | AUDIT-008: Threading + asyncio anti-pattern. Scheduler — daemon thread, sync_service — `asyncio.run()` внутри синхронных функций. Планируется выделение sync в отдельный процесс. | `src/scheduler.py`, `src/services/sync_service.py` | ⬜ Отложено |
| 6 | [Фикс] | AUDIT-012: Type hints не везде. `mypy src/ --strict` не проходит. | Весь `src/` | ⬜ Отложено |
| 8 | [Идея] | Sprint 7: Admin panel — дашборд, управление пользователями, просмотр аудита, принудительный sync. Отложено до >1 пользователя. | аудит 07.2026 (PROJECT_AUDIT, удалён; git) | ⬜ Отложено |
| 10 | [Идея] | Фильтр по типу тренировки на главной, общая дистанция/время за неделю/месяц. | аудит 07.2026 (PROJECT_AUDIT, удалён; git) | ⬜ Заморожено (после C8/C9 DEV_PLAN) |
| 11 | [Идея] | Sprint 14: Multi-brand onboarding — выбор бренда при `/start`, заглушки для Polar/Garmin/Suunto. | аудит 07.2026 (PROJECT_AUDIT, удалён; git) | ⬜ Sprint 14 (заморожен) |
| 12 | [Идея] | Факторы самочувствия — multi-select (ноги, дыхание, пульс, жара, недосып, стресс), адаптивные подсказки. | аудит 07.2026 (PROJECT_AUDIT, удалён; git) | 🔶 Частично закрыт C3/C4 23.08.2026 (`wellness_reports`: боль/крепатура/настроение/сон + вечерний опрос); полный multi-select открыт |
| 13 | [Идея] | Мобильное PWA (Progressive Web App). | README.md | ⬜ Идея |
| 15 | [Вопрос] | AUDIT-008: выделять ли sync в отдельный процесс/контейнер или оставить `run_async_in_thread`? | `src/services/sync_service.py` | ⬜ Вопрос |
| 16 | [Фикс] | Telegram `sync_runner.py`: нужен `run_sync_for_user_all_brands(chat_id)` для объединения отчёта по всем брендам. | `src/telegram/sync_runner.py` | ⬜ Sprint 12b |

## 🟠 P1 — Важно (желательно закрыть до аналитики)

### Input Validation

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 78 | [Validation] | **Только расширение файла проверяется** — `.exe` переименованный в `.tcx` пройдёт. | `src/web/routes/uploads.py:40` | ⬜ P2 |
| 81 | [Validation] | **Нет rate-limiting на upload/settings/logs** — уязвимость к abuse. | `src/web/routes/uploads.py`, `settings.py`, `logs.py` | ⬜ P2 |

### Architectural

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 84 | [Arch] | **`render_page` в index.py — 155 строк** с SQL-запросами, HTML, JSON, логикой. Нарушение «тонкие роуты». | `src/web/routes/pages/index.py:23` | ⬜ P2 |
| 85 | [Arch] | **`upload_files` — 116 строк** с DB операциями, Telegram нотификациями, файловым IO. | `src/web/routes/uploads.py:28-143` | ⬜ P2 |
| 87 | [Arch] | **`run_async_in_thread` создаёт новый event-loop на каждый вызов** — частая синхронизация = GC pressure. Нужен пул. | `src/services/async_utils.py:14` | ⬜ P2 |
| 89 | [Arch] | **`get_db()` телеграм хендлеры выдёргивают через `next(get_db())`** — хак вместо FastAPI DI, сломается при рефакторинге. | `src/telegram/utils.py:10` | ⬜ P2 |
| 90 | [Arch] | **3-4 отдельных DB session per telegram handler** — `get_user` + свой `SessionLocal()` = лишние коннекты. | `src/telegram/handlers/stats.py:25` и др. | ⬜ P2 |

## 🟡 P2 — Желательно

### Documentation

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 94 | [Docs] | **`CHANGELOG.md` — 1613 строк без оглавления**, нет стандартного формата дат, дублирующиеся записи. | `CHANGELOG.md` | ⬜ P2 |

### Code Quality

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 103 | [Bug] | **`save_dashboard_data` вызывается дважды** при пустом `metrics_list` — или баг, или лишний вызов. | `src/services/sync/health.py:81-83,181` | ⬜ P2 |
| 104 | [Bug] | **Start_time в TCX: `'' or None` → `AttributeError`** при replace, если оба отсутствуют. | `src/parsers/tcx_parser.py:23-24` | ⬜ P2 |
| 106 | [Bug] | **FIT: `enhanced_altitude=0 or data.get('altitude')` — 0 (valid) трактуется как falsy**. | `src/parsers/fit_parser.py:26` | ⬜ P2 |
| 109 | [Bug] | **Oscillation HR-lag: mismatch time scales** — `pace_change` за 1 шаг, `hr_change` за `lag_sec`. | `src/analysis/oscillation.py:182-190` | ⬜ P2 |
| 111 | [Bug] | **Сегментация O(n^2)** — while loop по trackpoints для rolling window при равных dist. | `src/analysis/segment.py:103-104` | ⬜ P2 |
| 112 | [Bug] | **Сегментация: `max_credible_upper=15.0` хардкодом** — не из конфига. | `src/analysis/segment.py:111` | ⬜ P2 |
| 113 | [Bug] | **Сегментация: `count_off_osc = len(osc) < num_kms * 0.5` — предел 50-150% слишком широк**. | `src/analysis/segment.py:370-371` | ⬜ P2 |
| 114 | [Bug] | **Sync audit: `log_sync_completed` вызывается внутри per-cred цикла, передаёт cumulative totals** — искажение per-brand статистики. | `src/telegram/sync_runner.py:84-90` | ⬜ P2 |
| 116 | [Bug] | **Пароль показывается в plaintext в Telegram** — self-deleting, но может засветиться в нотификациях. | `src/telegram/handlers/account.py:121-127` | ⬜ P2 |
| 117 | [Bug] | **`handle_weight_message` — catch-all для всех не-командных сообщений** — любой текст в неудачный момент попытается стать weight. | `src/telegram/main.py:68` | ⬜ P2 |
| 119 | [Bug] | **`/logs` endpoint без аутентификации** + path traversal (хотя `os.path.join` немного защищает). | `src/web/routes/logs.py:10` | ⬜ P2 |
| 120 | [Bug] | **`/logs` уровень детекции по подстроке** — слово `"WARNING"` в сообщении даёт неверный CSS. | `src/web/routes/logs.py:40-41` | ⬜ P2 |
| 121 | [Bug] | **`/health` всегда 200, даже при `degraded`** — маскирует проблемы от load balancer. | `src/api/routes/health.py:92` | ⬜ P2 |
| 123 | [Bug] | **`get_or_create_user_by_telegram` — если email уже занят другим, генерит рандомный пароль без уведомления юзера**. | `src/telegram/handlers/start.py:75-76` | ⬜ P2 |
| 124 | [Bug] | **`today_start` в `sync.py:43` считает по Moscow TZ, хотя `begin_ts` в UTC** — смещение до 12ч. | `src/telegram/handlers/sync.py:43` | ⬜ P2 |
| 125 | [Bug] | **Training list может превысить 4096 символов Telegram** — падение при 100+ сессиях. | `src/telegram/handlers/trainings.py:81` | ⬜ P2 |
| 126 | [Bug] | **Feedback TOCTOU race** — check-then-insert без атомарности, возможны дубли. | `src/telegram/handlers/feedback.py:41-56` | ⬜ P2 |
| 127 | [Bug] | **`settings.py: `old_watch_email` сравнение — ложное срабатывание при пустом `watch_brand`**. | `src/web/routes/pages/settings.py:127` | ⬜ P2 |
| 128 | [Bug] | **`token_ttl_minutes` вычисляется при import time** — stale при hot-reload. | `src/services/auth.py:24` | ⬜ P2 |

### Cleanup

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 133 | [Cleanup] | **`models.py` — shim + бизнес-логика (`get_settings`).** Или shim, или сервис — не Both. | `src/models.py` | ⬜ P2 |
| 134 | [Cleanup] | **`get_db()` в Telegram через `next(get_db())`** — если `get_db` рефакторят, сломается бот. | `src/telegram/utils.py:10` | ⬜ P2 |
| 135 | [Cleanup] | **`_get_web_app_url` с `_` (private), но импортируется снаружи** — или public, или не импортировать. | `src/telegram/utils.py:17` | ⬜ P2 |
| 136 | [Cleanup] | **`_AUTO_SYNC_LOCK` (UPPER_CASE) vs `_sync_tasks_lock` (snake_case)** — непоследовательный нейминг. | `src/web/state.py:11-12` | ⬜ P2 |

## 🆕 Новые находки (16.07.2026 — Диагностика сбоя уведомлений и регистрации)

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 158 | [Bug] | **Coros не синхронизируется после пересоздания БД** — таблица `watch_credentials` пуста, пользователю нужно заново ввести email/пароль от Coros Training Hub на странице `/settings`. | `src/web/templates/settings.html` (форма ввода credentials) | ⬜ |

## 🟡 P2 — Подготовка к модулю аналитики (аудит 14.07.2026 — Sprint 20c)

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 175 | [Cleanup] | **Undocumented root files** — `app.log`, `running_coach.db`, `test.db`, `test.db-journal` не отражены в README дереве и не в `.gitignore`. SQLite-файлы — артефакты прежних запусков, не используются (README декларирует PostgreSQL). Удалены SQLite-файлы; `app.log` — перенести/добавить в `logs/`. | корень проекта | ⬜ |
| 176 | [Docs] | **Revision-ID `f7g8h9i0j1k2`/`g9h0i1j2k3l4` содержат не-hex символы** — буквы g-l не являются hex-цифрами. Рабочие как строки Alembic, но стилистически подозрительны (hand-faked). Рекомендуется переименовать в корректные hex-ID при следующем пересоздании миграций. | `alembic/versions/f7g8h9i0j1k2*.py`, `g9h0i1j2k3l4*.py` | ⬜ |

## 📌 Находки деплоя коуча (23.08.2026)

| # | Тип | Описание | Файлы | Статус |
|---|-----|----------|-------|--------|
| 241 | [Coach] | Переезд с моста на личный API-ключ. | `.env`, `bin/coach_llm_bridge.py` | ⏸ **Не планируется** (решение владельца 25.08.2026: корпоративная подписка, мост — постоянный режим). Переезд при желании = `ANTHROPIC_API_KEY` в `.env` — код готов (`get_llm()`: ключ → мост → Null) |
| 243 | [Coach] | Правило P4 (план/цель): нет `race_date` и шаблонов планов — завести поля цели с датой и генерацию плана (DEV_PLAN §2, C8+). | `src/domain/models/user.py`, `src/coach/` | ⬜ |
| 244 | [Coach] | Правило P5 (persональные уроки): вернуть `lessons`-продюсер, когда накопится фидбек (RPE/боль); предпочтения — в профильный блок промпта. | `src/coach/` | ⬜ |
| 246 | [Coach] | Вернуть персонализацию (EWMA-калибровка UserModel, PredictionLog residuals), когда feedback coverage вырастет (сейчас копится через боль/RPE). | `src/coach/` | 🟡 02.09.2026: продюсер пишет residuals (prediction_log.py, идемпотентно) — «только пишем»; потребитель (EWMA-коррекция прогнозов) — после M3.2, иначе residuals до/после смены якоря зон несравнимы |
| 247 | [Coach] | Numeric-consistency checker: проза LLM не должна противоречить числам карточки (сейчас — только правило промпта, остаточный риск в ADR). | `src/coach/numeric_check.py` | 🟡 v1 ✅ 29.08.2026: детект+лог+meta.numeric_mismatch, текст не режем; обрезание прозы и weekly_plan-проза — после недели наблюдений |
| 248 | [Arch] | `training_type_override` не слит с `training_type` в web/`/stats` (коуч решает сам через `effective_training_type`). Слить в остальном приложении. | `src/web/`, `src/telegram/handlers/stats.py` | ⬜ |
| 249 | [Config] | Привести recovery-шкалу к Coros §12 (20/70/90): сейчас `RECOVERY_PCT_MODERATE=30` — исторический порог display-слоя. | `src/coach/config.py`, `src/services/recovery_view.py` | ⬜ |
| 250 | [Docs] | В BACKLOG дублируется номер 139 (две разные записи). Не перенумеровывать (ссылки в коммитах); при следующей чистке пометить вторую как 139-bis. | `BACKLOG.md` | ⬜ |
| 252 | [Bug] | `_merge_similar_segments` теряет `temperature`/`weather_code` сегментов при слиянии (ключи есть до merge, после — нет). | `src/analysis/segment.py` | ⬜ |
| 253 | [Идея] | Переключить `TrainingSession.elevation_gain/loss` на сглаженный расчёт: `calc_elevation` — naive-сумма дельт, завышает набор на GPS/баро-шуме. Сглаженный расчёт появится в D2 (`analysis/gap.py`) — переиспользовать. **Требует решения владельца** (изменит числа в UI). 01.09.2026: альтернативный эталон — `total_ascent/descent` из session-сообщения FIT (F1 парсер v2, #285). | `src/analysis/utils.py` | ⬜ (01.09: сглаженные высоты уже используются в `gap.downhill_block` — осталось переключить `TrainingSession.elevation_*`) |
| 255 | [Data] | `precipitation` скачивается из Open-Meteo и выбрасывается (`weather.py` использует только temps/codes). Сохранять и отдавать в разбор (дождь/снег — фактор темпа/пульса). | `src/parsers/weather.py`, `src/analysis/__init__.py` | ⬜ |
| 259 | [Analytics] | Наклон OLS-линии HR↔GAP-темп сильно занижен (attenuation: шум км-точек по x, межсессионные условия — жара/усталость/дрейф): у активного пользователя b=−2.4 при эмпирических ~−8 bpm за мин/км. На инверсию больше не опираемся (26.08: `pace_at_hr_band` — эмпирическая медиана полосы), но `hr_vs_baseline`/`deviation_flag` пользуются этой линией — ожидаемый HR и z-скоры смещены. Рассмотреть: сессионные средние вместо км-точек, Deming/ортогональная регрессия или поправка на дрейф. | `src/analysis/hr_baseline.py` | ⬜ (01.09: хвостовые км-точки <500 м исключены из baseline (#283/F0) — влияние на наклон не перемерено) |
| 261 | [Arch] | `telegram/main.py` ставит `Defaults(tzinfo=settings.timezone)` — расписание утро/вечер одно на всех, не per-user (`user.timezone`). Для мульти-юзера в другом поясе сообщения приходят по чужому времени. | `src/telegram/main.py:50` | ⬜ |
| 263 | [Coach] | **Расширить выборку км-точек темповыми сегментами** — `_collect_window_points` берёт только steady-типы (easy/long/recovery), на темповом диапазоне точек в полосе ±0.25 мин/км часто <5 → прогноз «пульс на темпе» (`expected_hr_at_pace`) будет часто None («мало данных»). Кандидаты: км-точки tempo/interval-сессий из ровных сегментов. | `src/services/workout_insights.py:_collect_window_points` | ⬜ |
| 264 | [Coach] | **Ориентир темпа/дистанции в карточке пропадает для recovery/Z1 и Z3+** (инцидент 27.08.2026: восстановительный бег без строки ориентира — владелец выбирает по ней маршрут). Причина: `pace_at_hr_band` требует ≥5 км-точек в односторонней полосе `[потолок−10, потолок]`, а пульс сосредоточен в узком коридоре (для Z1 потолок 125 → 2 точки; Z2 → 24, работает). Решение — ступенчатая деградация A (узкая полоса) → B (широкая ±25 + локальная поправка наклоном, гейт Δ≤15) → C (медиана `avg_pace` сессий типа) → D, с `quality` в `predicted` и честной пометкой «прикидка» в карточке. **Деградированные оценки не должны попадать в safety-clamp** (`_pace_clamp_context` — только уровень A). Полное задание с диагностикой, формулами, проверкой на живых данных и тестами: `docs/coach/TASK_pace_estimate_fallback.md`. Родственные: #259 (занижённый наклон OLS), #263. | `src/analysis/hr_baseline.py`, `src/services/workout_insights.py`, `src/coach/prescriber.py`, `src/coach/render.py` | ⬜ (01.09: появилась нормативная ступень от `ltsp` в `segments.py` — переиспользовать как C′ в `predict_volume`, именование `quality`→`pace_source`; детали — в шапке ТЗ); карточка недели печатает ~темп/≈км из прогноза ✅ 02.09.2026 |
| 268 | [Coach] | **Детерминированный анализ тренировок — расширение метрик (M1–M3).** Аудит 29.08: из 10 ключевых параметров разбора считаются 3, приближённо 2, отсутствуют 5; LLM оценивает вычислимое «на глаз». Руководство с формулами, порогами, флагами и порядком внедрения — `docs/coach/METRICS_GUIDE.md`: M1 — time-in-zones точно + дисциплина лёгкого дня, стабильность темпа/HR, чистый HR-drift, баллы Дэниелса, потолки качества, доля длительной, каденс, RPE-триангуляция, разминка; M2 — восстановление между интервалами, план vs факт (`linked_session_id`); §6 — унификация флагов (`decoupling_high` vs `hr_drift_high`); M3 — якорь ПАНО/VDOT (решение владельца). Родственные: #259, #263, #264, #265. | `docs/coach/METRICS_GUIDE.md`, `src/services/workout_insights.py`, `src/analysis/` | 🟡 почти закрыт: M1+§6 ✅ 29.08, M2.2 ✅ 29.08, M2.1 (HRR) ✅ 01.09 (F3), M3.1 (LTHR/LTSP) ✅ 01.09 (F4), M4 ✅ 01.09 (F5/F6, §11); осталось M3.2 (полевой тест ПАНО — за владельцем) и хвосты §7 (#289) |

## 🟠 Отложенные находки ревью (03.08.2026 — подготовка к аналитике)

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 220 | [Analytics] | `weekly_volume` бакетит недели по UTC, игнорируя `TrainingSession.timezone` — off-by-one для не-UTC. | `src/services/repositories.py` (weekly_volume) | ⬜ |
| 221 | [Analytics] | `compute_slope` индекс-based (0,1,2…), игнорирует календарные разрывы → величина наклона неверна (знак корректен). Взвесить по датам при количественном использовании. | `src/services/analytics_helpers.py` | ⬜ |
| 222 | [Classification] | Тюнинг порогов `classify.py` (tempo — catch-all) требует размеченной выборки тренировок; без неё менять пороги рискованно. Собрать labeled data → пересмотреть. | `src/analysis/classify.py` | ⬜ |
| 223 | [Arch] | Планировщик стартует per-worker; синглтон только в пределах процесса → дубли синков при `--workers>1`. Advisory-lock / leader election перед масштабированием. | `src/scheduler.py`, `src/startup.py` | ⬜ |
| 224 | [Arch] | Нет watchdog у потока планировщика: неперехваченное исключение вне внутренних try/except убивает `_loop` навсегда до рестарта. | `src/scheduler.py` | ⬜ |

## 🔴 Аудит фундамента 05.08.2026 — план ремедиации (этапы 1–6)

Полный аудит критических промахов перед модулем коуча. Этап 0 (рантайм-фиксы: `/stats` бота,
reanalyze, `performance` Float) выполнен 05.08.2026 — см. CHANGELOG. Порядок этапов важен:
1 (PG-тесты) до 3/4 (миграции проверяемы); 3 до 4 (backfill FIT матчится по external_id);
**3, 4, 5 — гейт перед Этапом 1 коуча**. Детальный план — `/home/nimda/.claude/plans/iterative-weaving-scone.md`.

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 232 | [Data] | **Repair `performance`** — значения, сохранённые до фикса Integer→Float (05.08.2026), округлены необратимо. Скрипт: перезапросить Coros за доступное окно истории и UPDATE существующих строк (текущий sync пропускает существующие даты — само не починится). Чем раньше — тем больше вернём. | `bin/` (новый скрипт), `src/services/sync/health.py` | ⬜ |
| 233 | [Tests] | `tests/test_health.py:7` — `os.environ.setdefault("SECRET_KEY", ...)`: CI grep-гвард по паттерну `os.environ.setdefault` может его зацепить (это не DATABASE_URL, но паттерн совпадает). Заменить на явное присваивание. Найдено db-safety-ревью 05.08.2026. | `tests/test_health.py:7` | ⬜ |
| 234 | [Ops] | **Деплой миграций с ALTER — останавливать bot заранее.** При деплое 05.08.2026 первая попытка `alembic upgrade` (ALTER TYPE на daily_metrics) конкурировала с транзакциями бота → прерванная попытка оставила колонку без штампа версии → crash-loop app на DuplicateColumn. Восстановлено: stop app+bot → DROP пустой фантомной колонки → чистый upgrade. Добавить в чеклист деплоя: `docker compose stop bot` перед миграциями с ALTER/DDL. | `docs/CHECKLIST_MIGRATION.md` | ⬜ |
| 235 | [Ops] | **Ошибка Alembic на старте app гаснет молча** — при DuplicateColumn в crash-loop не было ни трейсбека в stdout, ни `logger.exception` в logs/app.log (uvicorn exit code 3 без вывода). Разобраться, куда уходит лог `on_startup` до инициализации логгера, и сделать ошибку миграции громкой. | `src/startup.py:34-41` | ⬜ |
| 236 | [Bug] | **`/delete_me`: `user.telegram_chat_id = None` пишется в detached-объект** (`get_user` возвращает пользователя из закрытой сессии) → отвязка chat_id не персистится; данные удаляются, но аккаунт остаётся привязанным к Telegram. Тот же класс бага, что и вес (исправлен 05.08.2026 через weight_service). Починить через session-bound user в сессии хендлера. | `src/telegram/handlers/account.py:60` | ⬜ |
| 237 | [Идея] | **Авто-reanalyze после авто-поднятия max_hr** — тренировки батча проанализированы со старым max_hr (зоны слегка завышены). `reanalyze_training` умеет пересчёт от сырья (дёшево), но добавляет латентность/failure-mode в sync. Пользователь решил 06.08.2026: в v1 не пересчитывать (погрешность от нескольких bpm мала, пересчёт доступен кнопкой). | `src/services/hr_max.py`, `src/services/reanalyze.py` | ⬜ |
| 238 | [Идея] | **Эвристика «ранний пик на низком темпе = глюк датчика»** для адаптивного max_hr: пик в первые минуты пробежки при темпе ниже исторического easy — вопросы к датчику (cadence-lock оптики даёт УСТОЙЧИВЫЙ ложный пульс, медиана его не ловит). v1 закрывает это правилом повторяемости (≥3 превышений за 30д); вернуться, если появятся ложные предупреждения. | `src/services/hr_max.py`, `src/analysis/utils.py` | ⬜ |
| 239 | [Фикс] | **Валидация ручного ввода max_hr в POST /settings** — сейчас форма принимает любое int; `ValidationError("max_hr", "must be between 100 and 220")` объявлен в `src/exceptions.py:52`, но никем не поднимается. Использовать `MAX_HR_CAP`/floor 100 из `config/constants.py` (те же границы, что и у кнопки `maxhr:set`). | `src/web/routes/pages/settings.py:75` | ⬜ |
| 271 | [Фикс] | **Markdown-разметка разбора иногда не парсится Telegram** — `telegram.utils | Markdown parse failed (can't find end of the entity …) — resending plain` (инцидент 30.08, разбор пробежки). Сейчас деградирует в plain-text (доставка не теряется), но текст едет без форматирования. Разобраться, что генерит незакрытую сущность (вероятно спецсимвол в числах/юните разбора), и экранировать при сборке сообщения. Низкий приоритет. | `src/telegram/utils.py` | ⬜ |
| 272 | [Coach] | **Экспорт структурированной тренировки в часы Coros** — чтобы ИИ-тренер загружал тренировку (сегменты с пульс/темп-целями) прямо на часы, а не только текстом в карточке. Изучить Coros training/workout API. Пока — карточка по сегментам (M2.1) + ручной ввод/бег по часам. | `src/coach/segments.py`, sync-слой | ⬜ Будущее (запрос владельца 01.09.2026) |
| 274 | [Чистка] | **Мёртвые константы GPS-очистки** — `MAX_CREDIBLE_PACE`/`MAX_GPS_JUMP_M`/`MIN_DISTANCE_FOR_VALID_SEGMENT_M` в `config/constants.py:6,14-15` нигде не импортируются: реальные значения захардкожены дефолтами сигнатур (`gps.py:14`, `analysis/__init__.py`, парсеры) и per-user полями. Свести к одному источнику (нарушение golden rule №1). Найдено при работе над GPS-квалиметрией 01.09.2026. | `src/config/constants.py`, `src/parsers/gps.py` | ⬜ (01.09: дубль растёт — 3.0 захардкожен и в `tests/test_gps_quality.py`; той же породы `max_age_days=45` в `latest_lthr/latest_ltsp`) |
| 275 | [Coach] | **Персональная длина шага по истории** — fallback-ступень оценки дистанции при GPS-сбое: если чистых окон в самой тренировке мало (`quality="rough"`, дефолтный шаг 1.0 м), брать медианную длину шага пользователя из прошлых чистых тренировок на близком каденсе/пульсе. Сейчас есть калибровка только внутри тренировки (`gps_quality.py`). 01.09.2026: FIT пишет `step_length` per-record и `avg_step_length`/`total_strides` в session (покрытие 99.8%) — после F1 (#285) калибровка не нужна: брать шаг с часов напрямую. | `src/analysis/gps_quality.py` | ⬜ (01.09: сырьё готово — F1 даёт `sl` per-record и `device_summary.avg_step_length_mm`/`total_strides`; осталось подключить в gps_quality вместо дефолта 1.0 м) |
| 284 | [Чистка] | **Пакет находок аудита усреднений** (низкий приоритет, полный список — `docs/archive/AUDIT_averaging_2026-09-01.md` §3.8): лаг заднего окна rolling pace (~23 с, затухание пиков интервалов на графике); клампы графика отбрасывают точки без индикации + наивный даунсемпл; хардкод 5.0 в `interpolate_paces`; окна по точкам вместо времени (smart-recording ×5); elapsed vs moving несогласованность (moving-pace нет как понятия); смешение временных баз в `_ef`; GPS-мусор при HR≥130 не чистится; off-by-one/мёртвые ветки `oscillation.py`; несогласованная атрибуция HR к дельте; порог `_adaptive_min_diff` от сырого ряда; мёртвый код (`compute_ewma`, `compute_moving_average`, `CALIBRATION_EWMA_ALPHA`, метка `hr_pace_mismatch`); O(n²) в `build_hr_pace_series`. | см. аудит | 🟡 частично 01.09 (F0/F2: elapsed/moving и хвостовой км закрыты); остались лаг rolling pace ~23 c, клампы графика, хардкод 5.0 в interpolate_paces, окна по точкам, мёртвый EWMA-код |
| 286 | [Coach] | **Moving-time (F2)** — паузы из timer-событий FIT (fallback — gap-эвристика), `avg_pace` от moving-времени, кросс-чек с session-эталоном часов (>5% → флаг качества). Закрывает elapsed/moving-несогласованность из аудита (#284) честно, данными вместо эвристик. Зависит от #285. | `src/analysis/`, DEV_PLAN §9 F2 | 🟡 01.09.2026: кросс-чек с эталоном часов ✅ (device_mismatch→suspect_data); avg_pace от timer-пауз — не внедрён (паузы <30 c проскакивают, точные паузы лежат в device_summary.pauses) |
| 288 | [Чистка] | **Minors db-safety-ревью F0–F2 (01.09.2026)**: (а) кэш-путь reanalyze считает avg_pace полным временем (не знает выброшенных дельт) — legacy-сессии без сырья сохранят чуть «медленный» темп; (б) `_lap_row` отбрасывает лапы без distance/timer (только elapsed) — перед F3 проверить на реальном интервальном FIT, не теряются ли паузо-круги 0 м; (в) `zone_distribution`/`history_tools` читают time_in_zones из computed_json без проверки schema_version (v4-строки до lazy-пересчёта — устаревшие числа, не потеря); (г) рост trackpoints_json на +5 ключей/точку (~300–500 КБ на длинную) — наблюдать за бэкапами. | `src/services/reanalyze.py`, `src/parsers/fit_parser.py` | ⬜ низкий; п.(б) снят F3 — лапы проверены на №42 (16 лапов) и 10×1000 |
| 289 | [Coach] | **Дозамкнуть §7-хвосты METRICS_GUIDE на safety** — флаги считаются, но ограничений не дают: `easy_run_too_hard` ×2/7дн → сигнал в `evaluate_safety`; `quality_volume_exceeded`/`long_run_share_high` → вход skill `load`; `downhill_load_high` → P1-сигнал (колено); `detraining_expected` → поправка ожиданий `hr_vs_baseline` + потолок объёма первой трети возврата (⅓ пика); туда же #254 (недосып→осторожнее — те же рельсы signals→p1). | `src/coach/state.py`, `src/coach/rules/p1_safety.py`, `src/coach/skills/load.py` | ⬜ |
| 290 | [Analysis] | **Классификатор ставит `tempo` лёгким пробежкам у границы Z2/Z3**: 31.08 (avg HR 137, 38 мин) и 01.09 (avg HR 140, 46 мин, план — лёгкий со страйдами) при потолке Z2 = 138 → LLM в чате 02.09 пересказал «два насыщенных дня подряд (вторник-темповый и понедельничный)». Смотреть гейт `is_quality_session`/порог классификатора относительно LTHR, страйды не должны тянуть тип. | `src/analysis/`, `src/services/insights_baseline.py` | ⬜ |
| 291 | [Coach] | **LLM обращается в женском роде** («доберёшься сама», coach_messages id 125, 02.09): в `turn_context.profile` нет имени/пола подопечного. Добавить поле профиля (имя/обращение) или правило промпта. | `src/coach/turn_context.py`, `src/coach/llm/prompts.py` | ⬜ |
| 292 | [Coach] | **`confirm_or_adjust_morning` подтверждает не ту строку**: утро 02.09 пометило `confirmed` строку `planned` id 31 (tempo), хотя план дня накануне заменён строкой `proposed` id 34 (easy) — `PLAN_STATUSES` исключает `proposed`, а `unchanged_today` сравнивает с любой последней строкой даты. План-vs-факт недели (`week_plan_review`) увидит «темповую выполнена». Решить: включать `proposed` на ту же дату в выбор plan_row или помечать вытесненные строки. | `src/coach/planning.py` | ⬜ |
| 294 | [Coach] | **Окно доступности не персистится**: «могу бегать пн–чт» живёт только в истории чата (8 ходов) — на следующем `/plan` модель его уже не увидит. Хранить в `UserModel.params_json.week_plan.availability` (merge-паттерн `advance_mesocycle`), отдавать в `week_targets`/PLAN_PROMPT, задавать из чата (`log_suggestion`-подобный тап) или командой. | `src/coach/planning.py`, `src/coach/llm/prompts.py` | ⬜ |
| 295 | [Coach] | **План хранит `max_zone`, а не уд/мин** — потолок пульса карточки считается при рендере из текущего якоря зон; смена якоря (max_hr → LTHR, F4 01.09) молча меняет числа будущих дней (Z2: 144 → 138), владелец читает это как «план изменили». Сегменты уже хранят `hr_ceiling`. Рассмотреть фиксацию `hr_ceiling` в `target_json` при `finalize` + правило обновления (утреннее подтверждение re-clamp'ит) и явную пометку «зоны пересчитаны от ПАНО». | `src/coach/prescriber.py`, `src/coach/render.py` | ⬜ |

## 🟡 Исследование «пульс ↔ рельеф/температура» (02.09.2026, 39 тренировок прода)

Вывод: GAP снимает основную часть эффекта уклона (R² 0.54→0.74), остаток ~0.8 уд/мин на 1 %;
тягуны на маршрутах (2–3.5 %, 150–350 м) дают +2–3 уд/мин — детектор подъёмов не окупится.
Сделано: температурная поправка ожидания `hr_vs_baseline` + фраза в REVIEW_PROMPT. Хвосты:

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 298 | [Analysis] | **Спуски у Minetti «слишком лёгкие».** Остаточный эффект уклона поверх GAP положительный — как у Strava (HR-модель 2017: минимум фактора 0.88 при −9 %, у Minetti 0.5 при −18 %; при −3 % Minetti 0.85 vs ~0.95). Рассмотреть нижнее ограничение `gap_factor` (~0.9 на −3…−10 %); трогает GAP, дрейф, базовую линию → пересчёт insights, отдельная задача. | `src/analysis/gap.py::gap_factor` | ⬜ |
| 299 | [Data] | **Температура датчика часов как второй источник.** `device_summary.avg_temperature_c` (FIT session) объясняет пульс лучше Open-Meteo (R² 0.37 vs 0.24; +0.9 уд/мин/°C, солнце/тень), но выше воздуха в среднем на 3.3 °C. Сейчас не читается никем. Кандидат на фолбэк/поправку. | `src/parsers/fit_parser.py`, `device_summary` | ⬜ |
| 300 | [Data] | **Температура фиксируется на старте.** Для тренировок 60+ мин брать среднее по часовым значениям Open-Meteo за время бега (данные уже запрашиваются на весь день, `weather.py`). | `src/parsers/weather.py`, `src/analysis/__init__.py` | ⬜ |
| 301 | [Research] | **Аналитика пульса/темпа при отрицательных температурах — после 31.**12.2026. Пока ни одной пробежки в мороз нет (данные 13.05–02.09.2026, 10–30 °C), поэтому сдвиг `expected_hr_shift_bpm` зажат в 10–30 °C (`HEAT_SHIFT_TEMP_MIN/MAX_C`) и ниже +10 °C равен −2. Когда накопятся зимние тренировки (ориентир — 8–10 пробежек при ≤ 0 °C, в т.ч. −10…−20 °C), повторить исследование 02.09.2026 (`HR ~ GAP-скорость + время + уклон`, 30-с окна, лаг 30 с, HR на равном GAP-темпе vs температура) и решить: продлить линейную формулу вниз, задать отдельный наклон для мороза (одежда, снег, холодовой стресс могут поднимать пульс) или оставить кламп. Заодно сверить Open-Meteo с датчиком часов (#299) на морозе. | `src/analysis/effort.py::heat_block`, `HEAT_SHIFT_TEMP_MIN/MAX_C` | ⬜ после 31.12.2026 |

## 🆕 Находки рефакторинга документации (02.09.2026)

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 302 | [Analysis] | **Сегментация коротких интервалов — проверка на реальной тренировке** (из архивного PROJECT_AUDIT, AUDIT-014 DoD): применить `segment_by_pace()` к реальной интервальной тренировке (бывшая session id=67 — перезагрузить TCX или взять №33 от 05.08) и сверить число сегментов с лапами часов. | `src/analysis/segment.py`, `tests/` | ⬜ |
| 303 | [Fix] | **`GET /logs` не находит ротированный файл**: роут ищет `app_<date>.log` (подчёркивание), а ротатор пишет `app.log.YYYY-MM-DD`; путь `log_path` резолвится относительно `src/web/routes/`, не корня. Показывает пусто после первой ротации. | `src/web/routes/logs.py:15-16`, `src/utils/logger.py:110-177` | ⬜ |
| 305 | [Fix] | **Утро подтверждает устаревшую строку плана**: `confirm_or_adjust_morning` берёт `plan_row` только из `PLAN_STATUSES`, а `unchanged_today` сравнивает с последней строкой любого статуса → когда чат уже дал новое назначение на сегодня (03.09: #32 easy 30 мин получил `confirmed`, карточка — по #36 long 60). На показ не влияет (week_view берёт последнюю строку на дату), статусы в БД врут. | `src/coach/planning.py:confirm_or_adjust_morning`, `src/coach/turn_context.py:unchanged_today` | ⬜ |
| 306 | [UX] | **«Интенсив — не раньше …» шумит и дрейфует**: строка показывается на карточке лёгкой/длительной, даже когда до срока < 1 ч (03.09: 10:16 → через 38 мин 10:18); `earliest_next_hard = now + round(hours_left, 1)` (`skills/recovery.py`) вместо `begin_ts + need`. Скрывать для нехардовых типов при малом остатке, считать от конца тренировки. | `src/coach/rules/p1_safety.py:133`, `src/coach/skills/recovery.py`, `src/coach/render.py:140` | ⬜ |
| 307 | [Test] | **`test_poor_interval_recovery_delays_next_hard` зависит от реального времени**: `evaluate_safety` получает фиксированный `now=01.09.2026`, а `clamp(AGGRESSIVE, verdict, state)` — без `now` → с 03.09 12:00 UTC `earliest_next_hard` уже в прошлом, интервалы не режутся, `clamped is False`. Передать тот же `now` в `clamp`. Красный на main с 03.09 (замечено при работе над отменой дней плана). | `tests/coach/test_safety_clamp.py:341-356` | ⬜ |
