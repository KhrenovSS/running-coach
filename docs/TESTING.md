# Руководство по тестированию (Testing Guide)

> Как писать и запускать тесты в running-coach.

## Структура тестов

```
tests/
├── conftest.py              # Фикстуры pytest (SessionLocal, create/drop tables)
├── helpers.py               # builder-функции (build_trackpoints)
├── fixtures/                # TCX/FIT файлы для тестов
│   ├── tempo_run.tcx
│   └── short_walk.tcx
├── test_gps.py              # clean_trackpoints, haversine_m
├── test_classify.py         # classify_training
├── test_hr_zones.py         # get_zone, get_band
├── test_oscillation.py      # detect_pace_oscillations, compute_hr_lag_correlation
├── test_segment.py          # segment_by_pace, km_segment_fallback
├── test_stats.py            # calc_stats, fmt_duration, zone_ranges
├── test_health.py           # /health/ endpoint
├── test_process_trackpoints.py  # process_trackpoints pipeline
└── test_models.py           # SQLAlchemy model tests
```

| Тип | Скорость | БД |
|-----|----------|----|
| Unit (анализ) | быстро (< 1 сек) | нет (чистые функции) |
| Unit (парсеры) | быстро (< 1 сек) | нет |
| Integration (health) | средне (5-30 сек) | реальный PostgreSQL (SessionLocal) |

## Запуск тестов

```bash
# Все тесты
pytest

# С именем файла
pytest tests/test_classify.py -v

# С coverage
pytest --cov=src --cov-report=html

# Конкретный тест
pytest tests/test_classify.py::test_interval_detection -v
```

## Конфигурация

```ini
# pytest.ini
[pytest]
testpaths = tests
python_files = test_*.py
```

## Фикстуры (conftest.py)

```python
# tests/conftest.py
import pytest
from src.domain.models.base import Base, SessionLocal, get_engine, init_db


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    """Создать таблицы один раз на сессию (Create tables once per session)"""
    Base.metadata.create_all(bind=get_engine())
    yield
    Base.metadata.drop_all(bind=get_engine())


@pytest.fixture(scope="function")
def db_session():
    """Свежая сессия для каждого теста (Fresh session for each test)"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

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
    """Зоны для max_hr=177"""
    assert get_zone(150, 177) == 4
    assert get_zone(130, 177) == 2
    assert get_zone(90, 177) == 1


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

**Последнее обновление:** 16.07.2026
