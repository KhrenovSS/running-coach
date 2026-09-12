# Полевой тест ПАНО по треку (Field LTHR test from trackpoints, M3.2 — 12.09.2026)
#
# Протокол (Friel): после разминки 30 минут ровного максимального усилия; ПАНО ≈ средний пульс
# последних 20 минут отрезка. Здесь — чистая математика без БД и без импорта coach: рабочий отрезок
# ищем как 30-минутное окно с максимальным средним пульсом по ВРЕМЕНИ (учёт пауз записи и дропаутов,
# как в session_metrics.time_in_zones), затем считаем средний пульс последних window_min минут окна,
# дрейф (10-я → 30-я минута) и темп окна. Пороги приходят параметрами (coach/config → workout_insights).
# Всё деградирует в available=false с причиной. (Pure, tolerant; thresholds are parameters.)

from __future__ import annotations

from bisect import bisect_left

from src.analysis.utils import pause_overlap_sec
from src.config.constants import LTHR_SANITY_MIN, RECORDING_GAP_MAX_SEC


def _samples(times_sec: list[float], hrs: list[int | None],
             pauses_sec: list[tuple[float, float]] | None) -> list[tuple[float, float, int | None]]:
    """(start_sec, dt_sec, hr предыдущей точки) — интервалы записи без пауз и разрывов."""
    out = []
    for i in range(1, len(times_sec)):
        dt = times_sec[i] - times_sec[i - 1]
        if pauses_sec:
            dt -= pause_overlap_sec(times_sec[i - 1], times_sec[i], pauses_sec)
        if dt <= 0 or dt > RECORDING_GAP_MAX_SEC:
            continue
        out.append((times_sec[i - 1], dt, hrs[i - 1]))
    return out


def _mean_hr(samples: list[tuple[float, float, int | None]], t_from: float, t_to: float,
             ) -> tuple[float | None, float]:
    """Средний пульс по времени на [t_from, t_to] и покрытие пульсом (0..1)."""
    hr_t = t_hr = t_all = 0.0
    for s, dt, hr in samples:
        if s < t_from or s >= t_to:
            continue
        t_all += dt
        if hr is not None:
            t_hr += dt
            hr_t += hr * dt
    if t_hr <= 0:
        return None, 0.0
    return hr_t / t_hr, (t_hr / t_all if t_all else 0.0)


def lthr_from_test(times_sec: list[float], hrs: list[int | None], dists: list[float] | None = None,
                   pauses_sec: list[tuple[float, float]] | None = None, *,
                   max_hr: int | None = None, work_min: float = 30.0, window_min: float = 20.0,
                   drift_max_bpm: float = 8.0, coverage_min: float = 0.9) -> dict:
    """ПАНО из теста: окно work_min с максимальным средним пульсом → среднее последних window_min.

    Возврат: {"available": bool, "lthr": int, "window_start_min", "window_avg_hr", "drift_bpm",
    "quality": "ok"|"rough", "pace_s_km", "coverage", "reason"}. (LTHR from the steady block.)
    """
    if len(times_sec) < 2 or not any(h is not None for h in hrs):
        return {"available": False, "reason": "no_hr"}
    work_sec = work_min * 60.0
    if times_sec[-1] - times_sec[0] < work_sec:
        return {"available": False, "reason": "too_short"}
    samples = _samples(times_sec, hrs, pauses_sec)
    if not samples:
        return {"available": False, "reason": "no_samples"}
    starts = [s for s, _, _ in samples]
    # Префиксные суммы по интервалам записи (prefix sums over recording intervals)
    cum_t, cum_hr_t, cum_hrt = [0.0], [0.0], [0.0]
    for _, dt, hr in samples:
        cum_t.append(cum_t[-1] + dt)
        cum_hr_t.append(cum_hr_t[-1] + (dt if hr is not None else 0.0))
        cum_hrt.append(cum_hrt[-1] + (hr * dt if hr is not None else 0.0))
    best = None  # (mean, i, j, t_start, t_end)
    for i, s in enumerate(starts):
        e = s + work_sec
        if e > times_sec[-1] + 1e-6:
            break
        j = bisect_left(starts, e)
        t_hr = cum_hr_t[j] - cum_hr_t[i]
        t_all = cum_t[j] - cum_t[i]
        if t_all <= 0 or t_hr / t_all + 1e-9 < coverage_min or t_all < work_sec * coverage_min:
            continue
        mean = (cum_hrt[j] - cum_hrt[i]) / t_hr
        if best is None or mean > best[0]:
            best = (mean, i, j, s, e)
    if best is None:
        return {"available": False, "reason": "low_hr_coverage"}
    mean_all, _, _, t_start, t_end = best
    lthr_mean, cov = _mean_hr(samples, t_end - window_min * 60.0, t_end)
    if lthr_mean is None or cov + 1e-9 < coverage_min:
        return {"available": False, "reason": "low_hr_coverage"}
    lthr = int(round(lthr_mean))
    if lthr <= LTHR_SANITY_MIN or (max_hr and lthr >= max_hr):
        return {"available": False, "reason": "insane_value", "lthr": lthr}
    early, _ = _mean_hr(samples, t_start + 8 * 60.0, t_start + 12 * 60.0)
    late, _ = _mean_hr(samples, t_end - 4 * 60.0, t_end)
    drift = round(late - early, 1) if early is not None and late is not None else None
    pace_s_km = None
    if dists and len(dists) == len(times_sec):
        i0 = bisect_left(times_sec, t_start)
        i1 = min(bisect_left(times_sec, t_end), len(dists) - 1)
        dkm = (dists[i1] - dists[i0]) / 1000.0
        if dkm > 0.5:
            pace_s_km = round(work_sec / dkm)
    return {
        "available": True, "lthr": lthr,
        "window_start_min": round(t_start / 60.0, 1),
        "window_avg_hr": round(mean_all, 1),
        "drift_bpm": drift,
        "quality": "rough" if drift is not None and drift > drift_max_bpm else "ok",
        "pace_s_km": pace_s_km, "coverage": round(cov, 2),
    }
