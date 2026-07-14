# Сегментация тренировок: time-in-zones, сегментация по темпу, осцилляции
# Training segmentation: time-in-zones, pace-based segmentation, oscillations

from src.analysis.hr_zones import get_zone, get_band
from src.analysis.utils import format_duration, format_pace, calc_elevation
from src.analysis.oscillation import detect_pace_oscillations
from src.analysis.segment_km import (
    _build_segment_stats,
    compute_km_variability,
    km_segment_fallback,
)

# Константы сегментации (Segmentation constants)
MIN_SEGMENT_DIST_M = 200
PACE_SMOOTH_WINDOW = 5
CHANGE_POINT_WINDOW_M = 200  # метров, а не точек (distance-based, not point-based)
CHANGE_POINT_MIN_DIFF = 0.5  # мин/км, базовый порог (адаптивный через _adaptive_min_diff)


def _adaptive_min_diff(paces: list[float]) -> float:
    """
    Адаптивный порог смены темпа: для монотонных бегов порог выше,
    для вариативных — ниже, чтобы ловить переходы между work/recovery.
    Adaptive min diff: higher for steady runs, lower for variable runs.
    """
    if len(paces) < 3:
        return CHANGE_POINT_MIN_DIFF
    pace_range = max(paces) - min(paces)
    if pace_range < 0.3:
        return CHANGE_POINT_MIN_DIFF
    return max(0.3, 0.25 * pace_range)


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


def _compute_per_point_pace(trackpoints: list[dict], window_m: int = 50,
                             max_credible_pace: float = 3.0) -> list[dict]:
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
        max_credible_upper = 15.0
        if not (max_credible_pace < pace < max_credible_upper):
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


def _find_change_points(values: list[float], dists: list[float],
                         window_m: int = CHANGE_POINT_WINDOW_M,
                         min_diff: float = CHANGE_POINT_MIN_DIFF) -> list[int]:
    """
    Поиск точек смены темпа через скользящее окно по дистанции.
    Find pace change points using a distance-based sliding window.
    """
    n = len(values)
    if n < 3:
        return []
    diffs = []
    for i in range(n):
        left = i
        while left > 0 and dists[i] - dists[left] < window_m:
            left -= 1
        right = i
        while right < n - 1 and dists[right] - dists[i] < window_m:
            right += 1
        n_left = i - left
        n_right = right - i
        if n_left < 1 or n_right < 1:
            continue
        left_avg = sum(values[left:i]) / n_left
        right_avg = sum(values[i:right]) / n_right
        diff = abs(right_avg - left_avg)
        diffs.append({'idx': i, 'diff': diff})
    peaks = []
    for j in range(1, len(diffs) - 1):
        if diffs[j]['diff'] >= diffs[j-1]['diff'] and diffs[j]['diff'] > diffs[j+1]['diff']:
            if diffs[j]['diff'] >= min_diff:
                peaks.append(diffs[j]['idx'])
    return peaks


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
                     min_phase_duration_sec: int = 15,
                     max_credible_pace: float = 3.0) -> tuple[list[dict], int]:
    """
    Сегментация трека по смене темпа через change-point detection + осцилляции.
    Track segmentation via pace change-point detection + oscillations.

    Алгоритм:
    1. Вычислить темп для каждой точки (скользящее окно 50м)
    2. Сгладить темп (скользящее среднее)
    3. Найти change-points (distance-based окно, адаптивный порог)
    4. Если change-points дали ≤2 сегментов — осцилляции как границы
    5. Если осцилляций нет (монотонная) — км-блоки
    6. Если осцилляции есть — защищены от km fallback

    Returns:
        (segments, var_count) — список сегментов и число вариативных км
    """
    points = _compute_per_point_pace(trackpoints, max_credible_pace=max_credible_pace)
    if len(points) < 10:
        return [], compute_km_variability(trackpoints, total_dist_km)

    paces = [p['pace'] for p in points]
    dists = [p['dist'] for p in points]
    smoothed = _smooth(paces, PACE_SMOOTH_WINDOW)

    # Адаптивный порог: для монотонных выше, для вариативных ниже
    min_diff = _adaptive_min_diff(paces)

    # Distance-based change-point detection
    change_points = _find_change_points(smoothed, dists, window_m=CHANGE_POINT_WINDOW_M, min_diff=min_diff)
    boundaries = _merge_short_segments(change_points, MIN_SEGMENT_DIST_M, points)
    segments = _build_segments_from_boundaries(boundaries, points, max_hr)

    # Если change-point detection дал мало сегментов — пробуем осцилляции
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
                # Проверка: если сегменты не имеют реальной вариативности
                # (все Z2-Z3, без значимого разброса темпа) — это шум, km fallback
                # (If segments lack real variability (all Z2-Z3, no pace spread) — noise)
                osc_paces = [s.get('pace_min_km') for s in osc_segments if s.get('pace_min_km') is not None]
                osc_zones = [s.get('zone', 1) for s in osc_segments if s.get('zone') is not None]
                max_zone = max(osc_zones) if osc_zones else 1
                has_real_intensity = max_zone >= 4
                pace_spread = (max(osc_paces) - min(osc_paces)) if len(osc_paces) >= 2 else 0
                has_real_variability = pace_spread >= 0.5

                num_kms_osc = max(1, int(total_dist_km))
                count_off_osc = len(osc_segments) < num_kms_osc * 0.5 or len(osc_segments) > num_kms_osc * 1.5
                if len(osc_segments) > 2 and count_off_osc and not (has_real_intensity and has_real_variability):
                    return km_segment_fallback(trackpoints, max_hr, total_dist_km)
                var_count = compute_km_variability(trackpoints, total_dist_km)
                return osc_segments, var_count

    # Проверка: если число сегментов сильно не соответствует числу км —
    # это шум (GPS/ходьба/остановки) — fallback на км-блоки,
    # НО только если сегменты не имеют реальной интервальной вариативности
    # (If segment count is far from km count — likely noise, fall back to km blocks,
    # but only if segments lack real interval variability)
    num_kms_chk = max(1, int(total_dist_km))
    count_off = len(segments) < num_kms_chk * 0.5 or len(segments) > num_kms_chk * 1.5
    if len(segments) > 2 and count_off:
        _seg_paces = [s.get('pace_min_km') for s in segments if s.get('pace_min_km') is not None]
        _seg_zones = [s.get('zone', 1) for s in segments if s.get('zone') is not None]
        _max_zone = max(_seg_zones) if _seg_zones else 1
        _pace_spread = (max(_seg_paces) - min(_seg_paces)) if len(_seg_paces) >= 2 else 0
        if not (_max_zone >= 4 and _pace_spread >= 0.5):
            return km_segment_fallback(trackpoints, max_hr, total_dist_km)

    # Монотонная тренировка: если change-points не нашли структуры И осцилляций нет
    # — км-блоки (каждый км + последний неполный)
    if (not segments or len(segments) <= 2) and total_dist_km >= 0.5:
        return km_segment_fallback(trackpoints, max_hr, total_dist_km)

    # Страховка: если сегментов нет совсем
    if not segments:
        return km_segment_fallback(trackpoints, max_hr, total_dist_km)

    var_count = compute_km_variability(trackpoints, total_dist_km)
    return segments, var_count
