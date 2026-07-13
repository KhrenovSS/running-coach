# Утилиты анализа: форматирование, высота, часовой пояс
# Analysis utilities: formatting, elevation, timezone

from datetime import datetime
from zoneinfo import ZoneInfo
from timezonefinder import TimezoneFinder

_tf = TimezoneFinder()


def format_pace(min_per_km: float | None) -> str | None:
    """
    Форматировать темп из мин/км в M:SS
    Format pace from min/km to M:SS
    """
    if min_per_km is None or min_per_km <= 0:
        return None
    m = int(min_per_km)
    s = int((min_per_km - m) * 60)
    return f"{m}:{s:02d}"


def format_duration(duration_min: float | None) -> str | None:
    """
    Форматировать длительность из минут в M:SS
    Format duration from minutes to M:SS
    """
    if duration_min is None or duration_min <= 0:
        return None
    m = int(duration_min)
    s = int((duration_min - m) * 60)
    return f"{m}:{s:02d}"


def calc_elevation(altitudes: list[float | None]) -> tuple[int, int]:
    """
    Рассчитать набор и спуск высоты из списка altitude
    Calculate elevation gain and loss from altitude list
    """
    gain = 0.0
    loss = 0.0
    for i in range(1, len(altitudes)):
        if altitudes[i] is not None and altitudes[i-1] is not None:
            diff = altitudes[i] - altitudes[i-1]
            if diff > 0:
                gain += diff
            else:
                loss += abs(diff)
    return round(gain), round(loss)


def find_timezone(positions: list[tuple[float | None, float | None]]) -> str | None:
    """
    Определить IANA-таймзону по GPS-координатам
    Determine IANA timezone from GPS coordinates
    """
    for lat, lon in positions:
        if lat is not None and lon is not None:
            tz = _tf.timezone_at(lat=lat, lng=lon)
            if tz:
                return tz
    return None
