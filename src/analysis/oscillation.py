# Детекция осцилляций темпа и корреляция с пульсом
# Pace oscillation detection and HR lag correlation

# Пороги по умолчанию (default thresholds — перезаписываются из User)
from src.config.constants import MIN_EFFECTIVE_PACE_GAP

DEFAULT_PACE_THRESHOLD: float = 1.0         # мин/км — разница между базовым и work темпом
DEFAULT_MIN_PHASE_DURATION_SEC: int = 60    # сек — мин. длительность фазы
DEFAULT_MIN_PHASE_DISTANCE_M: int = 200     # м — мин. дистанция фазы
DEFAULT_HR_LAG_SEC: int = 5                 # сек — лаг пульса
DEFAULT_MIN_OSCILLATIONS: int = 3           # мин. число осцилляций для interval


def _calc_phase_distance(distances: list[float] | None, start_idx: int, end_idx: int) -> float:
    """
    Рассчитать дистанцию фазы по кумулятивным координатам.
    Calculate phase distance from cumulative distance array.
    end_idx — exclusive boundary (индекс точки после последней точки фазы).
    """
    if distances is None or start_idx >= len(distances) or end_idx > len(distances):
        return 0.0
    start_dist = distances[start_idx] if start_idx < len(distances) else 0.0
    end_dist = distances[end_idx] if end_idx < len(distances) else distances[-1]
    return max(0.0, end_dist - start_dist)


def _estimate_base_pace(paces: list[float]) -> float:
    """
    Оценка «лёгкого» темпа (easy pace) через 60-й процентиль.
    Устойчив к выбросам быстрых work-фаз.
    Easy pace estimate via 60th percentile — robust to fast work phases.
    """
    if len(paces) < 3:
        return sum(paces) / len(paces) if paces else 5.0
    sorted_paces = sorted(paces)
    idx = int(len(sorted_paces) * 0.6)
    return sorted_paces[min(idx, len(sorted_paces) - 1)]


