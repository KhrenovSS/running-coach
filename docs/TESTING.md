# Руководство по тестированию (Testing Guide)

> Как писать и запускать тесты в running-coach.

## Структура тестов

```
tests/
├── conftest.py              # Два режима БД: SQLite (дефолт) / PostgreSQL (opt-in, см. ниже)
├── helpers.py               # Фабрики: build_trackpoints, make_user, build_training_session, build_daily_metrics,
│                            #   build_training_feedback, build_gps_glitch_trackpoints
├── helpers_intervals.py     # Фабрики HRR-синтетики: build_hr_series/build_laps/interval_workout/build_hrr_trackpoints
├── fixtures/                # TCX/FIT файлы для тестов (tempo_run.tcx, short_walk.tcx)
├── skills/                  # Фикстуры каркаса коуча (conftest + scaffold-гейт)
├── coach/                   # Тесты гибридного коуча (31 модуль): скиллы, state, safety/clamp (табличный),
│                            #   source-гварды (Prescription только из clamp; tools read-only),
│                            #   tools, agent (ScriptedLLM), промпт-стабильность, оркестратор,
│                            #   pain-флоу, рендер, BridgeLLM (httpx.MockTransport); fakes.py;
│                            #   test_lthr_coach.py (LTHR у коуча), test_safety_week_rules.py (правила 12–14)
├── test_gps.py              # clean_trackpoints, haversine_m
├── test_classify.py / test_classify_boundaries.py  # classify_training
├── test_hr_zones.py         # get_zone/get_band/zone_bounds (LTHR-лестница + fallback %max_hr)
├── test_oscillation.py      # detect_pace_oscillations, compute_hr_lag_correlation
├── test_segment.py          # segment_by_pace, km_segment_fallback
├── test_gps_quality.py      # квалиметрия GPS / оценка дистанции по шагам
├── test_intervals.py        # HRR-разбор интервалов
├── test_week_structure.py   # структура недели / детренированность (M4)
├── test_lthr_pipeline.py    # зоны от LTHR по всему пайплайну
├── test_session_metrics.py  # метрики M1 разбора
├── test_workout_insights.py # разбор тренировки (computed_json schema v7)
├── test_hr_baseline.py      # базовая линия HR↔темп
├── test_effort.py           # кардиодрейф / HR-стабильность
├── test_gap.py              # GAP/Minetti + downhill_block
├── test_timeutils.py        # хелперы времени/таймзон
├── test_stats.py            # calc_stats, fmt_duration, zone_ranges
├── test_health.py           # /health/ endpoint
├── test_process_trackpoints.py  # process_trackpoints pipeline
├── test_models.py           # SQLAlchemy model tests
├── test_repositories.py     # Training/Health/FeedbackRepository (db — обязательный kwarg)
├── test_analytics_helpers.py# compute_slope, compute_ewma
├── test_coach_config.py     # таксономия recovery_hours + анти-дрейф порогов/весов
├── test_auto_sync.py        # коды возврата sync (-1 = не двигать таймстемп), счётчики, notify, backoff
├── test_dedup.py            # дедуп по external_activity_id + частичные UNIQUE-индексы
├── test_raw_files.py        # хранилище сырых FIT/TCX + reanalyze от сырья
├── test_weight_service.py   # save_weight/current_weight
├── test_session_ownership.py# ГВАРД: SessionLocal() только в композиционных корнях (allowlist)
├── test_stage0_fixes.py     # регрессы Этапа 0 (stats бота, reanalyze, performance Float)
├── test_hr_max.py           # адаптивный max_hr (повышение/снижение)
└── test_backfill.py         # backfill-скрипты
```

## Инвариант: тесты не ходят в сеть

Ни один тест не делает сетевых вызовов, и **весь набор зелёный при отсутствующем
`ANTHROPIC_API_KEY`**. LLM в тестах — фейки из `tests/coach/fakes.py` (`ScriptedLLM` с записью
вызовов, `FailingLLM` для fallback-пути); HTTP моста — `httpx.MockTransport`. Тест, которому
нужна сеть или ключ, — ошибка дизайна (DEV_PLAN §1.7).

## Два режима БД (DB SAFETY, §6 CLAUDE.md)

1. **SQLite in-memory (дефолт)** — `conftest.py` безусловно форсит
   `DATABASE_URL=sqlite:///:memory:` до импорта `src.*`; схема через `create_all`;
   `PRAGMA foreign_keys=ON` включён (FK проверяются).
2. **PostgreSQL (opt-in)** — переменная **`TEST_PG_URL`** (НЕ `DATABASE_URL`!):
   строго localhost (иначе hard fail); схема **пересоздаётся** и строится через
   `alembic upgrade head` — ловит дрейф моделей/миграций, реальные типы колонок,
   частичные индексы. CI гоняет оба режима.

```bash
# Дефолтный быстрый прогон (SQLite)
.venv/bin/python -m pytest -q

# PG-режим: одноразовый контейнер, НИКОГДА не прод
docker run --rm -d --name pg-test -e POSTGRES_USER=running_coach \
  -e POSTGRES_PASSWORD=testpass -e POSTGRES_DB=running_coach \
  -p 127.0.0.1:55432:5432 postgres:16-alpine
TEST_PG_URL="postgresql://running_coach:testpass@127.0.0.1:55432/running_coach" \
  .venv/bin/python -m pytest -q
docker stop pg-test
```

