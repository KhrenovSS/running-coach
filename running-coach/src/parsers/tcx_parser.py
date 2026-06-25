import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from timezonefinder import TimezoneFinder
import requests

NS = {'tcx': 'http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2'}

_tf = TimezoneFinder()
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

def get_zone(hr, max_hr):
    pct = hr / max_hr * 100
    if pct <= 70:
        return 1
    elif pct <= 80:
        return 2
    elif pct <= 87:
        return 3
    elif pct <= 93:
        return 4
    else:
        return 5

def get_band(hr, max_hr):
    zone = get_zone(hr, max_hr)
    return 'easy' if zone <= 2 else 'moderate' if zone == 3 else 'hard'

def format_pace(min_per_km):
    if min_per_km is None or min_per_km <= 0:
        return None
    m = int(min_per_km)
    s = int((min_per_km - m) * 60)
    return f"{m}:{s:02d}"

def format_duration(duration_min):
    if duration_min is None or duration_min <= 0:
        return None
    m = int(duration_min)
    s = int((duration_min - m) * 60)
    return f"{m}:{s:02d}"

def calc_elevation(altitudes):
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

def find_timezone(positions):
    for lat, lon in positions:
        if lat is not None and lon is not None:
            tz = _tf.timezone_at(lat=lat, lng=lon)
            if tz:
                return tz
    return None

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
        r = requests.get(url, params=params, timeout=10)
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
    except Exception:
        pass
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

