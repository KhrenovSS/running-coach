# Функции трендов: slope, EWMA, moving average, направление
# Trend functions: slope, EWMA, moving average, trend direction

from datetime import datetime
from collections.abc import Sequence


def _ols_slope(xs: Sequence[float], ys: Sequence[float]) -> float:
    n = len(xs)
    x_avg = sum(xs) / n
    y_avg = sum(ys) / n
    num = sum((x - x_avg) * (y - y_avg) for x, y in zip(xs, ys))
    den = sum((x - x_avg) ** 2 for x in xs)
    return num / den if den != 0 else 0.0


def _day_index(d, d0) -> float:
    if isinstance(d, datetime):
        d = d.date()
    if isinstance(d0, datetime):
        d0 = d0.date()
    return float((d - d0).days)


def compute_slope(series: Sequence[float | None], days: int = 30,
                  dates: Sequence | None = None) -> float | None:
    """Линейная регрессия: наклон ряда (Linear regression slope).

    Без `dates` — по индексу точки (единица = одна точка), как раньше. С `dates` (даты/datetime,
    выровнены с series) — по календарным дням (#221, 07.09.2026): пропуск синка или редкие
    взвешивания больше не сжимают ось времени, наклон — «в единицах за день»; окно `days` —
    последние N дней от последней точки. (Calendar-day slope when dates are given.)
    """
    if dates is None:
        cleaned = [v for v in series if v is not None]
        if len(cleaned) < 2:
            return None
        cleaned = cleaned[-days:] if len(cleaned) > days else cleaned
        return _ols_slope(list(range(len(cleaned))), cleaned)
    pairs = [(d, v) for d, v in zip(dates, series) if v is not None and d is not None]
    if len(pairs) < 2:
        return None
    last = pairs[-1][0]
    pairs = [(d, v) for d, v in pairs if _day_index(last, d) < days]
    if len(pairs) < 2:
        return None
    d0 = pairs[0][0]
    return _ols_slope([_day_index(d, d0) for d, _ in pairs], [v for _, v in pairs])


def compute_ewma(series: Sequence[float | None], alpha: float = 0.3) -> list[float]:
    """Экспоненциально взвешенное скользящее среднее (EWMA).

    None-значения ПРОПУСКАЮТСЯ (как в compute_slope/compute_moving_average), а не заменяются
    на 0.0 — иначе разрыв в данных (пропущенный день синка) обваливал бы тренд к нулю.
    None values are SKIPPED (not substituted with 0.0) to avoid corrupting the trend on gaps.
    """
    cleaned = [v for v in series if v is not None]
    if not cleaned:
        return []
    result = [cleaned[0]]
    for v in cleaned[1:]:
        result.append(alpha * v + (1 - alpha) * result[-1])
    return result


def compute_moving_average(series: Sequence[float | None], window: int = 7) -> list[float | None]:
    """Простое скользящее среднее (Simple moving average)."""
    cleaned = [v for v in series if v is not None]
    if len(cleaned) < window:
        return [None] * len(cleaned)
    result: list[float | None] = [None] * (window - 1)
    for i in range(len(cleaned) - window + 1):
        result.append(sum(cleaned[i:i + window]) / window)
    return result


def compute_trend_direction(series: Sequence[float | None],
                             up_threshold: float = 0.01,
                             down_threshold: float = -0.01,
                             dates: Sequence | None = None) -> str:
    """Направление тренда: 'up', 'stable', 'down' (Trend direction). С `dates` — наклон за день."""
    n_present = len([v for v in series if v is not None])
    if dates is not None:
        present = [d for d, v in zip(dates, series) if v is not None and d is not None]
        span = (_day_index(present[-1], present[0]) + 1) if len(present) >= 2 else n_present
        slope = compute_slope(series, days=int(max(span, n_present)), dates=dates)
    else:
        slope = compute_slope(series, days=n_present)
    if slope is None:
        return 'stable'
    if slope > up_threshold:
        return 'up'
    if slope < down_threshold:
        return 'down'
    return 'stable'