## ⚠️ Конвенция: уникальные chat_id/email на тест

In-memory БД (и PG-схема) живёт **весь прогон** — данные тестов не чистятся между
файлами. Поэтому `make_user` в каждом тесте должен получать уникальные
`chat_id`/`email` (иначе `UNIQUE constraint failed`). Занятые диапазоны chat_id:
`123456789/999/111/222` (test_models, auto_sync), `77xxx` (backfill), `88xxx` (test_lthr_pipeline),
`89xxx` (test_week_structure), `90001-90002` (skills), `93xxx` (test_workout_insights),
`94xxx` (hr_max), `95xxx` (stage0), `96xxx` (auto_sync), `97xxx` (dedup),
`98xxx` (raw_files), `99xxx` (weight), `92xxx` (coach — счётчик `tests/coach/conftest._seq`).
Для нового файла бери свободный диапазон и хелпер вида:

```python
def _user(db, n: int):
    return make_user(db, chat_id=<база> + n, email=f"<префикс>_{n}@example.com")
```

## Конфигурация

```ini
# pytest.ini
[pytest]
testpaths = tests
python_files = test_*.py
```

## Фикстуры (conftest.py)

Актуальный код — в `tests/conftest.py` (не копируй сюда, чтобы не дрейфовал). Ключевое:

- `DATABASE_URL` форсится ДО импорта `src.*`; **НИКОГДА** `setdefault` (no-op в контейнере →
  тесты пишут в прод) и **НИКОГДА** `drop_all` в autouse-фикстурах.
- Фикстура `db_session` — сессия через `SessionLocal` приложения.
- PG-режим: `DROP SCHEMA public` + `alembic upgrade head` один раз на сессию — выполняется
  ТОЛЬКО на явно указанном `TEST_PG_URL` с guard'ом «строго localhost».

## Примеры тестов

### Классификация тренировок

```python
# tests/test_classify.py
from src.analysis.classify import classify_training


def test_interval_oscillation_count():
    """oscillation_count >= min_oscillations → interval"""
    time_in_zone = {1: 0, 2: 10, 3: 10, 4: 5, 5: 0}
    result, seg_count = classify_training(
        var_count=0, time_in_zone=time_in_zone,
        total_duration_min=25, max_hr=177,
        z4_plus_segments=[], avg_hr=155,
        oscillation_count=3, hr_correlated=True,
        segments_len=5,
    )
    assert result == "interval"


def test_tempo_no_oscillations():
    """var_count >= 1, oscillation_count=0 → tempo"""
    time_in_zone = {1: 0, 2: 20, 3: 5, 4: 0, 5: 0}
    result, seg_count = classify_training(
        var_count=1, time_in_zone=time_in_zone,
        total_duration_min=25, max_hr=177,
        z4_plus_segments=[], avg_hr=140,
        oscillation_count=0, hr_correlated=False,
        segments_len=5,
    )
    assert result == "tempo"
```

### Пульсовые зоны

```python
# tests/test_hr_zones.py
from src.analysis.hr_zones import get_zone, get_band


def test_get_zone_max_hr_177():
    """Зоны для max_hr=177 (fallback без LTHR)"""
    assert get_zone(150, 177) == 4
    assert get_zone(130, 177) == 2
    assert get_zone(90, 177) == 1


def test_get_zone_lthr():
    """Зоны от ПАНО (лестница 81/89/100/105% от LTHR)"""
    assert get_zone(150, 177, lthr=160) == 3  # лестница от ПАНО


def test_get_zone_zero_max_hr():
    """max_hr=0 не вызывает ZeroDivisionError"""
    assert get_zone(100, 0) == 1
```

### Сегментация

```python
# tests/test_segment.py
from src.analysis.segment_km import km_segment_fallback


def test_km_fallback_short():
    """Км-fallback для короткой тренировки"""
    from tests.helpers import build_trackpoints
    tps = build_trackpoints(distances=[500, 1000, 1500], times=[120, 240, 360])
    segments, var_count = km_segment_fallback(tps, 177, 1.5)
    assert len(segments) >= 1
    assert var_count >= 0
```

## Что покрывать тестами

### Обязательно

- Бизнес-логика (классификация, сегментация, зоны, осцилляции)
- Парсеры (TCX, FIT)
- GPS очистка (clean_trackpoints, haversine)
- Edge cases (пустые данные, нули, None)

### Хорошая практика

- Edge cases (max_hr=0, distance=0)
- Error paths
- Граничные значения

## Чеклист теста

- [ ] Имя теста описывает поведение
- [ ] Тест проверяет одну вещь
- [ ] Нет зависимости от внешних сервисов
- [ ] Интеграционные тесты используют `TestClient` и `SessionLocal`

---

**Последнее обновление:** 01.09.2026 (F-серия: тесты gps_quality/intervals/week_structure/lthr, новые диапазоны chat_id)
