# Сегментация тренировок: time-in-zones, сегментация по темпу, осцилляции
# Training segmentation: time-in-zones, pace-based segmentation, oscillations

from src.analysis.hr_zones import get_zone, get_band
from src.analysis.utils import format_duration, format_pace, calc_elevation
from src.analysis.oscillation import detect_pace_oscillations

# Константы сегментации (Segmentation constants)
MIN_SEGMENT_DIST_M = 200
PACE_SMOOTH_WINDOW = 5
CHANGE_POINT_WINDOW = 10
CHANGE_POINT_MIN_DIFF = 0.3


def build_time_in_zones(trackpoints: list[dict], max_hr: int) -> tuple[dict, list[dict], float]:
    """
    Рассчитать время в пульсовых зонах и найти длинные Z4+ сегменты.
    Calculate time in HR zones and find long Z4+ segments.

    Args:
        trackpoints: список трекпоинтов [{time, hr, dist, ...}]
        max_hr: максимальный пульс

    Returns:
        (time_in_zone, z4_plus_segments, total_duration_min)
    """
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

    return time_in_zone, z4_plus_segments, total_duration_min


def _compute_per_point_pace(trackpoints: list[dict], window_m: int = 50) -> list[dict]:
    """
    Вычислить темп для каждой точки через скользящее окно.
    Calculate per-point pace using a rolling window.
    """
    points = []
    n = len(trackpoints)
    raw_dd = [0.0]
    raw_dt = [0.0]
    for i in range(1, n):
        dd = max(0, trackpoints[i]['dist'] - trackpoints[i-1]['dist']) if trackpoints[i]['dist'] is not None and trackpoints[i-1]['dist'] is not None else 0
        dt = (trackpoints[i]['time'] - trackpoints[i-1]['time']).total_seconds() if trackpoints[i]['time'] and trackpoints[i-1]['time'] else 0
        raw_dd.append(dd)
        raw_dt.append(dt)

    for i in range(n):
        cur = trackpoints[i]
        if cur['time'] is None or cur['dist'] is None:
            continue
        lo = i
        while lo >= 0 and trackpoints[i]['dist'] - trackpoints[lo]['dist'] < window_m:
            lo -= 1
        lo = max(0, lo)
        w_dist = max(0, trackpoints[i]['dist'] - trackpoints[lo]['dist'])
        w_time = (trackpoints[i]['time'] - trackpoints[lo]['time']).total_seconds()
        if w_dist < 10 or w_time < 2:
            continue
        pace = (w_time / 60) / (w_dist / 1000)
        if not (3.0 < pace < 12.0):
            continue
        points.append({
            'dist': cur['dist'],
            'dist_delta': raw_dd[i],
            'time_delta_sec': raw_dt[i],
            'hr': cur['hr'],
            'cad': cur['cad'],
            'alt': cur.get('alt'),
            'pace': pace,
            'time': cur['time'],
        })
    return points


def _smooth(values: list[float], window: int) -> list[float]:
    """Скользящее среднее (Moving average smoothing)"""
    return [sum(values[max(0, i - window):min(len(values), i + window + 1)]) /
            (min(len(values), i + window + 1) - max(0, i - window))
            for i in range(len(values))]


def _find_change_points(values: list[float], window: int = CHANGE_POINT_WINDOW,
                         min_diff: float = CHANGE_POINT_MIN_DIFF) -> list[int]:
    """
    Поиск точек смены темпа через скользящее окно.
    Find pace change points using a sliding window.
    """
    n = len(values)
    if n < window * 2 + 1:
        return []
    diffs = []
    for i in range(window, n - window):
        left_avg = sum(values[i - window:i]) / window
        right_avg = sum(values[i:i + window]) / window
        diff = abs(right_avg - left_avg)
        diffs.append({'idx': i, 'diff': diff})
    peaks = []
    for j in range(1, len(diffs) - 1):
        if diffs[j]['diff'] >= diffs[j-1]['diff'] and diffs[j]['diff'] > diffs[j+1]['diff']:
            if diffs[j]['diff'] >= min_diff:
                peaks.append(diffs[j]['idx'])
    return peaks


