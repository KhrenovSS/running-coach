# Тесты базовой линии HR↔темп (HR↔pace baseline tests) — DEV_PLAN §9 D2

from src.analysis.hr_baseline import (
    baseline_deviation,
    deviation_flag,
    fit_hr_pace_baseline,
    km_points,
)
from src.config.constants import BASELINE_MIN_POINTS, BASELINE_MIN_SESSIONS


def _points_by_law(n: int, a: float = 190.0, b: float = -8.0):
    """Точки по закону HR = a + b·pace с детерминированным «шумом»."""
    points = []
    for i in range(n):
        pace = 5.0 + (i % 20) * 0.1          # 5.0..6.9 мин/км
        noise = ((i * 7) % 5) - 2            # −2..+2 bpm
        points.append((pace, a + b * pace + noise))
    return points


def test_fit_recovers_slope():
    """OLS восстанавливает наклон закона (±15%)."""
    baseline = fit_hr_pace_baseline(_points_by_law(60), n_sessions=8)
    assert baseline is not None
    assert abs(baseline["b"] - (-8.0)) / 8.0 < 0.15
    assert baseline["rmse_bpm"] < 3.0
    assert baseline["n_points"] == 60


def test_too_few_points_or_sessions_no_baseline():
    """Мало точек или сессий → None (никакой ложной точности)."""
    assert fit_hr_pace_baseline(_points_by_law(BASELINE_MIN_POINTS - 1),
                                n_sessions=10) is None
    assert fit_hr_pace_baseline(_points_by_law(60),
                                n_sessions=BASELINE_MIN_SESSIONS - 1) is None


def test_degenerate_positive_slope_rejected():
    """Положительный наклон (быстрее → ниже пульс?!) → вырожденный фит → None."""
    points = [(5.0 + i * 0.05, 120 + i) for i in range(40)]  # HR растёт с pace
    assert fit_hr_pace_baseline(points, n_sessions=10) is None


def test_deviation_measures_delta():
    """Сегодняшний HR +10 к закону → delta_bpm ≈ 10, z положительный."""
    baseline = fit_hr_pace_baseline(_points_by_law(60), n_sessions=8)
    per_km = [{"km": i + 1, "gap_min_km": 6.0, "avg_hr": 190 - 8 * 6.0 + 10}
              for i in range(6)]
    dev = baseline_deviation(baseline, per_km)
    assert dev["available"] is True
    assert abs(dev["delta_bpm"] - 10.0) < 1.5
    assert dev["z"] > 0
    assert deviation_flag(dev) == "hr_above_baseline"


def test_no_baseline_deviation_absent():
    """Нет baseline → available=False с причиной."""
    dev = baseline_deviation(None, [{"km": 2, "gap_min_km": 6.0, "avg_hr": 150}])
    assert dev == {"available": False, "reason": "no_baseline"}


def test_km_points_skip_first_km():
    """Первый км исключается (разогрев + колено), None-строки отбрасываются."""
    per_km = [
        {"km": 1, "gap_min_km": 7.0, "avg_hr": 130},   # разогрев — исключён
        {"km": 2, "gap_min_km": 6.0, "avg_hr": 145},
        {"km": 3, "gap_min_km": None, "pace_min_km": 6.1, "avg_hr": 147},
        {"km": 4, "gap_min_km": 6.2, "avg_hr": None},  # нет HR — отброшен
    ]
    points = km_points(per_km)
    assert (6.0, 145.0) in points
    assert (6.1, 147.0) in points  # fallback на pace_min_km
    assert len(points) == 2
