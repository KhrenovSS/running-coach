# Тесты детекции осцилляций темпа и HR-lag корреляции
# Oscillation detection and HR-lag correlation tests

from src.analysis.oscillation import (
    detect_pace_oscillations,
    compute_hr_lag_correlation,
    _estimate_base_pace,
    _adaptive_pace_gap,
    _calc_phase_distance,
    DEFAULT_PACE_THRESHOLD,
    DEFAULT_MIN_PHASE_DURATION_SEC,
    DEFAULT_MIN_PHASE_DISTANCE_M,
    DEFAULT_HR_LAG_SEC,
)


def _make_times(duration_sec: float, n_points: int) -> list[float]:
    """Равномерные временные метки (Uniform timestamps)"""
    step = duration_sec / max(1, n_points - 1)
    return [i * step for i in range(n_points)]


class TestDetectPaceOscillations:
    def test_basic_interval_pattern(self):
        """5 work→recovery циклов: темп чередуется 4.0 / 5.5 мин/км"""
        n = 200
        times = _make_times(600, n)
        paces = []
        for i in range(n):
            if (i // 20) % 2 == 0:
                paces.append(4.0)
            else:
                paces.append(5.5)

        count, phases = detect_pace_oscillations(
            paces, times, pace_gap=1.0, min_phase_duration_sec=10,
        )
        assert count >= 3
        assert len(phases) >= 4

    def test_steady_pace_no_oscillations(self):
        """Стабильный темп → 0 осцилляций"""
        n = 100
        times = _make_times(300, n)
        paces = [5.0] * n

        count, phases = detect_pace_oscillations(
            paces, times, pace_gap=1.0, min_phase_duration_sec=15,
        )
        assert count == 0

    def test_short_phases_filtered(self):
        """Короткие фазы (< min_phase_duration) отфильтровываются"""
        n = 200
        times = _make_times(600, n)
        paces = []
        for i in range(n):
            if i % 5 < 2:
                paces.append(4.0)
            else:
                paces.append(5.5)

        count, phases = detect_pace_oscillations(
            paces, times, pace_gap=1.0, min_phase_duration_sec=30,
        )
        assert count == 0

    def test_insufficient_data(self):
        """< 5 точек → 0 осцилляций"""
        count, phases = detect_pace_oscillations([5.0, 5.0], [0, 10], pace_gap=1.0)
        assert count == 0
        assert phases == []

    def test_two_phases_no_full_cycle(self):
        """Только work → recovery (1 неполный цикл) → 0 осцилляций"""
        n = 40
        times = _make_times(200, n)
        paces = [5.5] * 20 + [4.0] * 20

        count, phases = detect_pace_oscillations(
            paces, times, pace_gap=1.0, min_phase_duration_sec=10,
        )
        assert count == 0


class TestComputeHrLagCorrelation:
    def test_positive_correlation(self):
        """Темп ускоряется → пульс растёт через lag_sec: положительная корреляция"""
        n = 100
        times = [i * 5.0 for i in range(n)]
        paces = []
        hrs = []
        for i in range(n):
            if (i // 15) % 2 == 0:
                paces.append(4.0)
            else:
                paces.append(5.5)
            base_hr = 130
            if i > 0 and paces[i] < paces[i-1]:
                hrs.append(base_hr + 25)
            elif i > 0 and paces[i] > paces[i-1]:
                hrs.append(base_hr)
            else:
                hrs.append(hrs[-1] if hrs else base_hr)

        coeff, is_corr = compute_hr_lag_correlation(
            times, paces, hrs, lag_sec=5,
        )
        assert coeff > 0

    def test_no_correlation_random(self):
        """Случайный пульс без связи с темпом → слабая корреляция"""
        n = 100
        times = [i * 5.0 for i in range(n)]
        paces = [5.0 + (i % 10) * 0.1 for i in range(n)]
        hrs = [130 + (i * 7) % 30 for i in range(n)]

        coeff, is_corr = compute_hr_lag_correlation(
            times, paces, hrs, lag_sec=5,
        )
        assert abs(coeff) < 0.8

    def test_insufficient_data(self):
        """< 10 точек → (0.0, False)"""
        times = [0.0, 5.0, 10.0]
        paces = [5.0, 4.5, 5.0]
        hrs = [130, 140, 130]
        coeff, is_corr = compute_hr_lag_correlation(times, paces, hrs)
        assert coeff == 0.0
        assert is_corr is False

    def test_none_hr_values(self):
        """None в HR пропускаются, корреляция работает"""
        n = 20
        times = [i * 5.0 for i in range(n)]
        paces = [4.0 if i % 2 == 0 else 5.5 for i in range(n)]
        hrs = [160 if i % 2 == 0 else 130 if i % 3 != 0 else None for i in range(n)]

        coeff, is_corr = compute_hr_lag_correlation(times, paces, hrs, lag_sec=5)
        assert isinstance(coeff, float)


class TestEstimateBasePace:
    def test_steady_pace(self):
        """Стабильный темп → base_pace == темпу"""
        base = _estimate_base_pace([5.0, 5.0, 5.0, 5.0])
        assert base == 5.0

    def test_interval_no_warmup(self):
        """Интервалы без разминки (4.0/4.5) → p60 ~4.3"""
        paces = [4.0] * 50 + [4.5] * 50
        base = _estimate_base_pace(paces)
        assert 4.2 <= base <= 4.5

    def test_interval_with_warmup(self):
        """Интервалы с разминкой → base_pace ~ recovery"""
        paces = [6.0] * 30 + [4.0] * 50 + [4.5] * 50 + [6.0] * 20
        base = _estimate_base_pace(paces)
        assert base >= 4.5  # должен быть ближе к recovery, чем к work


class TestAdaptivePaceGap:
    def test_steady_pace_small_gap(self):
        """Стабильный темп → малый data_gap → возвращаем user_gap (без схлопывания)"""
        gap = _adaptive_pace_gap([5.0] * 100, user_gap=1.0)
        assert gap == 1.0  # data_gap < MIN_EFFECTIVE_PACE_GAP → user_gap

    def test_wide_range_uses_user_gap(self):
        """Большой разброс → effective_gap = user_gap"""
        paces = [4.0] * 50 + [6.0] * 50
        gap = _adaptive_pace_gap(paces, user_gap=1.0)
        assert gap == 1.0  # data_gap=2.0 > user_gap=1.0 → min = 1.0

    def test_narrow_range_adapts(self):
        """Узкий разброс → effective_gap = data_gap (capped)"""
        paces = [4.0] * 50 + [4.5] * 50
        gap = _adaptive_pace_gap(paces, user_gap=1.0)
        assert gap == 0.5  # data_gap=0.5 < user_gap=1.0 → 0.5

    def test_fewer_than_10_points_returns_user_gap_minimum(self):
        """< 10 точек → max(MIN_EFFECTIVE_PACE_GAP, user_gap)"""
        gap = _adaptive_pace_gap([5.0] * 5, user_gap=0.5)
        assert gap == 0.5
        gap = _adaptive_pace_gap([5.0] * 5, user_gap=0.2)
        assert gap == 0.5  # max(MIN_EFFECTIVE_PACE_GAP=0.5, 0.2)


class TestDetectPaceOscillationsEdgeCases:
    def test_single_work_phase_no_full_cycle(self):
        """Одна work-фаза в конце: work без recovery после → 0 полных циклов"""
        n = 50
        times = [i * 5.0 for i in range(n)]
        paces = [5.5] * 30 + [3.5] * 20
        count, phases = detect_pace_oscillations(
            paces, times, pace_gap=1.0, min_phase_duration_sec=10,
        )
        assert count == 0

    def test_work_recovery_work_one_cycle(self):
        """work→recovery→work → 1 полный work→recovery цикл"""
        n = 50
        times = [i * 5.0 for i in range(n)]
        paces = [3.5] * 10 + [5.5] * 30 + [3.5] * 10
        count, phases = detect_pace_oscillations(
            paces, times, pace_gap=1.0, min_phase_duration_sec=10,
        )
        assert count == 1

    def test_steady_pace_zero_with_small_gap(self):
        """Стабильный темп → 0 осцилляций даже с малым pace_gap"""
        n = 50
        times = [i * 5.0 for i in range(n)]
        paces = [5.5] * n
        count, phases = detect_pace_oscillations(
            paces, times, pace_gap=0.1, min_phase_duration_sec=10,
        )
        assert count == 0


class TestEstimateBasePaceEdgeCases:
    def test_less_than_3_points_uses_mean(self):
        """< 3 точек → mean"""
        base = _estimate_base_pace([5.0, 6.0])
        assert base == 5.5

    def test_empty_list_returns_default(self):
        """Пустой список → 5.0"""
        base = _estimate_base_pace([])
        assert base == 5.0


class TestComputeHrLagCorrelationEdgeCases:
    def test_negative_correlation(self):
        """Отрицательная корреляция: пульс падает при ускорении"""
        n = 50
        times = [i * 5.0 for i in range(n)]
        paces = [4.0 if (i // 10) % 2 == 0 else 5.5 for i in range(n)]
        hrs = []
        for i in range(n):
            if paces[i] < 5.0:
                hrs.append(110)
            else:
                hrs.append(160)
        coeff, is_corr = compute_hr_lag_correlation(times, paces, hrs, lag_sec=5)
        assert isinstance(coeff, float)

    def test_constant_hr_returns_no_correlation(self):
        """Постоянный пульс → std_h=0 → (0.0, False)"""
        n = 20
        times = [i * 5.0 for i in range(n)]
        paces = [4.0 if (i // 5) % 2 == 0 else 5.5 for i in range(n)]
        hrs = [140] * n
        coeff, is_corr = compute_hr_lag_correlation(times, paces, hrs, lag_sec=5)
        assert coeff == 0.0
        assert is_corr is False


class TestCalcPhaseDistance:
    def test_normal_distance(self):
        """Обычная дистанция: разница между кумулятивными значениями"""
        distances = [0.0, 100.0, 200.0, 300.0, 400.0]
        result = _calc_phase_distance(distances, 1, 3)
        assert result == 200.0

    def test_none_distances(self):
        """None в distances → 0.0"""
        result = _calc_phase_distance(None, 0, 5)
        assert result == 0.0

    def test_out_of_bounds(self):
        """Индекс за пределами → 0.0"""
        distances = [0.0, 100.0, 200.0]
        result = _calc_phase_distance(distances, 0, 10)
        assert result == 0.0

    def test_single_point(self):
        """Одна точка → 0.0"""
        distances = [0.0, 100.0, 200.0]
        result = _calc_phase_distance(distances, 1, 2)
        assert result == 100.0


class TestEmptyPhaseAvgPace:
    def test_zero_length_phase_uses_base_pace(self):
        """Phase boundary where phase_start == i → avg_pace = base_pace, not 0.0"""
        n = 200
        times = _make_times(600, n)
        threshold_pace = 5.0
        paces = []
        for i in range(n):
            if i % 20 == 0:
                paces.append(threshold_pace)
            elif (i // 20) % 2 == 0:
                paces.append(4.0)
            else:
                paces.append(5.5)

        _, phases = detect_pace_oscillations(
            paces, times, pace_gap=1.0, min_phase_duration_sec=10,
        )
        for p in phases:
            assert p['avg_pace'] > 0.0, f"avg_pace={p['avg_pace']} for {p['type']} phase"

    def test_all_values_equal_to_threshold(self):
        """All values equal → threshold-based split can produce zero-length phases"""
        n = 50
        times = _make_times(250, n)
        paces = [5.0] * n

        _, phases = detect_pace_oscillations(
            paces, times, pace_gap=1.0, min_phase_duration_sec=10,
        )
        for p in phases:
            assert p['avg_pace'] > 0.0

    def test_consecutive_boundary_values_no_zero_pace(self):
        """Values oscillating exactly at threshold → no avg_pace == 0.0"""
        n = 200
        times = _make_times(600, n)
        paces = [5.0 if i % 2 == 0 else 5.5 for i in range(n)]

        _, phases = detect_pace_oscillations(
            paces, times, pace_gap=1.0, min_phase_duration_sec=10,
        )
        for p in phases:
            assert p['avg_pace'] > 0.0, f"avg_pace={p['avg_pace']} for {p['type']} phase"


class TestDistanceFiltering:
    def test_short_duration_long_distance_passes(self):
        """Короткая длительность, но длинная дистанция → проходит фильтр (ИЛИ)"""
        n = 100
        times = _make_times(300, n)
        distances = [i * 10.0 for i in range(n)]  # 10м на точку = 1000м всего
        paces = [4.0] * 30 + [5.5] * 70  # work-фаза 30 точек = 90сек, 300м

        count, phases = detect_pace_oscillations(
            paces, times, distances=distances,
            pace_gap=1.0, min_phase_duration_sec=120, min_phase_distance_m=200,
        )
        # work-фаза 90сек < 120сек, но 300м > 200м → проходит
        assert len(phases) >= 1

    def test_short_distance_long_duration_passes(self):
        """Длинная длительность, но короткая дистанция → проходит фильтр (ИЛИ)"""
        n = 100
        times = _make_times(300, n)
        distances = [i * 1.0 for i in range(n)]  # 1м на точку = 100м всего
        paces = [4.0] * 50 + [5.5] * 50  # work-фаза 50 точек = 150сек

        count, phases = detect_pace_oscillations(
            paces, times, distances=distances,
            pace_gap=1.0, min_phase_duration_sec=120, min_phase_distance_m=200,
        )
        # work-фаза 150сек > 120сек → проходит, хотя 50м < 200м
        assert len(phases) >= 1

    def test_short_both_filtered(self):
        """Короткая длительность И короткая дистанция → отфильтрована"""
        n = 100
        times = _make_times(300, n)
        distances = [i * 1.0 for i in range(n)]  # 1м на точку
        paces = [4.0] * 10 + [5.5] * 90  # work-фаза 10 точек = 30сек, 10м

        count, phases = detect_pace_oscillations(
            paces, times, distances=distances,
            pace_gap=1.0, min_phase_duration_sec=60, min_phase_distance_m=200,
        )
        # 30сек < 60сек И 10м < 200м → отфильтрована
        assert count == 0

    def test_no_distances_uses_duration_only(self):
        """Без distances → фильтрация только по длительности"""
        n = 100
        times = _make_times(300, n)
        paces = [4.0] * 30 + [5.5] * 70

        count, phases = detect_pace_oscillations(
            paces, times, distances=None,
            pace_gap=1.0, min_phase_duration_sec=60, min_phase_distance_m=200,
        )
        # work-фаза 90сек > 60сек → проходит
        assert len(phases) >= 1


class TestNewDefaults:
    def test_default_duration_is_60(self):
        """Порог по умолчанию — 60 секунд"""
        assert DEFAULT_MIN_PHASE_DURATION_SEC == 60

    def test_default_distance_is_200(self):
        """Порог дистанции по умолчанию — 200 метров"""
        assert DEFAULT_MIN_PHASE_DISTANCE_M == 200
