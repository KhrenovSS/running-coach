# Фабрики синтетических трекпоинтов для тестов
# Synthetic trackpoint factories for analysis tests

from datetime import datetime, timedelta, timezone


def _make_tp(time, dist, hr, alt=None, lat=55.75, lon=37.62, cad=None):
    return {
        'time': time,
        'hr': hr,
        'dist': dist,
        'alt': alt,
        'lat': lat,
        'lon': lon,
        'cad': cad,
    }


def _pace_to_dist_delta(pace_min_km: float, dt_sec: float) -> float:
    if pace_min_km <= 0:
        return 0.0
    return (dt_sec / 60) / pace_min_km * 1000


def build_trackpoints(
    training_type: str = 'tempo',
    base_pace: float = 5.0,
    distance_km: float | None = None,
    duration_min: float | None = None,
    hr: int = 140,
    max_hr: int = 177,
    start_time: datetime | None = None,
    work_pace: float = 4.0,
    intervals: int = 5,
    work_dist_m: float = 400,
    recovery_dist_m: float = 400,
    warmup_km: float = 1.0,
    cooldown_km: float = 1.0,
    error_indices: list[int] | None = None,
    **kwargs,
) -> list[dict]:
    """
    Универсальная фабрика синтетических трекпоинтов.
    Universal factory for synthetic trackpoints.

    Параметры (Parameters):
        training_type: 'tempo' | 'interval' | 'long' | 'recovery' | 'gps_errors'
        base_pace: базовый/восстановительный темп (мин/км)
        distance_km: дистанция для tempo/gps_errors
        duration_min: длительность для long/recovery
        hr: средний пульс
        max_hr: макс. пульс (для recovery)
        start_time: время старта
        work_pace: темп ускорений (для interval)
        intervals: число повторений (для interval)
        work_dist_m: дистанция ускорения, м (для interval)
        recovery_dist_m: дистанция восстановления, м (для interval)
        warmup_km: разминка, км (для interval)
        cooldown_km: заминка, км (для interval)
        error_indices: индексы точек с GPS-ошибкой (для gps_errors)
    """
    if start_time is None:
        start_time = datetime(2026, 7, 1, 8, 0, 0, tzinfo=timezone.utc)

    if training_type == 'interval':
        return _build_interval(start_time, base_pace, work_pace, warmup_km, cooldown_km,
                                intervals, work_dist_m, recovery_dist_m, hr, max_hr)
    elif training_type == 'tempo':
        dist_km = distance_km or 10.0
        return _build_tempo(start_time, base_pace, dist_km, hr)
    elif training_type == 'long':
        dur = duration_min or 100.0
        return _build_long(start_time, base_pace, dur, hr)
    elif training_type == 'recovery':
        dur = duration_min or 25.0
        return _build_recovery(start_time, base_pace, dur, hr, max_hr)
    elif training_type == 'gps_errors':
        dist_km = distance_km or 3.0
        return _build_gps_errors(start_time, base_pace, dist_km, error_indices)
    raise ValueError(f"Unknown training_type: {training_type}")


def _build_interval(start_time, base_pace, work_pace, warmup_km, cooldown_km,
                     intervals, work_dist_m, recovery_dist_m, base_hr, work_hr):
    trackpoints = []
    t = start_time
    dist = 0.0
    lat, lon = 55.75, 37.62
    dt_sec = 5.0
    recovery_hr = base_hr + 10

    warmup_m = warmup_km * 1000
    while dist < warmup_m:
        dd = _pace_to_dist_delta(base_pace, dt_sec)
        dist += dd
        trackpoints.append(_make_tp(t, dist, base_hr, alt=150, lat=lat, lon=lon, cad=170))
        t += timedelta(seconds=dt_sec)
        lat += 0.00001
        lon += 0.00001

    for _ in range(intervals):
        work_end = dist + work_dist_m
        while dist < work_end:
            dd = _pace_to_dist_delta(work_pace, dt_sec)
            dist += dd
            trackpoints.append(_make_tp(t, dist, work_hr, alt=150, lat=lat, lon=lon, cad=185))
            t += timedelta(seconds=dt_sec)
            lat += 0.00001

        rec_end = dist + recovery_dist_m
        while dist < rec_end:
            dd = _pace_to_dist_delta(base_pace, dt_sec)
            dist += dd
            trackpoints.append(_make_tp(t, dist, recovery_hr, alt=150, lat=lat, lon=lon, cad=165))
            t += timedelta(seconds=dt_sec)
            lat += 0.00001

    cooldown_end = dist + cooldown_km * 1000
    while dist < cooldown_end:
        dd = _pace_to_dist_delta(base_pace + 0.5, dt_sec)
        dist += dd
        trackpoints.append(_make_tp(t, dist, base_hr - 5, alt=150, lat=lat, lon=lon, cad=160))
        t += timedelta(seconds=dt_sec)
        lat += 0.00001

    return trackpoints


