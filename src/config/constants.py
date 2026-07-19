# Фиксированные константы проекта (Fixed project constants — not env-configurable)
import random
from typing import Final

# Пороги темпа и сегментации (Pace and segmentation thresholds)
MAX_CREDIBLE_PACE: Final[float] = 3.0
MIN_SEGMENT_DISTANCE_KM: Final[float] = 0.2
VARIABILITY_THRESHOLD: Final[float] = 1.0
PACE_SMOOTHING_WINDOW_SEC: Final[int] = 10
MIN_SMOOTHING_DISTANCE_M: Final[int] = 15
BIN_SIZE_M: Final[int] = 200

# Настройки очистки GPS (GPS cleaning settings)
MAX_GPS_JUMP_M: Final[float] = 100.0
MIN_DISTANCE_FOR_VALID_SEGMENT_M: Final[float] = 50.0

# Период синхронизации метрик здоровья (Health sync days)
HEALTH_SYNC_DAYS: Final[int] = 180

# Пороги пульсовых зон в процентах от max_hr (HR zone thresholds as % of max_hr)
HR_ZONE_1_MAX_PCT: Final[float] = 0.70
HR_ZONE_2_MAX_PCT: Final[float] = 0.80
HR_ZONE_3_MAX_PCT: Final[float] = 0.87
HR_ZONE_4_MAX_PCT: Final[float] = 0.93

# Настройки погоды Open-Meteo (Open-Meteo weather settings)
WEATHER_API_URL: Final[str] = "https://archive-api.open-meteo.com/v1/archive"
WEATHER_CACHE_TTL_SECONDS: Final[int] = 3600

# Настройки отображения (Display settings)
DISTANCE_DECIMALS: Final[int] = 1
PACE_DECIMALS: Final[int] = 2
HR_DISPLAY_UNIT: Final[str] = "уд/мин"
CADENCE_DISPLAY_UNIT: Final[str] = "spm"

# Тайминги (Timing)
CACHE_TTL_SECONDS: Final[int] = 300
SYNC_HEALTH_INTERVAL: Final[int] = 21600
SYNC_ACTIVITY_INTERVAL: Final[int] = 3600
JITTER_FACTOR: Final[float] = 0.2


def with_jitter(interval_seconds: int, factor: float = JITTER_FACTOR) -> int:
    """Применить jitter к интервалу: interval ± factor*interval.
    Apply jitter to an interval: interval ± factor*interval.
    """
    return int(interval_seconds * random.uniform(1 - factor, 1 + factor))


# Настройки детекции интервалов (Interval detection settings)
DEFAULT_PACE_THRESHOLD: Final[float] = 1.0          # мин/км — разница между базовым темпом и work-фазой
DEFAULT_MIN_PHASE_DURATION_SEC: Final[int] = 60     # сек — мин. длительность фазы
DEFAULT_MIN_PHASE_DISTANCE_M: Final[int] = 200      # м — мин. дистанция фазы
DEFAULT_HR_LAG_SEC: Final[int] = 5                  # сек — лаг пульса
DEFAULT_MIN_OSCILLATIONS: Final[int] = 3            # мин. число осцилляций для interval

# Пороги классификации тренировок (Training classification thresholds)
MIN_EFFECTIVE_PACE_GAP: Final[float] = 0.5        # мин/км — мин. adaptive gap для детекции осцилляций
RECOVERY_MAX_HR_PCT: Final[float] = 0.70          # max % от max_hr для recovery
EASY_MAX_HR_PCT: Final[float] = 0.75              # max % от max_hr для easy
EASY_MIN_Z2_PCT: Final[float] = 60.0              # мин. % времени в Z2 для easy
RECOVERY_MAX_Z4_PCT: Final[float] = 5.0           # макс. % времени в Z4+ для recovery
LONG_MAX_Z4_PCT: Final[float] = 15.0              # макс. % времени в Z4+ для long
EASY_MAX_Z4_SEGMENT_MIN: Final[float] = 3.0       # макс. длительность Z4+ сегмента для easy (мин)

# Интервалы синхронизации per-user (Per-user sync interval settings)
MIN_ACTIVITY_SYNC_INTERVAL_MIN: Final[int] = 15
MIN_HEALTH_SYNC_INTERVAL_MIN: Final[int] = 30
MAX_SYNC_INTERVAL_MIN: Final[int] = 1440
DEFAULT_ACTIVITY_SYNC_INTERVAL_MIN: Final[int] = 60
DEFAULT_HEALTH_SYNC_INTERVAL_MIN: Final[int] = 480
