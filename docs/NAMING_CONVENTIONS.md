# Соглашения об именовании (Naming Conventions)

> Как называть файлы, классы, функции, переменные.

## Таблица соглашений

| Элемент | Стиль | Пример |
|---------|-------|--------|
| Файлы и модули | `snake_case` | `tcx_parser.py`, `training_service.py` |
| Классы | `PascalCase` | `TrainingService`, `CorosClient` |
| Функции и методы | `snake_case` | `classify_training()`, `process_upload()` |
| Переменные | `snake_case` | `avg_heart_rate`, `total_distance_km` |
| Константы | `UPPER_SNAKE_CASE` | `DEFAULT_MAX_HR`, `HTTP_TIMEOUT` |
| Приватные методы/переменные | `_prefix` | `_internal_helper()`, `_cached_data` |
| Pydantic модели | `PascalCase` + суффикс | `TrainingCreate`, `SettingsUpdate` |
| SQLAlchemy модели | `PascalCase` | `TrainingSession`, `DailyMetrics` |
| Модули тестов | `test_*.py` | `test_classification.py` |
| Классы тестов | `TestPascalCase` | `TestTrainingClassification` |
| Фикстуры pytest | `snake_case` | `db_session`, `sample_user` |

## Примеры

### Файлы

```
✅ src/watch/coros.py
✅ src/parsers/tcx_parser.py
✅ tests/test_gps.py

❌ src/watch/CorosClient.py
❌ src/parsers/TCXParser.py
❌ tests/testGPS.py
```

### Классы

```python
# ✅
class TrainingUploadService:
    pass

class WatchAPIError(Exception):
    pass

# ❌
class trainingUploadService:
    pass

class watch_api_error(Exception):
    pass
```

### Функции

```python
# ✅
def calculate_hr_zones(max_hr: int) -> dict:
    pass

def process_trackpoints(trackpoints: list) -> list:
    pass

# ❌
def calculateHRZones(maxHR):
    pass

def ProcessTrackpoints(trackpoints):
    pass
```

### Переменные

```python
# ✅
avg_heart_rate = 150
total_distance_km = 10.5
duration_minutes = 45

# ❌
avgHeartRate = 150
totalDistance = 10.5
dur = 45
```

### Константы

```python
# ✅
from src.config import settings
from src.config.constants import MAX_CREDIBLE_PACE

timeout = settings.http_timeout
max_hr = settings.default_max_hr

# ❌
TIMEOUT = 15
MAXHR = 177
```

## Семантические правила

### Функции

Имя функции = глагол + объект:

```python
# ✅
get_training_by_id()
save_daily_metrics()
parse_tcx_file()
calculate_pace()

# ❌
training()        # непонятно, что делает
process()         # слишком общее
do_stuff()        # никогда так
```

### Сервисы

```python
# ✅
TrainingUploadService
WatchClientFactory
SettingsService

# ❌
TrainingManager
WatchHelper
SettingsHandler
```

### Boolean переменные

```python
# ✅
is_interval = True
has_gps_data = False
should_sync = True

# ❌
interval = True
gps = False
sync = True
```

## Специфика проекта

### Пульсовые зоны

```python
# ✅
hr_zone = "Z2"
max_hr = 177
avg_heart_rate = 145

# ❌
zone = "Z2"           # непонятно, чья зона
maximumHeartRate = 177
avgHR = 145
```

### Темп и дистанция

```python
# ✅
pace_min_per_km = 5.5
distance_km = 10.5
duration_minutes = 45

# ❌
pace = 5.5            # единицы не ясны
dist = 10.5
dur = 45
```

---

**Последнее обновление:** 30.06.2026
