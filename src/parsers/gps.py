from math import radians, cos, sin, sqrt, asin
from src.utils.logger import get_logger

logger = get_logger("parsers.gps")


def haversine_m(lat1, lon1, lat2, lon2):
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return 6371000 * 2 * asin(sqrt(min(a, 1)))


def clean_trackpoints(trackpoints, max_credible_pace=3.0, max_gps_jump_m=100.0, min_hr_for_fast_pace=130):
    original_count = len(trackpoints)
    if original_count < 3:
        return trackpoints, []

    cleaning_log = []
    bad_indices = set()

    for i in range(1, original_count - 1):
        prev = trackpoints[i-1]
        cur = trackpoints[i]
        nxt = trackpoints[i+1]
        if cur['lat'] is None or cur['lon'] is None:
            continue
        if prev['lat'] is None or prev['lon'] is None or nxt['lat'] is None or nxt['lon'] is None:
            continue
        d1 = haversine_m(prev['lat'], prev['lon'], cur['lat'], cur['lon'])
        d2 = haversine_m(cur['lat'], cur['lon'], nxt['lat'], nxt['lon'])
        d_skip = haversine_m(prev['lat'], prev['lon'], nxt['lat'], nxt['lon'])
        if d1 > max_gps_jump_m and d_skip < d1 * 0.5:
            bad_indices.add(i)

    for i in range(1, original_count):
        prev = trackpoints[i-1]
        cur = trackpoints[i]
        if prev['time'] and cur['time'] and prev['dist'] is not None and cur['dist'] is not None:
            delta_t = (cur['time'] - prev['time']).total_seconds() / 60
            delta_d = max(0, cur['dist'] - prev['dist'])
            if delta_d > 0 and delta_t > 0:
                pace = delta_t / (delta_d / 1000)
                hr = cur.get('hr')
                if pace < max_credible_pace and (hr is None or hr < min_hr_for_fast_pace):
                    bad_indices.add(i)
                    bad_indices.add(i-1)

    if bad_indices:
        sorted_bad = sorted(bad_indices)
        groups = []
        start = sorted_bad[0]
        end = sorted_bad[0]
        for idx in sorted_bad[1:]:
            if idx == end + 1:
                end = idx
            else:
                groups.append((start, end))
                start = idx
                end = idx
        groups.append((start, end))

        for gs, ge in groups:
            gs_t = trackpoints[gs]['time']
            ge_t = trackpoints[ge]['time']
            segment_dur = (ge_t - gs_t).total_seconds() if gs_t and ge_t else 0
            segment_dist = max(0, (trackpoints[ge]['dist'] or 0) - (trackpoints[gs]['dist'] or 0))
            reasons = []
            mid = trackpoints[(gs + ge) // 2]
            if mid['lat'] is not None and mid['lon'] is not None:
                d1 = haversine_m(trackpoints[max(0,gs-1)]['lat'] if trackpoints[max(0,gs-1)]['lat'] else mid['lat'],
                                  trackpoints[max(0,gs-1)]['lon'] if trackpoints[max(0,gs-1)]['lon'] else mid['lon'],
                                  mid['lat'], mid['lon'])
                if d1 > max_gps_jump_m:
                    reasons.append('gps_spike')
            if segment_dur > 0 and segment_dist > 0:
                pace = (segment_dur / 60) / (segment_dist / 1000)
                if pace < max_credible_pace:
                    reasons.append('pace_impossible')
            if not reasons:
                reasons.append('anomaly')
            cleaning_log.append({
                'removed_count': ge - gs + 1,
                'removed_dist_m': round(segment_dist),
                'removed_dur_s': round(segment_dur),
                'reason': reasons,
            })

        trackpoints = [tp for i, tp in enumerate(trackpoints) if i not in bad_indices]

    if len(trackpoints) < 2:
        cleaning_log.append({
            'removed_count': original_count,
            'removed_dist_m': 0,
            'removed_dur_s': 0,
            'reason': ['too_short'],
        })

    return trackpoints, cleaning_log
