"""
Централизованные константы проекта (Project centralized constants)

Все magic numbers, настройки и конфигурация — здесь.
Не используй hardcoded значения в коде — импортируй из CONFIG.

All magic numbers, settings and configuration — here.
Don't use hardcoded values in code — import from CONFIG.
"""

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class TimingConfig:
    """Тайминги и интервалы (Timing and intervals)"""
    CACHE_TTL_SECONDS: Final[int] = 300                    # 5 минут (5 minutes)
    SYNC_HEALTH_INTERVAL: Final[int] = 21600               # 6 часов (6 hours)
    SYNC_ACTIVITY_INTERVAL: Final[int] = 3600              # 1 час (1 hour)
    HTTP_TIMEOUT: Final[int] = 15                          # секунд (seconds)
    JITTER_FACTOR: Final[float] = 0.2                      # ±20% джитер (jitter)
    DEBOUNCE_DELAY_MS: Final[int] = 500                    # задержка ввода (input delay)


@dataclass(frozen=True)
class HRZonesConfig:
    """Пульсовые зоны — процент от max_hr (Heart rate zones — % of max_hr)"""
    DEFAULT_MAX_HR: Final[int] = 177
    
    # Границы зон в % от max_hr (Zone boundaries in % of max_hr)
    Z1_MIN_PCT: Final[int] = 60
    Z1_MAX_PCT: Final[int] = 70
    
    Z2_MIN_PCT: Final[int] = 70
    Z2_MAX_PCT: Final[int] = 80
    
    Z3_MIN_PCT: Final[int] = 80
    Z3_MAX_PCT: Final[int] = 87
    
    Z4_MIN_PCT: Final[int] = 87
    Z4_MAX_PCT: Final[int] = 93
    
    Z5_MIN_PCT: Final[int] = 93
    Z5_MAX_PCT: Final[int] = 100


@dataclass(frozen=True)
class PaceThresholds:
    """Пороги темпа и сегментации (Pace and segmentation thresholds)"""
    MAX_CREDIBLE_PACE: Final[float] = 3.0          # мин/км — максимально быстрый (min/km — fastest possible)
    MIN_SEGMENT_DISTANCE_KM: Final[float] = 0.2    # минимальная длина сегмента (minimum segment length)
    VARIABILITY_THRESHOLD: Final[float] = 1.0      # мин/км — порог вариативности км (min/km — km variability threshold)
    PACE_SMOOTHING_WINDOW_SEC: Final[int] = 10     # окно сглаживания темпа (pace smoothing window)
    MIN_SMOOTHING_DISTANCE_M: Final[int] = 15      # мин. дистанция для сглаживания (min distance for smoothing)
    BIN_SIZE_M: Final[int] = 200                   # размер бина для анализа (bin size for analysis)


@dataclass(frozen=True)
class GPSCleaningConfig:
    """Настройки очистки GPS (GPS cleaning settings)"""
    MAX_GPS_JUMP_M: Final[float] = 100.0           # максимальный скачок GPS (max GPS jump)
    MIN_DISTANCE_FOR_VALID_SEGMENT_M: Final[float] = 50.0  # мин. дистанция валидного сегмента


@dataclass(frozen=True)
class CorosAPIConfig:
    """Настройки Coros API (Coros API settings)"""
    BASE_URL: Final[str] = "https://traininghub.coros.com"
    AUTH_ENDPOINT: Final[str] = "/account/v2/signin"
    ACTIVITIES_ENDPOINT: Final[str] = "/activities/v2/list"
    DASHBOARD_ENDPOINT: Final[str] = "/dashboard/query"
    DAILY_METRICS_ENDPOINT: Final[str] = "/analyse/dayDetail/query"
    ANALYSE_ENDPOINT: Final[str] = "/analyse/query"
    HEALTH_SYNC_DAYS: Final[int] = 180             # дней для синхронизации (days to sync)


@dataclass(frozen=True)
class WeatherConfig:
    """Настройки погоды Open-Meteo (Open-Meteo weather settings)"""
    API_URL: Final[str] = "https://archive-api.open-meteo.com/v1/archive"
    CACHE_TTL_SECONDS: Final[int] = 3600           # 1 час (1 hour)