def _build_segment_stats(chunk_points: list[dict], max_hr: int) -> dict | None:
    """Собрать статистику сегмента из точек (Build segment stats from points)"""
    if len(chunk_points) < 2:
        return None
    sub_dur = 0.0
    sub_dist = 0.0
    sub_hrs = []
    sub_cads = []
    sub_alts = []
    for p in chunk_points:
        sub_dur += p['time_delta_sec'] / 60
        sub_dist += p['dist_delta']
        if p['hr'] is not None:
            sub_hrs.append((p['hr'], p['time_delta_sec'] / 60))
        if p['cad'] is not None:
            sub_cads.append((p['cad'], p['time_delta_sec'] / 60))
        if p['alt'] is not None:
            sub_alts.append(p['alt'])
    if sub_dist <= 0 or not sub_hrs:
        return None
    sub_dist_km = sub_dist / 1000
    total_hr_weight = sum(d for _, d in sub_hrs)
    avg_hr_seg = round(sum(h * d for h, d in sub_hrs) / total_hr_weight) if total_hr_weight > 0 else 0
    pace_val = sub_dur / sub_dist_km if sub_dist_km > 0 else None
    elev_gain, elev_loss = calc_elevation(sub_alts) if sub_alts else (None, None)
    avg_cad_seg = round(sum(c * d for c, d in sub_cads) / sum(d for _, d in sub_cads)) if sub_cads else None
    return {
        'duration_min': round(sub_dur, 1),
        'duration': format_duration(sub_dur),
        'distance_km': round(sub_dist_km, 1),
        'avg_hr': avg_hr_seg,
        'pace': format_pace(pace_val) if pace_val else None,
        'pace_min_km': round(pace_val, 2) if pace_val else None,
        'avg_cadence': avg_cad_seg,
        'zone': get_zone(avg_hr_seg, max_hr),
        'band': get_band(avg_hr_seg, max_hr),
        'elevation_gain': elev_gain,
        'elevation_loss': elev_loss,
    }


def _compute_km_variability(trackpoints: list[dict], total_dist_km: float) -> int:
    """Подсчёт вариативных км для классификации (Count variable km chunks)"""
    var_count = 0
    if total_dist_km < 0.1:
        return var_count
    num_kms = int(total_dist_km)
    km_chunks = [[] for _ in range(num_kms + 1)]
    for tp in trackpoints:
        d = tp['dist']
        if d is not None:
            idx = int(d / 1000)
            if idx < len(km_chunks):
                km_chunks[idx].append(tp)
    for chunk in km_chunks:
        if len(chunk) < 2:
            continue
        intervals = []
        prev_tp = chunk[0]
        for tp in chunk[1:]:
            if not (prev_tp['time'] and tp['time'] and prev_tp['dist'] is not None and tp['dist'] is not None):
                prev_tp = tp
                continue
            d_delta = (tp['time'] - prev_tp['time']).total_seconds() / 60
            d_dist = max(0, tp['dist'] - prev_tp['dist'])
            if d_dist > 0 and d_delta > 0:
                pace_val = d_delta / (d_dist / 1000)
                if 2.0 < pace_val < 10.0:
                    intervals.append({'pace': pace_val, 'delta': d_delta, 'dist': d_dist})
            prev_tp = tp
        if len(intervals) < 4:
            continue
        chunk_start_dist = chunk[0]['dist'] or 0
        bin_dist = 200
        bins = {}
        cumul_dist = 0.0
        for itv in intervals:
            mid_dist = chunk_start_dist + cumul_dist + itv['dist'] / 2
            cumul_dist += itv['dist']
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
        if len(bin_paces) >= 2 and (max(bin_paces) - min(bin_paces)) >= 1.0:
            var_count += 1
    return var_count


def _merge_short_segments(boundaries: list[int], min_dist_m: int, points: list[dict]) -> list[int]:
    """Удалить границы, создающие сегменты короче min_dist_m"""
    if not boundaries:
        return boundaries
    bounds = [0] + sorted(boundaries) + [len(points) - 1]
    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(bounds) - 1:
            seg_dist = points[bounds[i+1]]['dist'] - points[bounds[i]]['dist']
            if seg_dist < min_dist_m and len(bounds) > 2:
                if i == 0:
                    bounds.pop(1)
                elif i >= len(bounds) - 2:
                    bounds.pop(len(bounds) - 2)
                else:
                    left_dist = points[bounds[i]]['dist'] - points[bounds[i-1]]['dist']
                    right_dist = points[bounds[i+2]]['dist'] - points[bounds[i+1]]['dist']
                    if left_dist <= right_dist:
                        bounds.pop(i)
                    else:
                        bounds.pop(i+1)
                changed = True
                break
            i += 1
    return bounds[1:-1]


