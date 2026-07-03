from src.parsers.hr_zones import get_zone, get_band
from src.parsers.utils import format_duration, format_pace, calc_elevation


def build_time_in_zones(trackpoints, max_hr):
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


def segment_by_km(trackpoints, max_hr, total_dist_km):
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
                sub_cads = []
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
                    if prev_tp['cad'] is not None:
                        sub_cads.append((prev_tp['cad'], d_delta))
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
                avg_cad_seg = round(sum(c * d for c, d in sub_cads) / sum(d for _, d in sub_cads)) if sub_cads else None
                segments.append({
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
                })

    return segments, var_count
