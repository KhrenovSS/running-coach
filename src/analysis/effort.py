# Кардиодрейф / decoupling Pa:HR + heat (Cardiac drift & heat) — DEV_PLAN §9 D2
#
# Чистая математика без БД. Классический decoupling (Maffetone/TrainingPeaks):
# EF = grade-adjusted speed / HR по половинам moving-time;
# drift_pct = (EF1 − EF2) / EF1 · 100, >0 = эффективность упала во 2-й половине —
# маркер детренированности/жары/недовосстановления. Интерпретация причин — за LLM.
# (Pure math; positive drift = efficiency dropped in the second half.)

from __future__ import annotations

from dataclasses import dataclass

from src.config.constants import (
    DRIFT_HIGH_PCT,
    DRIFT_MAX_PACE_CV,
    DRIFT_MAX_SAMPLE_GAP_SEC,
    DRIFT_MIN_HR_COVERAGE,
    DRIFT_MIN_MOVING_SPEED_MS,
    DRIFT_MIN_STEADY_MIN,
    DRIFT_MODERATE_PCT,
    DRIFT_WARMUP_MIN,
    HEAT_TEMP_THRESHOLD_C,
)

_NOT_APPLICABLE = {"applicable": False, "drift_pct": None, "first_half_ef": None,
                   "second_half_ef": None, "gap_adjusted": None, "window_min": None,
                   "flag": None}


@dataclass
class MovingSample:
    """Сэмпл движения (one moving sample): dt сек, метры, HR, grade-фактор."""
    dt_sec: float
    dist_delta_m: float
    hr: int | None
    grade_factor: float = 1.0


def build_moving_samples(times_sec: list[float], dists: list[float],
                         hrs: list[int | None],
                         grade_factors: list[float] | None = None) -> list[MovingSample]:
    """Отфильтровать паузы/остановки (auto-pause + standing filter)."""
    samples: list[MovingSample] = []
    for i in range(1, len(times_sec)):
        dt = times_sec[i] - times_sec[i - 1]
        if dt <= 0 or dt > DRIFT_MAX_SAMPLE_GAP_SEC:
            continue  # автопауза/дыра в записи — интервал выброшен
        dd = dists[i] - dists[i - 1]
        if dd / dt < DRIFT_MIN_MOVING_SPEED_MS:
            continue  # стоим (дистанция не растёт)
        gf = grade_factors[i] if grade_factors else 1.0
        samples.append(MovingSample(dt_sec=dt, dist_delta_m=dd, hr=hrs[i], grade_factor=gf))
    return samples


def _ef(samples: list[MovingSample]) -> float | None:
    """EF половины: grade-adjusted speed / time-weighted HR."""
    t = sum(s.dt_sec for s in samples)
    hr_t = sum(s.dt_sec for s in samples if s.hr is not None)
    if t <= 0 or hr_t <= 0:
        return None
    speed = sum(s.dist_delta_m * s.grade_factor for s in samples) / t
    hr = sum(s.hr * s.dt_sec for s in samples if s.hr is not None) / hr_t
    return speed / hr if hr > 0 else None


def _pace_cv(per_km: list[dict] | None) -> float | None:
    """CV по-км темпов (GAP при наличии) без первого и последнего км."""
    if not per_km:
        return None
    key = "gap_min_km" if per_km[0].get("gap_min_km") is not None else "pace_min_km"
    vals = [r[key] for r in per_km[1:-1] if r.get(key) is not None]
    if len(vals) < 2:
        return None
    mean = sum(vals) / len(vals)
    if mean <= 0:
        return None
    var = sum((v - mean) ** 2 for v in vals) / len(vals)
    return (var ** 0.5) / mean


def compute_cardiac_drift(times_sec: list[float], dists: list[float],
                          hrs: list[int | None], *,
                          training_type: str | None,
                          grade_factors: list[float] | None = None,
                          per_km: list[dict] | None = None) -> dict:
    """Drift-блок computed_json; при неприменимости — applicable=False + reason."""
    def _na(reason: str) -> dict:
        return {**_NOT_APPLICABLE, "reason": reason}

    if training_type == "interval":
        return _na("interval")  # чередование нагрузок — дрейф неинформативен
    samples = build_moving_samples(times_sec, dists, hrs, grade_factors)
    if not samples:
        return _na("no_movement")
    if not any(s.hr is not None for s in samples):
        return _na("no_hr")

    # Отброс разогрева по moving-time (warmup discard by moving time)
    warmup_sec = DRIFT_WARMUP_MIN * 60
    acc = 0.0
    work: list[MovingSample] = []
    for s in samples:
        acc += s.dt_sec
        if acc > warmup_sec:
            work.append(s)
    window_min = sum(s.dt_sec for s in work) / 60.0
    if window_min < DRIFT_MIN_STEADY_MIN:
        return _na("too_short")
    hr_cov = sum(s.dt_sec for s in work if s.hr is not None) / (window_min * 60.0)
    if hr_cov < DRIFT_MIN_HR_COVERAGE:
        return _na("low_hr_coverage")
    cv = _pace_cv(per_km)
    if cv is not None and cv > DRIFT_MAX_PACE_CV:
        return _na("variable_pace")

    # Деление пополам по moving-time (halves by moving time)
    half_sec = window_min * 60.0 / 2.0
    acc = 0.0
    first: list[MovingSample] = []
    second: list[MovingSample] = []
    for s in work:
        (first if acc < half_sec else second).append(s)
        acc += s.dt_sec
    ef1, ef2 = _ef(first), _ef(second)
    if ef1 is None or ef2 is None or ef1 <= 0:
        return _na("low_hr_coverage")
    drift_pct = (ef1 - ef2) / ef1 * 100.0
    flag = ("high" if drift_pct > DRIFT_HIGH_PCT
            else "moderate" if drift_pct > DRIFT_MODERATE_PCT else "normal")
    return {
        "applicable": True, "reason": None,
        "drift_pct": round(drift_pct, 1),
        "first_half_ef": round(ef1, 5), "second_half_ef": round(ef2, 5),
        "gap_adjusted": grade_factors is not None,
        "window_min": round(window_min, 1), "flag": flag,
    }


def heat_block(temp_c: int | None) -> dict:
    """Heat-блок: флаг жары по температуре старта (интерпретация — LLM)."""
    if temp_c is None:
        return {"temp_c": None, "heat_flag": None}
    return {"temp_c": temp_c, "heat_flag": temp_c >= HEAT_TEMP_THRESHOLD_C}
