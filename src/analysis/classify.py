# Классификация тренировок: interval / tempo / long / recovery / easy
# Training classification: interval / tempo / long / recovery / easy

from src.analysis.hr_zones import get_zone
from src.config.constants import (
    RECOVERY_MAX_HR_PCT,
    EASY_MAX_HR_PCT,
    EASY_MIN_Z2_PCT,
    RECOVERY_MAX_Z4_PCT,
    LONG_MAX_Z4_PCT,
    EASY_MAX_Z4_SEGMENT_MIN,
)


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
    avg_pace: float | None = None,
) -> tuple[str, int]:
    """
    Мульти-сигнальная классификация тренировки.
    Multi-signal training classification.

    Приоритет проверок (highest first):
    1. interval — серия work→recovery циклов + подтверждение пульсом/интенсивностью
    2. long — длительная тренировка, преимущественно Z2
    3. recovery — очень лёгкая, низкий пульс, медленный темп
    4. easy (Легкая пробежка) — лёгкая стабильная, Z2 доминирование
    5. tempo — всё остальное (умеренная/высокая интенсивность)

    Args:
        var_count: число вариативных км (из _compute_km_variability)
        time_in_zone: время в зонах {1: мин, 2: мин, ...}
        total_duration_min: общая длительность (мин)
        max_hr: максимальный пульс
        z4_plus_segments: сегменты в Z4+ (для определения long/recovery)
        avg_hr: средний пульс
        oscillation_count: число осцилляций темпа
        hr_correlated: корреляция темп-пульс подтверждена
        min_oscillations: мин. число осцилляций для interval
        segments_len: число финальных сегментов после слияния
        avg_pace: средний темп (мин/км)

    Returns:
        (training_type, segments_count) — тип тренировки и число сегментов
    """
    total_z4_time = time_in_zone.get(4, 0.0) + time_in_zone.get(5, 0.0)
    z4_time_pct = (total_z4_time / total_duration_min * 100) if total_duration_min > 0 else 0
    z2_pct = (time_in_zone.get(2, 0.0) / total_duration_min * 100) if total_duration_min > 0 else 0

    has_long_z4 = any(s.get('duration', 0) > EASY_MAX_Z4_SEGMENT_MIN for s in z4_plus_segments)
    avg_hr_pct = avg_hr / max_hr if max_hr > 0 else 0

    # Защита: если < 3 сегментов — реальных интервалов нет
    # (Guard: fewer than 3 segments — not real intervals)
    if 0 < segments_len < 3:
        oscillation_count = 0
        var_count = 0

    # 1. Interval — серия work→recovery + подтверждение
    # (Interval — series of work→recovery + confirmation)
    is_interval = (
        oscillation_count >= 2
        and (hr_correlated or avg_hr_pct >= 0.87)
        and segments_len >= 3
    )

    # 2. Long — длительная тренировка, Z2 доминирование, допускаются короткие Z4+
    # (Long — long duration, Z2 dominant, brief Z4+ allowed)
    is_long = (
        total_duration_min >= 90
        and z2_pct >= 50
        and z4_time_pct < LONG_MAX_Z4_PCT
    )

    # 3. Recovery — очень лёгкая, низкий пульс, медленный темп
    # (Recovery — very easy, low HR, slow pace)
    is_recovery = (
        avg_hr_pct <= RECOVERY_MAX_HR_PCT
        and z4_time_pct < RECOVERY_MAX_Z4_PCT
        and (avg_pace is None or avg_pace > 6.0)
    )

    # 4. Easy (Легкая пробежка) — лёгкая стабильная, Z2 доминирование
    # (Easy — light stable run, Z2 dominant)
    is_easy = (
        avg_hr_pct <= EASY_MAX_HR_PCT
        and z2_pct >= EASY_MIN_Z2_PCT
        and not has_long_z4
    )

    # Классификация по приоритету (Classification by priority)
    if is_interval:
        segments_count = max(var_count, oscillation_count) if oscillation_count > 0 else var_count
        return 'interval', segments_count
    elif is_long:
        return 'long', 1
    elif is_recovery:
        return 'recovery', 1
    elif is_easy:
        return 'easy', 1
    else:
        return 'tempo', 1
