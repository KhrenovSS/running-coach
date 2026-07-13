# Оркестратор анализа тренировок: GPS, сегментация, классификация, погода
# Training analysis orchestrator: GPS, segmentation, classification, weather

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from src.utils.logger import get_logger
from src.parsers.gps import clean_trackpoints
from src.parsers.weather import fetch_weather, get_weather_code_at_time, get_temp_at_time
from src.analysis.hr_zones import get_zone
from src.analysis.segment import build_time_in_zones, segment_by_pace
from src.analysis.classify import classify_training
from src.analysis.oscillation import detect_pace_oscillations, compute_hr_lag_correlation
from src.analysis.utils import format_duration, calc_elevation, find_timezone

logger = get_logger("analysis")


def process_trackpoints(trackpoints: list[dict], start_time_utc: datetime,
                         max_hr: int = 177, max_credible_pace: float = 3.0,
                         max_gps_jump_m: float = 100.0, min_hr_for_fast_pace: int = 130,
                         pace_gap: float = 1.0,
                         interval_min_phase_duration: int = 15,
                         interval_hr_lag_sec: int = 5,
                         interval_min_oscillations: int = 3) -> dict | None:
    """
    Полный пайплайн анализа тренировки из трекпоинтов.
    Full training analysis pipeline from trackpoints.

    Пайплайн:
    1. Очистка GPS (gps.py)
    2. Накопительная дистанция
    3. Пульсовые зоны (segment.py → hr_zones.py)
    4. Сегментация по темпу + осцилляции (segment.py + oscillation.py)
    5. Классификация (classify.py)
    6. Осцилляции темпа + HR-lag (oscillation.py) — НОВОЕ
    7. Погода, каденс, высота
    8. HR/pace серия для графика
    """
    if len(trackpoints) < 2:
        return None

    if start_time_utc.tzinfo is None:
        start_time_utc = start_time_utc.replace(tzinfo=timezone.utc)

    trackpoints, cleaning_log = clean_trackpoints(
        trackpoints, max_credible_pace, max_gps_jump_m, min_hr_for_fast_pace
    )

    if len(trackpoints) < 2:
        return _empty_result(start_time_utc, cleaning_log)

    # Накопительная дистанция с фильтрацией аномальных скачков
    # (Cumulative distance with anomalous jump filtering)
    orig_dists = [tp['dist'] for tp in trackpoints]
    cumulative = 0.0
    for i, tp in enumerate(trackpoints):
        if orig_dists[i] is None:
            continue
        if i == 0:
            cumulative = orig_dists[i]
            tp['dist'] = cumulative
            continue
        prev_orig = orig_dists[i-1]
        if prev_orig is not None and tp['time'] is not None and trackpoints[i-1]['time'] is not None:
            raw_delta = orig_dists[i] - prev_orig
            t_delta = (tp['time'] - trackpoints[i-1]['time']).total_seconds() / 60
            if raw_delta > 0 and t_delta > 0:
                pace = t_delta / (raw_delta / 1000)
                if pace >= max_credible_pace:
                    cumulative += raw_delta
            elif raw_delta > 0:
                cumulative += raw_delta
        tp['dist'] = cumulative

    hr_values = [tp['hr'] for tp in trackpoints if tp['hr'] is not None]
    distances = [tp['dist'] for tp in trackpoints if tp['dist'] is not None]
    if not distances or not hr_values:
        return _empty_result(start_time_utc, cleaning_log)

    total_dist_km = distances[-1] / 1000
    avg_hr = round(sum(hr_values) / len(hr_values))
    max_hr_val = max(hr_values)

    start_ts = trackpoints[0]['time']
    times = []
    hrs = []
    dists = []
    if start_ts:
        for tp in trackpoints:
            if tp['time'] and tp['hr'] is not None and tp['dist'] is not None:
                t_sec = (tp['time'] - start_ts).total_seconds()
                times.append(t_sec)
                hrs.append(tp['hr'])
                dists.append(tp['dist'])

    time_in_zone, z4_plus_segments, total_duration_min = build_time_in_zones(trackpoints, max_hr)

    segments, var_count = segment_by_pace(
        trackpoints, max_hr, total_dist_km,
        min_oscillations=interval_min_oscillations,
        pace_gap=pace_gap,
        min_phase_duration_sec=interval_min_phase_duration,
    )

    # НОВОЕ: осцилляции темпа + HR-lag корреляция
    # (NEW: pace oscillations + HR lag correlation)
    oscillation_count = 0
    hr_correlated = False
    if len(times) >= 10:
        # Сгладить темп для осцилляций (Smooth pace for oscillation detection)
        raw_pace_for_osc = [None] * len(times)
        pace_dist = 250
        for i in range(len(times)):
            lo = i
            while lo >= 0 and dists[i] - dists[lo] < pace_dist:
                lo -= 1
            lo = max(0, lo)
            d_dist = dists[i] - dists[lo]
            d_time = times[i] - times[lo]
            if d_time >= 10 and d_dist >= 100:
                raw_pace_for_osc[i] = (d_time / 60) / (d_dist / 1000)

        # Заполнить пропуски линейной интерполяцией (Fill gaps with linear interpolation)
        filled_paces = _interpolate_paces(raw_pace_for_osc)
        if filled_paces:
            smoothed_osc = _smooth_paces_for_oscillation(filled_paces)
            oscillation_count, _ = detect_pace_oscillations(
                smoothed_osc, times, pace_gap=pace_gap,
                min_phase_duration_sec=interval_min_phase_duration,
            )
            _, hr_correlated = compute_hr_lag_correlation(
                times, filled_paces, hrs, lag_sec=interval_hr_lag_sec,
            )

    t_type, segments_count = classify_training(
        var_count, time_in_zone, total_duration_min, max_hr,
        z4_plus_segments, avg_hr,
        oscillation_count=oscillation_count,
        hr_correlated=hr_correlated,
        min_oscillations=interval_min_oscillations,
    )

    hr_pace_series = _build_hr_pace_series(times, hrs, dists, var_count)

    positions = [(tp['lat'], tp['lon']) for tp in trackpoints if tp['lat'] is not None and tp['lon'] is not None]
    tz_name = find_timezone(positions)
    local_tz = ZoneInfo(tz_name) if tz_name else ZoneInfo("Europe/Moscow")
    begin_ts = start_time_utc

    avg_temperature = None
    weather_code = None
    total_elevation_gain = None
    total_elevation_loss = None
    altitudes_all = [tp['alt'] for tp in trackpoints if tp['alt'] is not None]
    if altitudes_all:
        total_elevation_gain, total_elevation_loss = calc_elevation(altitudes_all)

    if positions:
        mid_idx = len(positions) // 2
        center_lat, center_lon = positions[mid_idx]
        begin_local = start_time_utc.astimezone(local_tz)
        date_str = begin_local.strftime("%Y-%m-%d")
        weather = fetch_weather(center_lat, center_lon, date_str)
        if weather:
            avg_temperature = get_temp_at_time(weather, begin_local)
            weather_code = get_weather_code_at_time(weather, begin_local)
            cumul_min = 0.0
            for seg in segments:
                seg_mid_min = cumul_min + seg['duration_min'] / 2
                seg_dt = begin_local + timedelta(minutes=seg_mid_min)
                seg['temperature'] = get_temp_at_time(weather, seg_dt)
                seg['weather_code'] = get_weather_code_at_time(weather, seg_dt)
                cumul_min += seg['duration_min']

    all_cads = [tp['cad'] for tp in trackpoints if tp['cad'] is not None]
    avg_cadence = round(sum(all_cads) / len(all_cads)) if all_cads else None

    result = {
        'begin_ts': begin_ts,
        'total_distance_km': total_dist_km,
        'avg_heart_rate': avg_hr,
        'max_heart_rate': max_hr_val,
        'training_type': t_type,
        'segments_count': segments_count,
        'duration_minutes': round(total_duration_min, 1),
        'segments_json': segments,
        'hr_pace_series': hr_pace_series,
        'avg_temperature': avg_temperature,
        'weather_code': weather_code,
        'elevation_gain': total_elevation_gain,
        'elevation_loss': total_elevation_loss,
        'avg_cadence': avg_cadence,
        'timezone': tz_name,
        'trackpoints_json': _serialize_trackpoints(trackpoints),
    }

    if cleaning_log:
        result['cleaning_log'] = cleaning_log
    else:
        if result['duration_minutes'] < 2.0 and result['total_distance_km'] > 0.3:
            result['suspect_flags'] = ['too_short']

    return result


