# Тесты GAP/рельефа (GAP & terrain tests) — DEV_PLAN §9 D2

from src.analysis.gap import compute_gap, gap_factor, smooth_altitudes
from src.config.constants import HILLY_GAIN_M_PER_KM
from tests.helpers import build_trackpoints


def _series(tps):
    t0 = tps[0]['time']
    times = [(tp['time'] - t0).total_seconds() for tp in tps]
    return (times, [tp['dist'] for tp in tps],
            [tp.get('hr') for tp in tps], [tp.get('alt') for tp in tps])


def test_uphill_gap_faster_than_pace():
    """Подъём 5%: GAP заметно быстрее фактического темпа."""
    tps = build_trackpoints('tempo', distance_km=5.0, base_pace=6.0, grade_pct=5.0)
    gap = compute_gap(*_series(tps))
    assert gap["available"] is True
    row = gap["per_km"][1]
    assert row["grade_pct"] > 3.0
    assert row["gap_min_km"] < row["pace_min_km"]


def test_downhill_gap_slower_than_pace():
    """Спуск: GAP медленнее фактического темпа (бежать под горку легче)."""
    tps = build_trackpoints('tempo', distance_km=5.0, base_pace=6.0, grade_pct=-5.0)
    gap = compute_gap(*_series(tps))
    row = gap["per_km"][1]
    assert row["gap_min_km"] > row["pace_min_km"]


def test_flat_gap_equals_pace():
    """Плоско: GAP ≈ темп (фабрика даёт константную высоту 150)."""
    tps = build_trackpoints('tempo', distance_km=5.0, base_pace=6.0)
    gap = compute_gap(*_series(tps))
    for row in gap["per_km"]:
        assert abs(row["gap_min_km"] - row["pace_min_km"]) <= 0.02
    assert gap["hilly"] is False


def test_altitude_spike_is_smoothed():
    """Одиночный выброс высоты ±30 м не создаёт фантомного набора."""
    tps = build_trackpoints('tempo', distance_km=5.0, base_pace=6.0)
    tps[len(tps) // 2]['alt'] = 180.0  # выброс барометра
    gap = compute_gap(*_series(tps))
    assert gap["elevation_gain_smoothed_m"] < 5


def test_no_altitude_gap_unavailable():
    """Без высоты GAP недоступен, per_km нет."""
    tps = build_trackpoints('tempo', distance_km=5.0)
    for tp in tps:
        tp['alt'] = None
    gap = compute_gap(*_series(tps))
    assert gap == {"available": False}
    assert smooth_altitudes([None] * 100) is None


def test_hilly_flag():
    """Стабильный подъём: набор на км выше порога → hilly=True."""
    tps = build_trackpoints('tempo', distance_km=5.0, grade_pct=2.0)  # 20 м/км
    gap = compute_gap(*_series(tps))
    assert gap["gain_per_km_m"] >= HILLY_GAIN_M_PER_KM
    assert gap["hilly"] is True


def test_gap_factor_monotonic():
    """Фактор растёт с уклоном: подъём > плоскость > лёгкий спуск."""
    assert gap_factor(0.05) > gap_factor(0.0) > gap_factor(-0.05)
    assert abs(gap_factor(0.0) - 1.0) < 1e-9
