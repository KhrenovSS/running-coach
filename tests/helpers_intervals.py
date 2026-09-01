# Синтетика для тестов HRR/F3 (M2.1 разбора): кусочно-линейные ряды HR,
# лапы часов и трекпоинты — общие фабрики test_intervals/test_workout_insights.
# (Piecewise-linear HR series, watch laps and trackpoints for the HRR/F3 tests.)

from datetime import datetime, timedelta, timezone

T0 = datetime(2026, 9, 1, 8, 0, 0, tzinfo=timezone.utc)
MAX_HR = 180  # границы зон при 180: Z2 ≤144, Z3 ≤156.6, Z4 ≤167.4 (zone edges)


def build_hr_series(segments: list[tuple], dt: float = 5.0):
    """segments: (dur_s, hr_start, hr_end) → (times_sec, hrs), линейная интерполяция.
    (Linear piecewise HR interpolation sampled every dt seconds.)"""
    times, hrs = [0.0], [round(segments[0][1])]
    t, seg_start = 0.0, 0.0
    for dur, h0, h1 in segments:
        seg_end = seg_start + dur
        while t + dt <= seg_end + 1e-9:
            t += dt
            hrs.append(round(h0 + (h1 - h0) * (t - seg_start) / dur))
            times.append(t)
        seg_start = seg_end
    return times, hrs


def build_laps(meta: list[tuple]) -> list[dict]:
    """meta: (dur_s, dist_m) подряд от T0 → лапы в формате laps_json (fit_parser)."""
    laps, t = [], 0.0
    for dur, dist in meta:
        laps.append({'start_time': (T0 + timedelta(seconds=t)).isoformat(),
                     'distance_m': dist, 'timer_s': round(dur)})
        t += dur
    return laps


def interval_workout(reps: int = 4, work_peak: int = 162, drop60: int = 25,
                     rest_end: int = 130, rest_s: int = 120,
                     work_s: int = 180) -> tuple[list, list]:
    """Разминка 120с + reps×(работа ramp 130→work_peak / отдых: −drop60 за 60с,
    затем к rest_end). → (segments, laps_meta) для build_hr_series/build_laps.
    (Warmup + reps of work-ramp / two-stage recovery decay.)"""
    segs = [(120, 120, 120)]
    meta = [(120, 400)]
    for _ in range(reps):
        segs.append((work_s, 130, work_peak))
        meta.append((work_s, 800))
        segs.append((60, work_peak, work_peak - drop60))
        if rest_s > 60:
            segs.append((rest_s - 60, work_peak - drop60, rest_end))
        meta.append((rest_s, 200))
    return segs, meta


def build_hrr_trackpoints(segments: list[tuple], dt: float = 5.0,
                          speed_ms: float = 3.0) -> list[dict]:
    """Трекпоинты (time ISO / dist / hr) по HR-сегментам — вход trackpoints_json.
    Ровная скорость: дистанция нужна парсеру, темп в HRR-тестах не участвует."""
    times, hrs = build_hr_series(segments, dt)
    return [{'time': (T0 + timedelta(seconds=t)).isoformat(),
             'dist': round(speed_ms * t, 1), 'hr': hr, 'alt': 150.0}
            for t, hr in zip(times, hrs)]