def parse_tcx(file_path, max_hr=177):
    tree = ET.parse(file_path)
    root = tree.getroot()

    start_time_str = root.findtext('.//tcx:StartTime', namespaces=NS) or root.findtext('.//tcx:Id', namespaces=NS)
    start_time_utc = datetime.fromisoformat(start_time_str.replace('Z', '+00:00')) if start_time_str else datetime.utcnow()

    trackpoints = []
    for tp in root.findall('.//tcx:Trackpoint', NS):
        time_str = tp.findtext('tcx:Time', namespaces=NS)
        hr_str = tp.findtext('tcx:HeartRateBpm/tcx:Value', namespaces=NS)
        dist_str = tp.findtext('tcx:DistanceMeters', namespaces=NS)
        alt_str = tp.findtext('tcx:AltitudeMeters', namespaces=NS)
        lat_str = tp.findtext('tcx:Position/tcx:LatitudeDegrees', namespaces=NS)
        lon_str = tp.findtext('tcx:Position/tcx:LongitudeDegrees', namespaces=NS)
        t = datetime.fromisoformat(time_str.replace('Z', '+00:00')) if time_str else None
        hr = int(hr_str) if hr_str else None
        dist = float(dist_str) if dist_str else None
        alt = float(alt_str) if alt_str else None
        lat = float(lat_str) if lat_str else None
        lon = float(lon_str) if lon_str else None
        trackpoints.append({'time': t, 'hr': hr, 'dist': dist, 'alt': alt, 'lat': lat, 'lon': lon})

    if len(trackpoints) < 2:
        return None

    hr_values = [tp['hr'] for tp in trackpoints if tp['hr'] is not None]
    distances = [tp['dist'] for tp in trackpoints if tp['dist'] is not None]
    if not distances or not hr_values:
        return None

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

    time_in_zone = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0}
    z4_plus_segments = []
    in_z4 = False
    z4_seg_hrs = []
    total_duration_min = 0.0

    prev = trackpoints[0]
    for tp in trackpoints[1:]:
        if not (prev['time'] and tp['time']):
            prev = tp
            continue

        delta = (tp['time'] - prev['time']).total_seconds() / 60
        total_duration_min += delta

        if prev['hr'] is not None:
            zone = get_zone(prev['hr'], max_hr)
            time_in_zone[zone] += delta

            if zone >= 4:
                if not in_z4:
                    in_z4 = True
                    z4_seg_hrs = [(prev['hr'], delta)]
                else:
                    z4_seg_hrs.append((prev['hr'], delta))
            else:
                if in_z4:
                    in_z4 = False
                    seg_dur_z4 = sum(d for _, d in z4_seg_hrs)
                    seg_avg_z4 = round(sum(h * d for h, d in z4_seg_hrs) / seg_dur_z4) if seg_dur_z4 else 0
                    if seg_dur_z4 >= 0.5:
                        z4_plus_segments.append({'duration': seg_dur_z4, 'avg_hr': seg_avg_z4})
                    z4_seg_hrs = []

        prev = tp

    if in_z4 and trackpoints[-1]['time']:
        seg_dur_z4 = sum(d for _, d in z4_seg_hrs)
        seg_avg_z4 = round(sum(h * d for h, d in z4_seg_hrs) / seg_dur_z4) if seg_dur_z4 else 0
        if seg_dur_z4 >= 0.5:
            z4_plus_segments.append({'duration': seg_dur_z4, 'avg_hr': seg_avg_z4})

    segments = []
    var_count = 0

    if total_dist_km >= 0.1:
        num_kms = int(total_dist_km)
        km_chunks = [[] for _ in range(num_kms + 1)]
        for tp in trackpoints:
            d = tp['dist']
            if d is not None:
                idx = int(d / 1000)
                if idx < len(km_chunks):
                    km_chunks[idx].append(tp)

        km_stats = []
        for chunk in km_chunks:
            if len(chunk) < 2:
                continue

            intervals = []
            prev_tp = chunk[0]
            for idx, tp in enumerate(chunk[1:], 1):
                if not (prev_tp['time'] and tp['time'] and prev_tp['dist'] is not None and tp['dist'] is not None):
                    prev_tp = tp
                    continue
                d_delta = (tp['time'] - prev_tp['time']).total_seconds() / 60
                d_dist = max(0, tp['dist'] - prev_tp['dist'])
                if d_dist > 0 and d_delta > 0:
                    pace_val = d_delta / (d_dist / 1000)
                    if 2.0 < pace_val < 10.0:
                        intervals.append({
                            'pace': pace_val, 'delta': d_delta, 'dist': d_dist,
                            'hr': prev_tp['hr'], 'idx': idx,
                        })
                prev_tp = tp

            chunk_start_dist = chunk[0]['dist'] or 0
            internal_range = 0
            split_at = None

            if len(intervals) >= 4:
                bin_dist = 200
                bins = {}
                for itv in intervals:
                    mid_dist = chunk_start_dist + (itv['idx'] - 0.5) * (chunk[1]['dist'] - chunk[0]['dist']) if chunk[0]['dist'] is not None and chunk[1]['dist'] is not None else 0
                    bin_key = int((mid_dist - chunk_start_dist) / bin_dist) if (mid_dist - chunk_start_dist) >= 0 else 0
                    if bin_key not in bins:
                        bins[bin_key] = {'dur': 0.0, 'dist': 0.0}
                    bins[bin_key]['dur'] += itv['delta']
                    bins[bin_key]['dist'] += itv['dist']
                bin_paces = []
                for bk in sorted(bins):
                    bd = bins[bk]['dist']
                    if bd >= 100:
                        bin_paces.append(bins[bk]['dur'] / (bd / 1000))
                if len(bin_paces) >= 2:
                    internal_range = max(bin_paces) - min(bin_paces)
                    if internal_range >= 1.0:
                        max_diff = 0
                        for j in range(1, len(intervals)):
                            diff = abs(intervals[j]['pace'] - intervals[j-1]['pace'])
                            if diff > max_diff:
                                max_diff = diff
                                split_at = intervals[j-1]['idx']
                        if split_at < 1 or split_at >= len(chunk) - 1:
                            split_at = len(chunk) // 2

            km_stats.append({
                'chunk': chunk, 'intervals': intervals,
                'internal_range': internal_range, 'split_at': split_at,
            })

        var_count = sum(1 for ks in km_stats if ks['internal_range'] >= 1.0)

        for ks in km_stats:
            needs_split = var_count >= 3 and ks['split_at'] is not None

            if needs_split:
                chunk = ks['chunk']
                split_idx = ks['split_at']
                d1 = max(0, (chunk[split_idx]['dist'] or 0) - (chunk[0]['dist'] or 0))
                d2 = max(0, (chunk[-1]['dist'] or 0) - (chunk[split_idx]['dist'] or 0))
                if d1 >= 200 and d2 >= 200:
                    sub_chunks = [chunk[:split_idx+1], chunk[split_idx:]]
                else:
                    sub_chunks = [chunk]
            else:
                sub_chunks = [ks['chunk']]

            for sub_chunk in sub_chunks:
                if len(sub_chunk) < 2:
                    continue
                sub_dur = 0.0
                sub_dist = 0.0
                sub_hrs = []
                sub_alts = []
                prev_tp = sub_chunk[0]
                for tp in sub_chunk[1:]:
                    if not (prev_tp['time'] and tp['time'] and prev_tp['dist'] is not None and tp['dist'] is not None):
                        prev_tp = tp
                        continue
                    d_delta = (tp['time'] - prev_tp['time']).total_seconds() / 60
                    d_dist = max(0, tp['dist'] - prev_tp['dist'])
                    sub_dur += d_delta
                    sub_dist += d_dist
                    if prev_tp['hr'] is not None:
                        sub_hrs.append((prev_tp['hr'], d_delta))
                    if prev_tp['alt'] is not None:
                        sub_alts.append(prev_tp['alt'])
                    if tp['alt'] is not None:
                        sub_alts.append(tp['alt'])
                    prev_tp = tp
                if sub_dist <= 0 or not sub_hrs:
                    continue
                sub_dist_km = sub_dist / 1000
                total_hr_weight = sum(d for _, d in sub_hrs)
                avg_hr_seg = round(sum(h * d for h, d in sub_hrs) / total_hr_weight) if total_hr_weight > 0 else 0
                pace_val = sub_dur / sub_dist_km if sub_dist_km > 0 else None
                elev_gain, elev_loss = calc_elevation(sub_alts) if sub_alts else (None, None)
                segments.append({
                    'duration_min': round(sub_dur, 1),
                    'duration': format_duration(sub_dur),
                    'distance_km': round(sub_dist_km, 1),
                    'avg_hr': avg_hr_seg,
                    'pace': format_pace(pace_val) if pace_val else None,
                    'pace_min_km': round(pace_val, 2) if pace_val else None,
                    'zone': get_zone(avg_hr_seg, max_hr),
                    'band': get_band(avg_hr_seg, max_hr),
                    'elevation_gain': elev_gain,
                    'elevation_loss': elev_loss,
                })

    z2_pct = (time_in_zone[2] / total_duration_min * 100) if total_duration_min > 0 else 0
    hr_75 = 0.75 * max_hr
    long_z4 = [s for s in z4_plus_segments if s['duration'] > 5]

    if var_count >= 3:
        t_type = 'interval'
        segments_count = var_count
    elif var_count >= 1:
        t_type = 'tempo'
        segments_count = 1
    elif total_duration_min >= 90 and z2_pct >= 50 and not long_z4:
        t_type = 'long'
        segments_count = 1
    elif avg_hr <= hr_75 and not long_z4:
        t_type = 'recovery'
        segments_count = 1
    else:
        t_type = 'tempo'
        segments_count = 1

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
        begin_ts = start_time_utc.astimezone(local_tz).replace(tzinfo=None)
    else:
        begin_ts = start_time_utc.replace(tzinfo=None)

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
        date_str = begin_ts.strftime("%Y-%m-%d")
        weather = fetch_weather(center_lat, center_lon, date_str)
        if weather:
            ref_tz = ZoneInfo(tz_name) if tz_name else None
            def aware(dt_naive):
                return dt_naive.replace(tzinfo=ref_tz) if ref_tz else dt_naive
            avg_temperature = get_temp_at_time(weather, aware(begin_ts))
            weather_code = get_weather_code_at_time(weather, aware(begin_ts))
            cumul_min = 0.0
            for seg in segments:
                seg_mid_min = cumul_min + seg['duration_min'] / 2
                seg_dt = begin_ts + timedelta(minutes=seg_mid_min)
                seg['temperature'] = get_temp_at_time(weather, aware(seg_dt))
                seg['weather_code'] = get_weather_code_at_time(weather, aware(seg_dt))
                cumul_min += seg['duration_min']

    return {
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
    }
