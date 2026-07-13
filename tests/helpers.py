# Фабрики синтетических трекпоинтов для тестов анализа
# Synthetic trackpoint factories for analysis tests

from datetime import datetime, timedelta, timezone


def _make_tp(time, dist, hr, alt=None, lat=55.75, lon=37.62, cad=None):
    """Создать один трекпоинт (Create a single trackpoint)"""
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
    """Конвертировать темп (мин/км) и время (сек) в дистанцию (м)"""
    if pace_min_km <= 0:
        return 0.0
    return (dt_sec / 60) / pace_min_km * 1000


def build_interval_trackpoints(
    base_pace: float = 5.0,
    work_pace: float = 4.0,
    warmup_km: float = 1.0,
    cooldown_km: float = 1.0,
    intervals: int = 5,
    work_dist_m: float = 400,
    recovery_dist_m: float = 400,
    base_hr: int = 130,
    work_hr: int = 165,
    recovery_hr: int = 140,
    start_time: datetime | None = None,
) -> list[dict]:
    """
    Интервальная тренировка: разминка + N work→recovery + заминка.
    Interval training: warmup + N work→recovery + cooldown.
    """
    if start_time is None:
        start_time = datetime(2026, 7, 1, 8, 0, 0, tzinfo=timezone.utc)

    trackpoints = []
    t = start_time
    dist = 0.0
    lat, lon = 55.75, 37.62

    dt_sec = 5.0

    # Разминка (warmup)
    warmup_m = warmup_km * 1000
    while dist < warmup_m:
        dd = _pace_to_dist_delta(base_pace, dt_sec)
        dist += dd
        trackpoints.append(_make_tp(t, dist, base_hr, alt=150, lat=lat, lon=lon, cad=170))
        t += timedelta(seconds=dt_sec)
        lat += 0.00001
        lon += 0.00001

    # Интервалы (intervals: work → recovery)
    for _ in range(intervals):
        # Work phase
        work_end = dist + work_dist_m
        while dist < work_end:
            dd = _pace_to_dist_delta(work_pace, dt_sec)
            dist += dd
            trackpoints.append(_make_tp(t, dist, work_hr, alt=150, lat=lat, lon=lon, cad=185))
            t += timedelta(seconds=dt_sec)
            lat += 0.00001

        # Recovery phase
        rec_end = dist + recovery_dist_m
        while dist < rec_end:
            dd = _pace_to_dist_delta(base_pace, dt_sec)
            dist += dd
            trackpoints.append(_make_tp(t, dist, recovery_hr, alt=150, lat=lat, lon=lon, cad=165))
            t += timedelta(seconds=dt_sec)
            lat += 0.00001

    # Заминка (cooldown)
    cooldown_end = dist + cooldown_km * 1000
    while dist < cooldown_end:
        dd = _pace_to_dist_delta(base_pace + 0.5, dt_sec)
        dist += dd
        trackpoints.append(_make_tp(t, dist, base_hr - 5, alt=150, lat=lat, lon=lon, cad=160))
        t += timedelta(seconds=dt_sec)
        lat += 0.00001

    return trackpoints


def build_tempo_trackpoints(
    pace: float = 4.5,
    distance_km: float = 10.0,
    hr: int = 155,
    start_time: datetime | None = None,
) -> list[dict]:
    """
    Темповая тренировка: стабильный темп на всю дистанцию.
    Tempo run: steady pace for entire distance.
    """
    if start_time is None:
        start_time = datetime(2026, 7, 1, 8, 0, 0, tzinfo=timezone.utc)

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


def build_long_trackpoints(
    pace: float = 5.5,
    duration_min: float = 100.0,
    hr: int = 135,
    start_time: datetime | None = None,
) -> list[dict]:
    """
    Длинная тренировка: стабильный темп, низкий пульс, >= 90 мин.
    Long run: steady pace, low HR, >= 90 min.
    """
    if start_time is None:
        start_time = datetime(2026, 7, 1, 6, 0, 0, tzinfo=timezone.utc)

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


def build_recovery_trackpoints(
    pace: float = 6.5,
    duration_min: float = 25.0,
    hr: int = 110,
    max_hr: int = 177,
    start_time: datetime | None = None,
) -> list[dict]:
    """
    Recovery тренировка: короткая, лёгкая, низкий пульс (< 75% max_hr).
    Recovery training: short, easy, low HR (< 75% max_hr).
    """
    if start_time is None:
        start_time = datetime(2026, 7, 1, 9, 0, 0, tzinfo=timezone.utc)

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


def build_trackpoints_with_gps_errors(
    base_pace: float = 5.0,
    distance_km: float = 3.0,
    error_indices: list[int] | None = None,
    start_time: datetime | None = None,
) -> list[dict]:
    """
    Тренировка с GPS-ошибками: аномальные скачки координат.
    Training with GPS errors: anomalous coordinate jumps.
    """
    if start_time is None:
        start_time = datetime(2026, 7, 1, 8, 0, 0, tzinfo=timezone.utc)
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