def _build_tempo(start_time, pace, distance_km, hr):
    trackpoints = []
    t = start_time
    dist = 0.0
    target_dist = distance_km * 1000
    dt_sec = 5.0
    lat, lon = 55.75, 37.62

    while dist < target_dist:
        dd = _pace_to_dist_delta(pace, dt_sec)
        dist += dd
        hr_val = hr + int((dist / target_dist) * 5)
        trackpoints.append(_make_tp(t, dist, hr_val, alt=150, lat=lat, lon=lon, cad=175))
        t += timedelta(seconds=dt_sec)
        lat += 0.00001

    return trackpoints


def _build_long(start_time, pace, duration_min, hr):
    trackpoints = []
    t = start_time
    dist = 0.0
    dt_sec = 10.0
    total_sec = duration_min * 60
    lat, lon = 55.75, 37.62
    elapsed = 0.0

    while elapsed < total_sec:
        dd = _pace_to_dist_delta(pace, dt_sec)
        dist += dd
        trackpoints.append(_make_tp(t, dist, hr, alt=150, lat=lat, lon=lon, cad=168))
        t += timedelta(seconds=dt_sec)
        elapsed += dt_sec
        lat += 0.00001

    return trackpoints


def _build_recovery(start_time, pace, duration_min, hr, max_hr):
    trackpoints = []
    t = start_time
    dist = 0.0
    dt_sec = 10.0
    total_sec = duration_min * 60
    lat, lon = 55.75, 37.62
    elapsed = 0.0

    while elapsed < total_sec:
        dd = _pace_to_dist_delta(pace, dt_sec)
        dist += dd
        trackpoints.append(_make_tp(t, dist, hr, alt=150, lat=lat, lon=lon, cad=155))
        t += timedelta(seconds=dt_sec)
        elapsed += dt_sec
        lat += 0.00001

    return trackpoints


def _build_gps_errors(start_time, base_pace, distance_km, error_indices):
    if error_indices is None:
        error_indices = [50, 100]
    trackpoints = []
    t = start_time
    dist = 0.0
    dt_sec = 5.0
    target_dist = distance_km * 1000
    lat, lon = 55.75, 37.62
    idx = 0

    while dist < target_dist:
        dd = _pace_to_dist_delta(base_pace, dt_sec)
        dist += dd
        if idx in error_indices:
            lat += 0.01
            lon += 0.01
        else:
            lat += 0.00001
        trackpoints.append(_make_tp(t, dist, 140, alt=150, lat=lat, lon=lon, cad=170))
        t += timedelta(seconds=dt_sec)
        idx += 1

    return trackpoints


# Обратная совместимость (Backward compatibility aliases)
def build_interval_trackpoints(**kwargs):
    return build_trackpoints(training_type='interval', **kwargs)


def build_tempo_trackpoints(**kwargs):
    return build_trackpoints(training_type='tempo', **kwargs)


def build_long_trackpoints(**kwargs):
    return build_trackpoints(training_type='long', **kwargs)


def build_recovery_trackpoints(**kwargs):
    return build_trackpoints(training_type='recovery', **kwargs)


def build_trackpoints_with_gps_errors(**kwargs):
    return build_trackpoints(training_type='gps_errors', **kwargs)
