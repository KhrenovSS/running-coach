# Функции трендов: slope, EWMA, moving average, направление
# Trend functions: slope, EWMA, moving average, trend direction

from collections.abc import Sequence


def compute_slope(series: Sequence[float | None], days: int = 30) -> float | None:
    """Линейная регрессия: наклон ряда за N дней (Linear regression slope over N days)."""
    cleaned = [v for v in series if v is not None]
    if len(cleaned) < 2:
        return None
    cleaned = cleaned[-days:] if len(cleaned) > days else cleaned
    n = len(cleaned)
    x_avg = (n - 1) / 2
    y_avg = sum(cleaned) / n
    num = sum((i - x_avg) * (v - y_avg) for i, v in enumerate(cleaned))
    den = sum((i - x_avg) ** 2 for i in range(n))
    return num / den if den != 0 else 0.0


def compute_ewma(series: Sequence[float | None], alpha: float = 0.3) -> list[float]:
    """Экспоненциально взвешенное скользящее среднее (EWMA)."""
    cleaned = [v if v is not None else 0.0 for v in series]
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
                             down_threshold: float = -0.01) -> str:
    """Направление тренда: 'up', 'stable', 'down' (Trend direction)."""
    slope = compute_slope(series, days=len([v for v in series if v is not None]))
    if slope is None:
        return 'stable'
    if slope > up_threshold:
        return 'up'
    if slope < down_threshold:
        return 'down'
    return 'stable'
