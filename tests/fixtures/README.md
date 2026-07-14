# Тестовые фикстуры (Test Fixtures)

## TCX-файлы

| Файл | Описание | Дистанция | Длительность | Пульс |
|------|----------|-----------|-------------|-------|
| `tempo_run.tcx` | Темповая тренировка, 8 трекпоинтов | ~5 км | 30 мин | 130–152 |
| `short_walk.tcx` | Короткая прогулка < 1 км (edge case) | ~0.4 км | 5 мин | 100–110 |

## FIT-файлы
В настоящий момент отсутствуют. Для тестирования FIT-парсера используйте
реальный FIT-файл от любых часов (Garmin, Coros, Polar, Suunto).

## Синтетические трекпоинты
Для unit-тестов без файлового IO используйте фабрики из `tests/helpers.py`:
```python
from tests.helpers import build_trackpoints

# Темповая
tps = build_trackpoints('tempo', distance_km=10.0, hr=150)

# Интервальная
tps = build_trackpoints('interval', intervals=5, work_pace=4.0, base_pace=5.0)

# Длинная
tps = build_trackpoints('long', duration_min=100, hr=130)

# Recovery
tps = build_trackpoints('recovery', duration_min=25, hr=110)

# С GPS-ошибками
tps = build_trackpoints('gps_errors', distance_km=3.0, error_indices=[10, 20])
```
