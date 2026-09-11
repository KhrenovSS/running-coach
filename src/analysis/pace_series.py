# Ряды темпа по трекпоинтам (Pace series over trackpoints) — вынос из analysis/utils.py (#329, 11.09.2026)
#
# Скользящий темп по окну дистанции, интерполяция пропусков, сглаживание и двойная
# сглаженная серия пульс/темп для графика. Чистая математика без БД.
# (Rolling pace, gap interpolation, smoothing and the HR/pace chart series; pure math.)

from src.config.constants import CHART_MAX_PACE_MIN_PER_KM, CHART_MIN_PACE_MIN_PER_KM


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
            if CHART_MIN_PACE_MIN_PER_KM < pace_val < CHART_MAX_PACE_MIN_PER_KM:
                hr_pace_series.append({
                    'dist_km': round(dists[i] / 1000, 3),
                    'hr': smoothed_hrs[i],
                    'pace': round(pace_val, 2),
                })

    return hr_pace_series
