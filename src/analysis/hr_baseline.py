# Персональная базовая линия HR↔GAP-темп (Personal HR↔pace baseline) — DEV_PLAN §9 D2
#
# Чистая математика без БД: OLS-регрессия HR = a + b·gap_pace_min_km по км-точкам
# steady-тренировок. Отвечает на «пульс 149 на 6:10 — это нормально для меня?».
# Малая выборка → None, никакой ложной точности (graceful degradation).
# (Pure math; OLS over km-points of steady runs; small sample → no baseline.)

from __future__ import annotations

from src.config.constants import (
    BASELINE_MIN_POINTS,
    BASELINE_MIN_SESSIONS,
    BASELINE_SKIP_FIRST_KM,
    BASELINE_Z_FLAG,
)

BASELINE_VERSION = 1


def km_points(per_km: list[dict]) -> list[tuple[float, float]]:
    """Км-точки (gap_pace, hr) одной тренировки; первый км исключён (разогрев/колено)."""
    points = []
    for row in per_km[BASELINE_SKIP_FIRST_KM:]:
        pace = row.get("gap_min_km") or row.get("pace_min_km")
        hr = row.get("avg_hr")
        if pace is not None and hr is not None:
            points.append((float(pace), float(hr)))
    return points


def fit_hr_pace_baseline(points: list[tuple[float, float]],
                         n_sessions: int) -> dict | None:
    """OLS: HR = a + b·pace. None при малой выборке или вырожденном фите.

    Санити-гейт: b < 0 обязателен (медленнее темп в мин/км → ниже пульс);
    b >= 0 = вырожденный фит, baseline отсутствует.
    """
    n = len(points)
    if n < BASELINE_MIN_POINTS or n_sessions < BASELINE_MIN_SESSIONS:
        return None
    mean_x = sum(p for p, _ in points) / n
    mean_y = sum(h for _, h in points) / n
    sxx = sum((p - mean_x) ** 2 for p, _ in points)
    if sxx <= 0:
        return None
    b = sum((p - mean_x) * (h - mean_y) for p, h in points) / sxx
    if b >= 0:
        return None  # degenerate_fit: быстрее должен быть выше пульс
    a = mean_y - b * mean_x
    rmse = (sum((h - (a + b * p)) ** 2 for p, h in points) / n) ** 0.5
    return {"a": round(a, 2), "b": round(b, 3), "rmse_bpm": round(rmse, 1),
            "n_points": n, "n_sessions": n_sessions, "version": BASELINE_VERSION}


def baseline_deviation(baseline: dict | None, per_km: list[dict]) -> dict:
    """Отклонение сегодняшней тренировки от базовой линии (today vs baseline)."""
    if not baseline:
        return {"available": False, "reason": "no_baseline"}
    points = km_points(per_km)
    if not points:
        return {"available": False, "reason": "no_km_points"}
    expected = sum(baseline["a"] + baseline["b"] * p for p, _ in points) / len(points)
    actual = sum(h for _, h in points) / len(points)
    delta = actual - expected
    rmse = baseline.get("rmse_bpm") or 0.0
    z = round(delta / rmse, 1) if rmse > 0 else None
    return {
        "available": True, "reason": None,
        "expected_hr": round(expected, 1), "actual_hr": round(actual, 1),
        "delta_bpm": round(delta, 1), "z": z,
        "baseline_rmse_bpm": rmse,
        "baseline_n_sessions": baseline.get("n_sessions"),
        "baseline_computed_at": baseline.get("computed_at"),
    }


def deviation_flag(deviation: dict) -> str | None:
    """hr_above/below_baseline при |z| ≥ BASELINE_Z_FLAG (flag for LLM)."""
    z = deviation.get("z")
    if z is None:
        return None
    if z >= BASELINE_Z_FLAG:
        return "hr_above_baseline"
    if z <= -BASELINE_Z_FLAG:
        return "hr_below_baseline"
    return None