def _empty_result(start_time_utc: datetime, cleaning_log: list) -> dict:
    """Пустой результат при ошибке или слишком короткой тренировке"""
    return {
        'begin_ts': start_time_utc,
        'total_distance_km': 0,
        'avg_heart_rate': 0,
        'max_heart_rate': 0,
        'training_type': 'invalid',
        'segments_count': 0,
        'duration_minutes': 0,
        'segments_json': [],
        'hr_pace_series': [],
        'avg_temperature': None,
        'weather_code': None,
        'elevation_gain': 0,
        'elevation_loss': 0,
        'avg_cadence': None,
        'timezone': None,
        'cleaning_log': cleaning_log,
    }


def _interpolate_paces(raw_paces: list[float | None]) -> list[float]:
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


def _smooth_paces_for_oscillation(paces: list[float], window: int = 5) -> list[float]:
    """Сглаживание темпа для детекции осцилляций (Smooth pace for oscillation detection)"""
    n = len(paces)
    return [sum(paces[max(0, i-window):min(n, i+window+1)]) /
            (min(n, i+window+1) - max(0, i-window))
            for i in range(n)]


def _build_hr_pace_series(times: list[float], hrs: list[int], dists: list[float],
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

    raw_pace = [None] * len(times)
    pace_dist = 250
    for i in range(len(times)):
        lo = i
        while lo >= 0 and dists[i] - dists[lo] < pace_dist:
            lo -= 1
        lo = max(0, lo)
        d_dist = dists[i] - dists[lo]
        d_time = times[i] - times[lo]
        if d_time >= 10 and d_dist >= 100:
            raw_pace[i] = (d_time / 60) / (d_dist / 1000)

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


def _serialize_trackpoints(trackpoints: list[dict]) -> list[dict]:
    """
    Сериализовать трекпоинты для JSON-хранилища (Serialize trackpoints for JSON storage)
    Конвертирует datetime → ISO-строку для JSON. Сохраняет None-значения
    для обратной совместимости при восстановлении.
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
