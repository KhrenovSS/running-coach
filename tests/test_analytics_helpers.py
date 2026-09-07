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


def test_slope_with_dates_uses_calendar_days():
    """#221: с датами наклон — в единицах за день; разрыв в календаре не сжимается."""
    from datetime import date, datetime, timedelta
    d0 = date(2026, 9, 1)
    contiguous = [d0 + timedelta(days=i) for i in range(3)]
    assert abs(compute_slope([1, 2, 3], dates=contiguous) - compute_slope([1, 2, 3])) < 1e-9
    gapped = [d0, d0 + timedelta(days=1), d0 + timedelta(days=10)]
    dated = compute_slope([1, 2, 3], dates=gapped)
    assert 0 < dated < compute_slope([1, 2, 3])                 # 10 дней на тот же прирост → положе
    assert abs(dated - 10 / 60.666666) < 1e-3                   # OLS по x = [0, 1, 10]
    # None и datetime допустимы; окно days — по календарю от последней точки
    assert compute_slope([1, None, 3], dates=[d0, d0 + timedelta(days=1), d0 + timedelta(days=2)]) == 1.0
    dt = [datetime(2026, 9, 1, 7), datetime(2026, 9, 2, 19), datetime(2026, 9, 3, 6)]
    assert abs(compute_slope([1, 2, 3], dates=dt) - 1.0) < 1e-9
    assert compute_slope([1, 2, 3], days=2, dates=[d0, d0 + timedelta(days=5), d0 + timedelta(days=6)]) == 1.0
    assert compute_slope([1, 2], dates=[d0, None]) is None
    assert compute_trend_direction([50, 50.05, 50.1], dates=[d0, d0 + timedelta(days=30), d0 + timedelta(days=60)]) == 'stable'
    assert compute_trend_direction([50, 51, 52], dates=[d0, d0 + timedelta(days=1), d0 + timedelta(days=2)]) == 'up'
