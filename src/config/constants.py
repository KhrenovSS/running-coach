# Фиксированные константы проекта (Fixed project constants — not env-configurable)
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

# Настройки Coros API (Coros API settings)
COROS_BASE_URL: Final[str] = "https://traininghub.coros.com"
COROS_AUTH_ENDPOINT: Final[str] = "/account/v2/signin"
COROS_ACTIVITIES_ENDPOINT: Final[str] = "/activities/v2/list"
COROS_DASHBOARD_ENDPOINT: Final[str] = "/dashboard/query"
COROS_DAILY_METRICS_ENDPOINT: Final[str] = "/analyse/dayDetail/query"
COROS_ANALYSE_ENDPOINT: Final[str] = "/analyse/query"
HEALTH_SYNC_DAYS: Final[int] = 180

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

# Интервалы синхронизации per-user (Per-user sync interval settings)
MIN_ACTIVITY_SYNC_INTERVAL_MIN: Final[int] = 15
MIN_HEALTH_SYNC_INTERVAL_MIN: Final[int] = 30
MAX_SYNC_INTERVAL_MIN: Final[int] = 1440
DEFAULT_ACTIVITY_SYNC_INTERVAL_MIN: Final[int] = 60
DEFAULT_HEALTH_SYNC_INTERVAL_MIN: Final[int] = 480
