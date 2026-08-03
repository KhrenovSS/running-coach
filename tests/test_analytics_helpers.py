# Тесты трендовых helpers (Trend helpers tests) — Трек 2
from src.services.analytics_helpers import (
    compute_slope, compute_ewma, compute_moving_average, compute_trend_direction,
)


def test_slope_positive_and_negative():
    assert compute_slope([1, 2, 3, 4, 5]) > 0
    assert compute_slope([5, 4, 3, 2, 1]) < 0
    assert abs(compute_slope([3, 3, 3, 3])) < 1e-9


def test_slope_edge_cases():
    assert compute_slope([]) is None
    assert compute_slope([42]) is None          # <2 точек
    assert compute_slope([None, None]) is None   # все None отброшены


def test_slope_skips_none():
    # None не влияет на наклон (отбрасывается, как и в EWMA/MA)
    assert compute_slope([1, None, 2, None, 3]) == compute_slope([1, 2, 3])


def test_ewma_skips_none_not_zero():
    """Регресс: None ПРОПУСКАЕТСЯ, а не заменяется на 0.0 (иначе обвал тренда на пропуске)."""
    with_gap = compute_ewma([70, 68, None, 71])
    without_gap = compute_ewma([70, 68, 71])
    assert with_gap == without_gap
    # если бы None → 0.0, третий элемент рухнул бы к нулю
    assert min(with_gap) > 60


def test_ewma_empty_and_all_none():
    assert compute_ewma([]) == []
    assert compute_ewma([None, None]) == []


def test_moving_average_basic_and_none():
    ma = compute_moving_average([1, 2, 3, 4, 5], window=3)
    assert ma[:2] == [None, None]
    assert ma[2] == 2.0 and ma[-1] == 4.0
    # None отбрасываются перед окном
    assert compute_moving_average([1, None, 2, 3], window=3) == compute_moving_average([1, 2, 3], window=3)


def test_moving_average_short_series():
    assert compute_moving_average([1, 2], window=5) == [None, None]


def test_trend_direction():
    assert compute_trend_direction([1, 2, 3, 4, 5]) == 'up'
    assert compute_trend_direction([5, 4, 3, 2, 1]) == 'down'
    assert compute_trend_direction([3, 3, 3]) == 'stable'
    assert compute_trend_direction([]) == 'stable'
