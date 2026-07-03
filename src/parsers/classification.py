def classify_training(var_count, time_in_zone, total_duration_min, max_hr, z4_plus_segments, avg_hr):
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

    return t_type, segments_count
