# Утилиты анализа: форматирование, высота, часовой пояс, rolling pace
# Analysis utilities: formatting, elevation, timezone, rolling pace

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


def compute_rolling_pace(times_sec: list[float], dists_m: list[float],
                          window_m: int = 250,
                          min_dist_m: float = 100.0,
                          min_time_sec: float = 10.0) -> list[float | None]:
    """
    Вычислить темп через скользящее окно по дистанции.
    Compute pace via distance-based rolling window.

    Для каждой точки i: ищем точку lo, отстоящую на window_m левее,
    и вычисляем темп = delta_time / delta_distance.

    Args:
        times_sec: время (сек) для каждой точки
        dists_m: дистанция (м) для каждой точки
        window_m: размер окна в метрах
        min_dist_m: минимальная дистанция для расчёта
        min_time_sec: минимальное время для расчёта

    Returns:
        Список темпа (мин/км), None где расчёт невозможен
    """
    n = len(times_sec)
    result = [None] * n
    for i in range(n):
        lo = i
        while lo >= 0 and dists_m[i] - dists_m[lo] < window_m:
            lo -= 1
        lo = max(0, lo)
        d_dist = dists_m[i] - dists_m[lo]
        d_time = times_sec[i] - times_sec[lo]
        if d_time >= min_time_sec and d_dist >= min_dist_m:
            result[i] = (d_time / 60) / (d_dist / 1000)
    return result


def interpolate_paces(raw_paces: list[float | None]) -> list[float]:
    """Линейная интерполяция пропусков в темпе (Linear interpolation for pace gaps)"""
    result = list(raw_paces)
    for i in range(len(result)):
        if result[i] is None:
            prev_val = None
            next_val = None
            for j in range(i-1, -1, -1):
                if result[j] is not None:
                    prev_val = result[j]
                    break
            for j in range(i+1, len(result)):
                if result[j] is not None:
                    next_val = result[j]
                    break
            if prev_val is not None and next_val is not None:
                result[i] = (prev_val + next_val) / 2
            elif prev_val is not None:
                result[i] = prev_val
            elif next_val is not None:
                result[i] = next_val
    return [p if p is not None else 5.0 for p in result]


def smooth_paces(paces: list[float], window: int = 5) -> list[float]:
    """Сглаживание темпа скользящим средним (Smooth pace via moving average)"""
    n = len(paces)
    return [sum(paces[max(0, i-window):min(n, i+window+1)]) /
            (min(n, i+window+1) - max(0, i-window))
            for i in range(n)]


def is_km_segmentation(segments: list[dict], total_dist_km: float) -> bool:
    """
    Проверить, являются ли сегменты км-блоками.
    Check if segments are km-based blocks.
    Км-блок: все сегменты ~1.0км (±0.15), последний может быть короче.
    """
    if not segments:
        return False
    num_km = max(1, int(total_dist_km))
    if abs(len(segments) - num_km) > 1 and abs(len(segments) - (num_km + 1)) > 1:
        return False
    for i, s in enumerate(segments):
        d = s.get('distance_km', 0)
        if i < len(segments) - 1:
            if d < 0.85 or d > 1.15:
                return False
        else:
            if d > 1.15:
                return False
    return True


def serialize_trackpoints(trackpoints: list[dict]) -> list[dict]:
    """
    Сериализовать трекпоинты для JSON-хранилища (Serialize trackpoints for JSON storage)
    Конвертирует datetime → ISO-строку для JSON. Сохраняет None-значения.
    """
    result = []
    for tp in trackpoints:
        serialized = {}
        for k, v in tp.items():
            if hasattr(v, 'isoformat'):
                serialized[k] = v.isoformat()
            else:
                serialized[k] = v
        result.append(serialized)
    return result


def build_hr_pace_series(times: list[float], hrs: list[int], dists: list[float],
                          var_count: int) -> list[dict]:
    """Построить двойную сглаженную серию пульс/темп для графика"""
    if len(times) < 2:
        return []

    hr_window = 5 if var_count >= 3 else 40
    smoothed_hrs = list(hrs)
    for i in range(len(hrs)):
        weighted_sum = 0.0
        total_weight = 0.0
        for j in range(len(hrs)):
            dt = abs(times[i] - times[j])
            if dt < hr_window:
                w = 1.0 - dt / hr_window
                weighted_sum += hrs[j] * w
                total_weight += w
        if total_weight > 0:
            smoothed_hrs[i] = round(weighted_sum / total_weight, 1)

    raw_pace = compute_rolling_pace(times, dists)
    pace_window = 45
    smoothed_pace = [None] * len(times)
    for i in range(len(times)):
        if raw_pace[i] is None:
            continue
        weighted_sum = 0.0
        total_weight = 0.0
        for j in range(len(times)):
            if raw_pace[j] is None:
                continue
            dt = abs(times[i] - times[j])
            if dt < pace_window:
                w = 1.0 - dt / pace_window
                weighted_sum += raw_pace[j] * w
                total_weight += w
        if total_weight > 0:
            smoothed_pace[i] = weighted_sum / total_weight

    hr_pace_series = []
    for i in range(len(times)):
        if smoothed_pace[i] is None:
            continue
        weighted_sum = 0.0
        total_weight = 0.0
        for j in range(len(times)):
            if smoothed_pace[j] is None:
                continue
            dt = abs(times[i] - times[j])
            if dt < pace_window:
                w = 1.0 - dt / pace_window
                weighted_sum += smoothed_pace[j] * w
                total_weight += w
        if total_weight > 0:
            pace_val = weighted_sum / total_weight
            if 3.0 < pace_val < 10.0:
                hr_pace_series.append({
                    'dist_km': round(dists[i] / 1000, 3),
                    'hr': smoothed_hrs[i],
                    'pace': round(pace_val, 2),
                })

    return hr_pace_series