def _build_segments_from_boundaries(boundaries: list[int], points: list[dict], max_hr: int) -> list[dict]:
    """Построить сегменты из списка границ (Build segments from boundary list)"""
    segments = []
    all_bounds = sorted([0] + boundaries + [len(points)])
    for i in range(len(all_bounds) - 1):
        start = all_bounds[i]
        end = all_bounds[i+1]
        if end - start < 3:
            continue
        chunk_points = points[start:end]
        stats = _build_segment_stats(chunk_points, max_hr)
        if stats:
            segments.append(stats)
    return segments


def segment_by_pace(trackpoints: list[dict], max_hr: int, total_dist_km: float,
                     min_oscillations: int = 3, pace_gap: float = 1.0,
                     min_phase_duration_sec: int = 15) -> tuple[list[dict], int]:
    """
    Сегментация трека по смене темпа через change-point detection + осцилляции.
    Track segmentation via pace change-point detection + oscillations.

    Алгоритм:
    1. Вычислить темп для каждой точки (скользящее окно 50м)
    2. Сгладить темп (скользящее среднее)
    3. Найти change-points (скользящее окно, порог 0.3 мин/км)
    4. НОВОЕ: если мало сегментов — использовать осцилляции как границы
    5. Построить сегменты между границами

    Returns:
        (segments, var_count) — список сегментов и число вариативных км
    """
    points = _compute_per_point_pace(trackpoints)
    if len(points) < 10:
        return [], _compute_km_variability(trackpoints, total_dist_km)

    paces = [p['pace'] for p in points]
    smoothed = _smooth(paces, PACE_SMOOTH_WINDOW)

    # Поиск change-points (Change-point detection)
    change_points = _find_change_points(smoothed, window=CHANGE_POINT_WINDOW, min_diff=CHANGE_POINT_MIN_DIFF)
    boundaries = _merge_short_segments(change_points, MIN_SEGMENT_DIST_M, points)

    segments = _build_segments_from_boundaries(boundaries, points, max_hr)

    # НОВОЕ: если change-point detection не дал достаточно сегментов —
    # использовать осцилляции как границы (If change-point detection yields
    # too few segments — use oscillations as boundaries)
    if len(segments) <= 2:
        times_sec = []
        for p in points:
            if p['time'] and points[0]['time']:
                times_sec.append((p['time'] - points[0]['time']).total_seconds())
            else:
                times_sec.append(0.0)
        osc_count, osc_phases = detect_pace_oscillations(
            smoothed, times_sec, pace_gap=pace_gap,
            min_phase_duration_sec=min_phase_duration_sec,
        )
        if osc_phases and len(osc_phases) >= min_oscillations:
            osc_boundaries = [p['end_idx'] for p in osc_phases if p['end_idx'] < len(points)]
            osc_boundaries = _merge_short_segments(osc_boundaries, MIN_SEGMENT_DIST_M, points)
            osc_segments = _build_segments_from_boundaries(osc_boundaries, points, max_hr)
            if len(osc_segments) > len(segments):
                segments = osc_segments

    # Fallback: км-сегменты (Fallback: km-based segments)
    if not segments:
        return _km_segment_fallback(trackpoints, max_hr, total_dist_km)

    var_count = _compute_km_variability(trackpoints, total_dist_km)
    return segments, var_count


def _km_segment_fallback(trackpoints: list[dict], max_hr: int, total_dist_km: float) -> tuple[list[dict], int]:
    """Запасной вариант: сегментация по км-блокам (Fallback: km-based segmentation)"""
    segments = []
    if total_dist_km < 0.1:
        return [], 0
    num_kms = int(total_dist_km)
    km_chunks = [[] for _ in range(num_kms + 1)]
    for tp in trackpoints:
        d = tp['dist']
        if d is not None:
            idx = int(d / 1000)
            if idx < len(km_chunks):
                km_chunks[idx].append(tp)
    for chunk in km_chunks:
        if len(chunk) < 2:
            continue
        points_data = []
        prev = chunk[0]
        for cur in chunk[1:]:
            if not (prev['time'] and cur['time'] and prev['dist'] is not None and cur['dist'] is not None):
                prev = cur
                continue
            d_delta = (cur['time'] - prev['time']).total_seconds() / 60
            d_dist = max(0, cur['dist'] - prev['dist'])
            if d_dist > 0 and d_delta > 0:
                points_data.append({'dist_delta': d_dist, 'time_delta_sec': d_delta, 'hr': prev['hr'], 'cad': prev['cad'], 'alt': prev['alt']})
            prev = cur
        if points_data:
            stats = _build_segment_stats(points_data, max_hr)
            if stats:
                segments.append(stats)
    var_count = _compute_km_variability(trackpoints, total_dist_km)
    return segments, var_count