def _adaptive_pace_gap(paces: list[float], user_gap: float) -> float:
    """
    Адаптивный pace_gap: используем переданный пользователем,
    но не больше разницы между 25-м и 75-м процентилем (data-driven).
    Если data_gap мал (монотонный бег) — возвращаем user_gap без схлопывания.
    Adaptive pace gap: if data-driven gap is too small (monotonous run),
    use user gap directly to avoid hypersensitive detection.
    """
    if len(paces) < 10:
        return max(MIN_EFFECTIVE_PACE_GAP, user_gap)
    sorted_paces = sorted(paces)
    p25 = sorted_paces[len(sorted_paces) // 4]
    p75 = sorted_paces[3 * len(sorted_paces) // 4]
    data_gap = max(0.05, p75 - p25)
    if data_gap < MIN_EFFECTIVE_PACE_GAP:
        return user_gap
    return max(MIN_EFFECTIVE_PACE_GAP, min(user_gap, data_gap))


def detect_pace_oscillations(
    smoothed_paces: list[float],
    times: list[float],
    distances: list[float] | None = None,
    pace_gap: float = DEFAULT_PACE_THRESHOLD,
    min_phase_duration_sec: int = DEFAULT_MIN_PHASE_DURATION_SEC,
    min_phase_distance_m: int = DEFAULT_MIN_PHASE_DISTANCE_M,
) -> tuple[int, list[dict]]:
    """
    Подсчёт work→recovery циклов по порогу относительно темпа лёгких участков.
    Count work→recovery cycles using threshold relative to easy pace.

    Алгоритм:
    1. base_pace = 60-й процентиль (устойчивая оценка easy pace)
    2. pace_gap адаптивный: min(пользовательский, data-driven разброс)
    3. work_threshold = base_pace - effective_gap
    4. Темп <= work_threshold → work-фаза (ускорение)
    5. Темп > work_threshold → recovery-фаза (отдых/разминка/заминка)
    6. Отфильтровать короткие фазы (по длительности ИЛИ дистанции)
    7. Объединить смежные однотипные фазы
    8. Подсчитать число полных work→recovery циклов

    Args:
        smoothed_paces: сглаженный темп (мин/км) для каждой точки
        times: время (сек) для каждой точки
        distances: кумулятивная дистанция (м) для каждой точки (опционально)
        pace_gap: разница между базовым темпом и порогом work-фазы (мин/км)
        min_phase_duration_sec: минимальная длительность фазы (сек)
        min_phase_distance_m: минимальная дистанция фазы (м)

    Returns:
        (oscillation_count, phases) — число циклов и список фаз
    """
    if len(smoothed_paces) < 5 or len(times) < 5:
        return 0, []

    # 1. База: 60-й процентиль (устойчив к быстрым work-фазам)
    base_pace = _estimate_base_pace(smoothed_paces)

    # 2. Адаптивный pace_gap: не больше data-driven разброса
    effective_gap = _adaptive_pace_gap(smoothed_paces, pace_gap)

    # 3. Порог work-фазы (Work phase threshold)
    threshold = base_pace - effective_gap

    # 4. Классифицировать каждую точку (Classify each point)
    raw_phases = []
    current_type = 'work' if smoothed_paces[0] <= threshold else 'recovery'
    phase_start = 0

    for i in range(1, len(smoothed_paces)):
        point_type = 'work' if smoothed_paces[i] <= threshold else 'recovery'
        if point_type != current_type:
            duration_sec = times[i] - times[phase_start]
            if i > phase_start:
                avg_pace = sum(smoothed_paces[phase_start:i]) / (i - phase_start)
            else:
                avg_pace = base_pace
            phase_dist_m = _calc_phase_distance(distances, phase_start, i)
            raw_phases.append({
                'type': current_type,
                'start_idx': phase_start,
                'end_idx': i,
                'avg_pace': round(avg_pace, 2),
                'duration_sec': round(duration_sec, 1),
                'distance_m': round(phase_dist_m, 1),
            })
            phase_start = i
            current_type = point_type

    # Последняя фаза (Last phase)
    duration_sec = times[-1] - times[phase_start]
    if duration_sec > 0:
        avg_pace = sum(smoothed_paces[phase_start:]) / max(1, len(smoothed_paces) - phase_start)
        phase_dist_m = _calc_phase_distance(distances, phase_start, len(smoothed_paces))
        raw_phases.append({
            'type': current_type,
            'start_idx': phase_start,
            'end_idx': len(smoothed_paces) - 1,
            'avg_pace': round(avg_pace, 2),
            'duration_sec': round(duration_sec, 1),
            'distance_m': round(phase_dist_m, 1),
        })

    # 5. Отфильтровать короткие фазы (Filter short phases — duration OR distance)
    filtered_phases = [
        p for p in raw_phases
        if p['duration_sec'] >= min_phase_duration_sec or p['distance_m'] >= min_phase_distance_m
    ]

    # 6. Объединить смежные однотипные фазы (после удаления коротких)
    if filtered_phases:
        merged = [filtered_phases[0]]
        for p in filtered_phases[1:]:
            if merged[-1]['type'] == p['type']:
                merged[-1]['end_idx'] = p['end_idx']
                merged[-1]['duration_sec'] = round(merged[-1]['duration_sec'] + p['duration_sec'], 1)
            else:
                merged.append(p)
        filtered_phases = merged

    if len(filtered_phases) < 2:
        return 0, filtered_phases

    # 7. Подсчитать полные циклы work→recovery (Count full work→recovery cycles)
    oscillation_count = 0
    for i in range(len(filtered_phases) - 1):
        if filtered_phases[i]['type'] == 'work' and filtered_phases[i+1]['type'] == 'recovery':
            oscillation_count += 1

    return oscillation_count, filtered_phases


def compute_hr_lag_correlation(
    times: list[float],
    paces: list[float],
    hrs: list[int | None],
    lag_sec: int = DEFAULT_HR_LAG_SEC,
) -> tuple[float, bool]:
    """
    Корреляция changes(pace) с changes(HR) со сдвигом lag_sec.
    Correlation of pace changes with HR changes (shifted by lag_sec).

    Инвертируем темп: pace_eff = -pace, поэтому pace_eff растёт когда бегун ускоряется.
    Высокая положительная корреляция означает: ускорение → рост пульса через lag_sec
    (классический паттерн интервалов).
    Invert pace so that pace_eff increases when runner speeds up.
    Positive correlation = speed-up → HR increase after lag_sec (classic interval pattern).

    Args:
        times: время (сек) для каждой точки
        paces: темп (мин/км) для каждой точки
        hrs: пульс (уд/мин) для каждой точки (None пропускается)
        lag_sec: задержка пульса относительно темпа (сек)

    Returns:
        (coefficient, is_correlated) — коэффициент корреляции и флаг
    """
    if len(times) < 10:
        return 0.0, False

    valid = [(times[i], paces[i], hrs[i]) for i in range(len(times)) if hrs[i] is not None]
    if len(valid) < 10:
        return 0.0, False

    pace_changes = []
    hr_changes = []

    for i in range(1, len(valid)):
        t_prev, p_prev, _ = valid[i-1]
        t_cur, p_cur, hr_cur = valid[i]
        dt = t_cur - t_prev
        if dt <= 0:
            continue
        pace_change = -(p_cur - p_prev)  # инвертируем: положительный = ускорение

        hr_lag = None
        for j in range(i, len(valid)):
            if valid[j][0] - t_cur >= lag_sec:
                hr_lag = valid[j][2]
                break
        if hr_lag is None and i + 1 < len(valid):
            hr_lag = valid[i][2]

        if hr_lag is not None:
            hr_change = hr_lag - valid[i-1][2]
            pace_changes.append(pace_change)
            hr_changes.append(hr_change)

    if len(pace_changes) < 5:
        return 0.0, False

    n = len(pace_changes)
    mean_p = sum(pace_changes) / n
    mean_h = sum(hr_changes) / n

    cov = sum((pace_changes[i] - mean_p) * (hr_changes[i] - mean_h) for i in range(n))
    std_p = sum((p - mean_p) ** 2 for p in pace_changes) ** 0.5
    std_h = sum((h - mean_h) ** 2 for h in hr_changes) ** 0.5

    if std_p == 0 or std_h == 0:
        return 0.0, False

    coefficient = cov / (std_p * std_h)
    is_correlated = coefficient > 0.3

    return round(coefficient, 3), is_correlated