@dataclass(frozen=True)
class DisplayConfig:
    """Настройки отображения (Display settings)"""
    DISTANCE_DECIMALS: Final[int] = 1              # знаки после запятой для км (decimals for km)
    PACE_DECIMALS: Final[int] = 2                  # знаки после запятой для темпа (decimals for pace)
    HR_DISPLAY_UNIT: Final[str] = "уд/мин"         # единица измерения пульса (HR unit)
    CADENCE_DISPLAY_UNIT: Final[str] = "spm"       # единица измерения каденса (cadence unit)


@dataclass(frozen=True)
class AuthConfig:
    """Настройки аутентификации (Authentication settings)"""
    TOKEN_TTL_MINUTES: Final[int] = 30                     # время жизни регистрационного токена (reg token TTL)
    PASSWORD_MIN_LENGTH: Final[int] = 6                    # мин. длина пароля (min password length)
    SESSION_TTL_DAYS: Final[int] = 7                       # срок жизни сессии (session lifetime)


@dataclass(frozen=True)
class CONFIG:
    """
    Все настройки проекта (All project settings)
    
    Использование (Usage):
        from src.config.constants import CONFIG
        max_hr = CONFIG.HR_ZONES.DEFAULT_MAX_HR
        timeout = CONFIG.TIMING.HTTP_TIMEOUT
    """
    TIMING: Final[TimingConfig] = TimingConfig()
    HR_ZONES: Final[HRZonesConfig] = HRZonesConfig()
    PACE: Final[PaceThresholds] = PaceThresholds()
    GPS: Final[GPSCleaningConfig] = GPSCleaningConfig()
    COROS: Final[CorosAPIConfig] = CorosAPIConfig()
    WEATHER: Final[WeatherConfig] = WeatherConfig()
    DISPLAY: Final[DisplayConfig] = DisplayConfig()
    AUTH: Final[AuthConfig] = AuthConfig()
    
    # Пути (Paths)
    DB_PATH: Final[str] = "running_coach.db"
    UPLOAD_DIR: Final[str] = "uploads"
    LOG_FILE: Final[str] = "app.log"


# === Утилиты для расчёта пульсовых зон ===
# === Utilities for HR zone calculation ===

def calculate_hr_zones(max_hr: int) -> dict[str, tuple[int, int]]:
    """
    Рассчитать пульсовые зоны для заданного max_hr
    Calculate heart rate zones for given max_hr
    
    Returns:
        dict с зонами: {"Z1": (min, max), "Z2": (min, max), ...}
    """
    zones_config = CONFIG.HR_ZONES
    return {
        "Z1": (int(max_hr * zones_config.Z1_MIN_PCT / 100), int(max_hr * zones_config.Z1_MAX_PCT / 100)),
        "Z2": (int(max_hr * zones_config.Z2_MIN_PCT / 100), int(max_hr * zones_config.Z2_MAX_PCT / 100)),
        "Z3": (int(max_hr * zones_config.Z3_MIN_PCT / 100), int(max_hr * zones_config.Z3_MAX_PCT / 100)),
        "Z4": (int(max_hr * zones_config.Z4_MIN_PCT / 100), int(max_hr * zones_config.Z4_MAX_PCT / 100)),
        "Z5": (int(max_hr * zones_config.Z5_MIN_PCT / 100), int(max_hr * zones_config.Z5_MAX_PCT / 100)),
    }


def get_hr_zone(hr: int, max_hr: int) -> str:
    """
    Определить зону пульса для значения HR
    Determine heart rate zone for HR value
    
    Returns:
        "Z1", "Z2", "Z3", "Z4", "Z5" или "below" если ниже Z1
    """
    zones = calculate_hr_zones(max_hr)
    for zone_name in reversed(["Z5", "Z4", "Z3", "Z2", "Z1"]):
        zone_min, zone_max = zones[zone_name]
        if hr >= zone_min:
            return zone_name
    return "below"
