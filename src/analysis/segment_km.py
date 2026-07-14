# Км-сегментация и вариативность: fallback и классификация
# Km segmentation and variability: fallback and classification

from src.analysis.hr_zones import get_zone, get_band
from src.analysis.utils import format_duration, format_pace, calc_elevation


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


def compute_km_variability(trackpoints: list[dict], total_dist_km: float) -> int:
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


def _chunk_by_km(trackpoints: list[dict], num_kms: int) -> list[list[dict]]:
    """Разбить трекпоинты на км-блоки (Split trackpoints into km chunks)"""
    km_chunks = [[] for _ in range(num_kms + 1)]
    for tp in trackpoints:
        d = tp['dist']
        if d is not None:
            idx = int(d / 1000)
            if idx < len(km_chunks):
                km_chunks[idx].append(tp)
    return km_chunks


def km_segment_fallback(trackpoints: list[dict], max_hr: int, total_dist_km: float) -> tuple[list[dict], int]:
    """Запасной вариант: сегментация по км-блокам (Fallback: km-based segmentation)"""
    segments = []
    if total_dist_km < 0.1:
        return [], 0
    num_kms = int(total_dist_km)
    km_chunks = _chunk_by_km(trackpoints, num_kms)
    for chunk in km_chunks:
        if len(chunk) < 2:
            continue
        points_data = []
        prev = chunk[0]
        for cur in chunk[1:]:
            if not (prev['time'] and cur['time'] and prev['dist'] is not None and cur['dist'] is not None):
                prev = cur
                continue
            d_delta = (cur['time'] - prev['time']).total_seconds()
            d_dist = max(0, cur['dist'] - prev['dist'])
            if d_dist > 0 and d_delta > 0:
                points_data.append({'dist_delta': d_dist, 'time_delta_sec': d_delta, 'hr': prev['hr'], 'cad': prev['cad'], 'alt': prev['alt']})
            prev = cur
        if points_data:
            stats = _build_segment_stats(points_data, max_hr)
            if stats:
                segments.append(stats)
    var_count = compute_km_variability(trackpoints, total_dist_km)
    return segments, var_count
