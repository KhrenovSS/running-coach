# Классификация тренировок: interval / tempo / long / recovery
# Training classification: interval / tempo / long / recovery

from src.analysis.hr_zones import get_zone


def classify_training(
    var_count: int,
    time_in_zone: dict,
    total_duration_min: float,
    max_hr: int,
    z4_plus_segments: list[dict],
    avg_hr: int,
    oscillation_count: int = 0,
    hr_correlated: bool = False,
    min_oscillations: int = 3,
    segments_len: int = 0,
) -> tuple[str, int]:
    """
    Мульти-сигнальная классификация тренировки.
    Multi-signal training classification.

    Сигналы:
    1. var_count >= 3 → interval (км-блоки с вариативностью)
    2. oscillation_count >= min_oscillations → interval (осцилляции темпа)
    3. oscillation_count >= 2 AND hr_correlated → interval (подтверждено пульсом)

    Args:
        var_count: число вариативных км (из _compute_km_variability)
        time_in_zone: время в зонах {1: мин, 2: мин, ...}
        total_duration_min: общая длительность (мин)
        max_hr: максимальный пульс
        z4_plus_segments: сегменты в Z4+ (для определения long/recovery)
        avg_hr: средний пульс
        oscillation_count: число осцилляций темпа (НОВОЕ)
        hr_correlated: корреляция темп-пульс подтверждена (НОВОЕ)
        min_oscillations: мин. число осцилляций для interval (НОВОЕ, default=3)
        segments_len: число финальных сегментов после слияния (для валидации)

    Returns:
        (training_type, segments_count) — тип тренировки и число сегментов
    """
    z2_pct = (time_in_zone[2] / total_duration_min * 100) if total_duration_min > 0 else 0
    hr_75 = 0.75 * max_hr
    long_z4 = [s for s in z4_plus_segments if s['duration'] > 5]

    # Если после слияния осталось < 3 сегментов — реальных интервалов нет
    # (If after merging fewer than 3 segments remain — not real intervals)
    if 0 < segments_len < 3:
        oscillation_count = 0
        var_count = 0

    # Мульти-сигнальная детекция интервалов (Multi-signal interval detection)
    is_interval = (
        var_count >= 3
        or oscillation_count >= min_oscillations
        or (oscillation_count >= 2 and hr_correlated)
    )

    if is_interval:
        t_type = 'interval'
        # Сегменты: max(var_count, oscillation_count) как оценка
        segments_count = max(var_count, oscillation_count) if oscillation_count > 0 else var_count
    elif var_count >= 1:
        t_type = 'tempo'
        segments_count = 1
    elif total_duration_min >= 90 and z2_pct >= 50 and not long_z4:
        t_type = 'long'
        segments_count = 1
    elif avg_hr <= hr_75 and not long_z4:
        t_type = 'recovery'
        segments_count = 1
    else:
        t_type = 'tempo'
        segments_count = 1

    return t_type, segments_count
