from datetime import datetime, timezone
import httpx
from src.config.constants import WEATHER_API_URL
from src.utils.logger import get_logger

logger = get_logger("parsers.weather")

_weather_cache: dict = {}
_WEATHER_CACHE_MAX = 500

WMO_ICONS = {
    0: "☀️", 1: "🌤️", 2: "⛅", 3: "☁️",
    45: "🌫️", 48: "🌫️",
    51: "🌦️", 53: "🌦️", 55: "🌦️", 56: "🌦️", 57: "🌦️",
    61: "🌧️", 63: "🌧️", 65: "🌧️", 66: "🌧️", 67: "🌧️",
    71: "❄️", 73: "❄️", 75: "❄️", 77: "❄️",
    80: "🌧️", 81: "🌧️", 82: "🌧️",
    85: "🌨️", 86: "🌨️",
    95: "⛈️", 96: "⛈️", 99: "⛈️",
}


def weather_icon(code):
    return WMO_ICONS.get(code, "❓")


def fetch_weather(lat, lon, date):
    key = (round(lat, 2), round(lon, 2), date)
    if key in _weather_cache:
        return _weather_cache[key]
    url = WEATHER_API_URL
    params = {
        "latitude": lat, "longitude": lon,
        "start_date": date, "end_date": date,
        "hourly": "temperature_2m,precipitation,weathercode",
        "timezone": "UTC",
    }
    try:
        r = httpx.get(url, params=params, timeout=10)
        data = r.json()
        if "hourly" in data:
            result = {
                "times": data["hourly"]["time"],
                "temps": data["hourly"]["temperature_2m"],
                "precip": data["hourly"].get("precipitation", [None] * len(data["hourly"]["time"])),
                "codes": data["hourly"].get("weathercode", [None] * len(data["hourly"]["time"])),
            }
            if len(_weather_cache) >= _WEATHER_CACHE_MAX:
                _weather_cache.pop(next(iter(_weather_cache)))
            _weather_cache[key] = result
            return result
    except (KeyError, httpx.HTTPError, ValueError) as e:
        logger.warning("Weather fetch error: %s", e)
    return None


def _epoch(t: str) -> float:
    """Часовая метка Open-Meteo (`timezone=UTC`, naive ISO) → epoch. Без явного UTC naive-строка
    трактовалась бы в поясе хоста — на не-UTC хосте все выборки сдвигались бы на его offset
    (в контейнере UTC не проявлялось; найдено 08.09.2026). (Parse the naive UTC stamp as UTC.)"""
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _get_nearest(weather, dt_local, key, cast=None):
    """Найти ближайшее по времени значение в погодных данных (Find nearest value in weather data)"""
    if not weather:
        return None
    target_ts = dt_local.timestamp()
    best = None
    best_diff = float('inf')
    values = weather.get(key, [])
    for t, val in zip(weather["times"], values):
        if val is None:
            continue
        diff = abs(_epoch(t) - target_ts)
        if diff < best_diff:
            best_diff = diff
            best = int(val) if cast == int else round(val)
    return best


def get_weather_code_at_time(weather, dt_local):
    return _get_nearest(weather, dt_local, "codes", cast=int)


def get_temp_at_time(weather, dt_local):
    return _get_nearest(weather, dt_local, "temps")


def get_avg_temp_between(weather, start_local, end_local):
    """Средняя температура по часовым значениям внутри [start, end] (#300); часовые точки берём
    с допуском ±30 мин к границам, чтобы часовая пробежка захватила два отсчёта. Нет точек в
    окне → ближайшее значение к старту (как раньше). (Mean hourly temperature over the run.)"""
    if not weather:
        return None
    lo = start_local.timestamp() - 1800
    hi = end_local.timestamp() + 1800
    vals = []
    for t, val in zip(weather["times"], weather.get("temps", [])):
        if val is None:
            continue
        ts = _epoch(t)
        if lo <= ts <= hi:
            vals.append(float(val))
    if not vals:
        return get_temp_at_time(weather, start_local)
    return round(sum(vals) / len(vals))
