from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from src.utils.logger import get_logger
from src.parsers.gps import clean_trackpoints
from src.parsers.weather import fetch_weather, get_weather_code_at_time, get_temp_at_time
from src.parsers.hr_zones import get_zone
from src.parsers.segmentation import build_time_in_zones, segment_by_km
from src.parsers.classification import classify_training
from src.parsers.utils import format_duration, calc_elevation, find_timezone

logger = get_logger("parsers.common")


def process_trackpoints(trackpoints, start_time_utc, max_hr=177,
                         max_credible_pace=3.0, max_gps_jump_m=100.0, min_hr_for_fast_pace=130):
    if len(trackpoints) < 2:
        return None

    if start_time_utc.tzinfo is None:
        start_time_utc = start_time_utc.replace(tzinfo=timezone.utc)

    trackpoints, cleaning_log = clean_trackpoints(
        trackpoints, max_credible_pace, max_gps_jump_m, min_hr_for_fast_pace
    )

    if len(trackpoints) < 2:
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
            'timezone': tz_name,
            'cleaning_log': cleaning_log,
        }

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

    segments, var_count = segment_by_km(trackpoints, max_hr, total_dist_km)

    t_type, segments_count = classify_training(var_count, time_in_zone, total_duration_min, max_hr, z4_plus_segments, avg_hr)

    hr_pace_series = []
    if len(times) >= 2:
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

    positions = [(tp['lat'], tp['lon']) for tp in trackpoints if tp['lat'] is not None and tp['lon'] is not None]
    tz_name = find_timezone(positions)
    if tz_name:
        local_tz = ZoneInfo(tz_name)
    else:
        local_tz = ZoneInfo("Europe/Moscow")
    begin_ts = start_time_utc
    begin_local = start_time_utc.astimezone(local_tz)

    avg_temperature = None
    weather_code = None
    total_elevation_gain = None
    total_elevation_loss = None
    altitudes_all = [tp['alt'] for tp in trackpoints if tp['alt'] is not None]
    if altitudes_all:
        eg, el = calc_elevation(altitudes_all)
        total_elevation_gain = eg
        total_elevation_loss = el

    if positions:
        mid_idx = len(positions) // 2
        center_lat, center_lon = positions[mid_idx]
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
    }

    if cleaning_log:
        result['cleaning_log'] = cleaning_log
    else:
        if result['duration_minutes'] < 2.0 and result['total_distance_km'] > 0.3:
            result['suspect_flags'] = ['too_short']

    return result
