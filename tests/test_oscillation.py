# Тесты детекции осцилляций темпа и HR-lag корреляции
# Oscillation detection and HR-lag correlation tests

from src.analysis.oscillation import (
    detect_pace_oscillations,
    compute_hr_lag_correlation,
    _estimate_base_pace,
    _adaptive_pace_gap,
    DEFAULT_PACE_THRESHOLD,
    DEFAULT_MIN_PHASE_DURATION_SEC,
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
        """Стабильный темп → малый data_gap → minimal effective_gap"""
        gap = _adaptive_pace_gap([5.0] * 100, user_gap=1.0)
        assert gap == 0.3  # max(0.3, min(1.0, 0.0))

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
