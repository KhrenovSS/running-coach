from datetime import datetime
import httpx
from src.utils.logger import get_logger

logger = get_logger("parsers.weather")

_weather_cache = {}

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
    url = "https://archive-api.open-meteo.com/v1/archive"
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
            _weather_cache[key] = result
            return result
    except (KeyError, httpx.HTTPError, ValueError) as e:
        logger.debug("Weather fetch error: %s", e)
    return None


def get_weather_code_at_time(weather, dt_local):
    if not weather:
        return None
    target_ts = dt_local.timestamp()
    best = None
    best_diff = float('inf')
    for t, code in zip(weather["times"], weather["codes"]):
        if code is None:
            continue
        t_dt = datetime.fromisoformat(t)
        diff = abs(t_dt.timestamp() - target_ts)
        if diff < best_diff:
            best_diff = diff
            best = int(code)
    return best


def get_temp_at_time(weather, dt_local):
    if not weather:
        return None
    target_ts = dt_local.timestamp()
    best = None
    best_diff = float('inf')
    for t, temp in zip(weather["times"], weather["temps"]):
        if temp is None:
            continue
        t_dt = datetime.fromisoformat(t)
        diff = abs(t_dt.timestamp() - target_ts)
        if diff < best_diff:
            best_diff = diff
            best = round(temp)
    return best
