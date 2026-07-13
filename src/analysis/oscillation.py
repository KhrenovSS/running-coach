# Детекция осцилляций темпа и корреляция с пульсом
# Pace oscillation detection and HR lag correlation

# Пороги по умолчанию (default thresholds — перезаписываются из User)
DEFAULT_PACE_THRESHOLD: float = 1.0         # мин/км — разница между базовым и work темпом
DEFAULT_MIN_PHASE_DURATION_SEC: int = 15    # сек — мин. длительность фазы
DEFAULT_HR_LAG_SEC: int = 5                 # сек — лаг пульса
DEFAULT_MIN_OSCILLATIONS: int = 3           # мин. число осцилляций для interval


def detect_pace_oscillations(
    smoothed_paces: list[float],
    times: list[float],
    pace_gap: float = DEFAULT_PACE_THRESHOLD,
    min_phase_duration_sec: int = DEFAULT_MIN_PHASE_DURATION_SEC,
) -> tuple[int, list[dict]]:
    """
    Подсчёт work→recovery циклов по порогу относительно среднего темпа.
    Count work→recovery cycles using threshold relative to average pace.

    Алгоритм:
    1. base_pace = средний темп всей пробежки
    2. work_threshold = base_pace - pace_gap
    3. Темп < work_threshold → work-фаза (ускорение)
    4. Темп >= work_threshold → recovery-фаза (отдых/разминка/заминка)
    5. Объединить смежные фазы, отфильтровать короткие
    6. Подсчитать число полных work→recovery циклов

    Args:
        smoothed_paces: сглаженный темп (мин/км) для каждой точки
        times: время (сек) для каждой точки
        pace_gap: разница между базовым темпом и порогом work-фазы (мин/км)
        min_phase_duration_sec: минимальная длительность фазы (сек)

    Returns:
        (oscillation_count, phases) — число циклов и список фаз
    """
    if len(smoothed_paces) < 5 or len(times) < 5:
        return 0, []

    # 1. Базовый темп = средний темп пробежки (Base pace = average run pace)
    base_pace = sum(smoothed_paces) / len(smoothed_paces)

    # 2. Порог work-фазы (Work phase threshold)
    threshold = base_pace - pace_gap

    # 3. Классифицировать каждую точку (Classify each point)
    raw_phases = []
    current_type = 'work' if smoothed_paces[0] < threshold else 'recovery'
    phase_start = 0

    for i in range(1, len(smoothed_paces)):
        point_type = 'work' if smoothed_paces[i] < threshold else 'recovery'
        if point_type != current_type:
            # Смена фазы — сохранить предыдущую (Phase change — save previous)
            duration_sec = times[i] - times[phase_start]
            avg_pace = sum(smoothed_paces[phase_start:i]) / max(1, i - phase_start)
            raw_phases.append({
                'type': current_type,
                'start_idx': phase_start,
                'end_idx': i,
                'avg_pace': round(avg_pace, 2),
                'duration_sec': round(duration_sec, 1),
            })
            phase_start = i
            current_type = point_type

    # Последняя фаза (Last phase)
    duration_sec = times[-1] - times[phase_start]
    if duration_sec > 0:
        avg_pace = sum(smoothed_paces[phase_start:]) / max(1, len(smoothed_paces) - phase_start)
        raw_phases.append({
            'type': current_type,
            'start_idx': phase_start,
            'end_idx': len(smoothed_paces) - 1,
            'avg_pace': round(avg_pace, 2),
            'duration_sec': round(duration_sec, 1),
        })

    # 4. Отфильтровать короткие фазы (Filter short phases)
    filtered_phases = [p for p in raw_phases if p['duration_sec'] >= min_phase_duration_sec]

    if len(filtered_phases) < 2:
        return 0, filtered_phases

    # 5. Подсчитать полные циклы work→recovery (Count full work→recovery cycles)
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

    Высокая положительная корреляция означает: когда темп растёт —
    пульс растёт через lag_sec секунд (классический паттерн интервалов).

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
        pace_change = p_cur - p_prev  # отрицательный = быстрее

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
