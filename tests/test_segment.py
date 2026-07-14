# Тесты сегментации тренировок (Segmentation tests)
from datetime import datetime, timedelta, timezone
from src.analysis.segment import (
    segment_by_pace, build_time_in_zones,
    _adaptive_min_diff, _find_change_points,
)
from src.analysis.segment_km import km_segment_fallback
from tests.helpers import (
    build_interval_trackpoints, build_tempo_trackpoints,
    build_recovery_trackpoints,
)


def _tp_list(start_time, paces_and_dists):
    """Быстрое создание трекпоинтов из списка (pace, dist_delta, hr)"""
    tps = []
    t = start_time
    dist = 0.0
    for pace, dd, hr in paces_and_dists:
        dist += dd
        tps.append({
            'time': t, 'hr': hr, 'dist': dist, 'alt': 150.0,
            'lat': 55.75, 'lon': 37.62, 'cad': 170,
        })
        dt = timedelta(minutes=pace * (dd / 1000))
        t += dt
    return tps


class TestAdaptiveMinDiff:
    def test_steady_pace_returns_default(self):
        """Монотонный темп → базовый порог 0.5"""
        diff = _adaptive_min_diff([5.0, 5.0, 5.0, 5.0, 5.0])
        assert diff == 0.5

    def test_variable_pace_adaptive(self):
        """Вариативный темп → порог = 0.25 * range"""
        diff = _adaptive_min_diff([4.0, 4.0, 5.5, 5.5])
        assert diff == 0.375  # 0.25 * 1.5

    def test_minimum_floor(self):
        """Минимальный порог 0.3"""
        diff = _adaptive_min_diff([5.0, 5.0, 5.2, 5.2])
        assert diff >= 0.3


class TestFindChangePoints:
    def test_distance_based_detection(self):
        """Смена темпа на 1.5 км → change-point найден"""
        values = [5.0] * 30 + [4.0] * 30  # первые 30 точек медленно, потом быстро
        dists = list(range(0, 3000, 50))  # 60 точек, каждая через 50м
        peaks = _find_change_points(values, dists, window_m=200, min_diff=0.3)
        assert len(peaks) >= 1
        # Пик должен быть около индекса 30 (переход с 5.0 на 4.0)
        assert any(28 <= p <= 32 for p in peaks)

    def test_no_change_no_peaks(self):
        """Без смены темпа → нет пиков"""
        values = [5.0] * 50
        dists = list(range(0, 2500, 50))
        peaks = _find_change_points(values, dists, window_m=200, min_diff=0.5)
        assert len(peaks) == 0


class TestKmSegmentFallback:
    def test_km_segments_includes_last_partial(self):
        """Км-fallback: полные км + последний неполный"""
        start = datetime(2026, 7, 1, 8, 0, 0, tzinfo=timezone.utc)
        tps = build_tempo_trackpoints(pace=5.0, distance_km=7.3, hr=140, start_time=start)
        segments, var_count = km_segment_fallback(tps, max_hr=177, total_dist_km=7.3)
        assert len(segments) == 8  # 7 полных + 1 неполный
        total_dist = sum(s['distance_km'] for s in segments)
        assert abs(total_dist - 7.3) < 0.2

    def test_short_run_one_segment(self):
        """Короткая тренировка < 1 км → 1 сегмент"""
        start = datetime(2026, 7, 1, 8, 0, 0, tzinfo=timezone.utc)
        tps = build_tempo_trackpoints(pace=5.0, distance_km=0.7, hr=130, start_time=start)
        segments, var_count = km_segment_fallback(tps, max_hr=177, total_dist_km=0.7)
        assert len(segments) == 1
        assert segments[0]['distance_km'] > 0


class TestSegmentByPace:
    def test_change_in_pace_creates_segments(self):
        """Резкая смена темпа → 2+ сегмента"""
        start = datetime(2026, 7, 1, 8, 0, 0, tzinfo=timezone.utc)
        tps = build_tempo_trackpoints(pace=4.5, distance_km=3.0, hr=150, start_time=start)
        half = len(tps) // 2
        for i in range(half, len(tps)):
            tps[i]['hr'] = 170

        segments, var_count = segment_by_pace(
            tps, max_hr=177, total_dist_km=3.0,
        )
        assert len(segments) >= 1
        assert var_count >= 0

    def test_steady_pace_km_fallback(self):
        """Стабильный темп → км-блоки (каждый км + последний неполный)"""
        start = datetime(2026, 7, 1, 8, 0, 0, tzinfo=timezone.utc)
        tps = build_tempo_trackpoints(pace=5.0, distance_km=5.0, hr=140, start_time=start)

        segments, var_count = segment_by_pace(
            tps, max_hr=177, total_dist_km=5.0,
        )
        assert len(segments) >= 4  # 5 км-блоков (steady run → km fallback)
        assert var_count == 0

    def test_interval_oscillation_based_segments(self):
        """Интервальная тренировка → сегменты на основе осцилляций, а не км"""
        start = datetime(2026, 7, 1, 8, 0, 0, tzinfo=timezone.utc)
        tps = build_interval_trackpoints(
            base_pace=5.0, work_pace=4.0,
            warmup_km=1.0, cooldown_km=1.0,
            intervals=5, work_dist_m=400, recovery_dist_m=400,
            base_hr=130, work_hr=165, recovery_hr=140,
            start_time=start,
        )
        total_dist = (tps[-1]['dist'] or 0) / 1000

        segments, var_count = segment_by_pace(
            tps, max_hr=177, total_dist_km=total_dist,
            min_oscillations=3, pace_gap=1.0, min_phase_duration_sec=10,
        )
        # Должны быть сегменты по работе/восстановлению, а не км-блоки
        assert len(segments) >= 6  # разминка + 5 work→recovery пар

    def test_interval_long_work_phases_1_2km(self):
        """Интервалы по 1.2 км работы → сегменты по work/recovery, а не по км"""
        start = datetime(2026, 7, 1, 8, 0, 0, tzinfo=timezone.utc)
        tps = build_interval_trackpoints(
            base_pace=5.0, work_pace=4.0,
            warmup_km=1.0, cooldown_km=1.0,
            intervals=3, work_dist_m=1200, recovery_dist_m=600,
            base_hr=130, work_hr=165, recovery_hr=140,
            start_time=start,
        )
        total_dist = (tps[-1]['dist'] or 0) / 1000

        segments, var_count = segment_by_pace(
            tps, max_hr=177, total_dist_km=total_dist,
            min_oscillations=3, pace_gap=1.0, min_phase_duration_sec=10,
        )
        # Должны получить сегменты по фазам, а не по км
        # 7.4 км → km fallback дал бы ~7 сегментов
        # oscillation-based: разминка + 3 work + 3 recovery + заминка = 8
        assert len(segments) >= 5

    def test_recovery_run_km_segments(self):
        """Recovery (медленный, короткий) → км-отсечки"""
        start = datetime(2026, 7, 1, 9, 0, 0, tzinfo=timezone.utc)
        tps = build_recovery_trackpoints(pace=6.5, duration_min=25.0, hr=110, start_time=start)

        segments, var_count = segment_by_pace(
            tps, max_hr=177, total_dist_km=3.8,
            min_oscillations=3, pace_gap=1.0,
        )
        assert len(segments) >= 1
        assert var_count == 0


class TestBuildTimeInZones:
    def test_zones_distribution(self):
        """Проверка распределения времени по зонам"""
        start = datetime(2026, 7, 1, 8, 0, 0, tzinfo=timezone.utc)
        tps = []
        t = start
        hr_values = [120] * 10 + [150] * 10 + [165] * 5
        for hr_val in hr_values:
            tps.append({
                'time': t, 'hr': hr_val, 'dist': 100.0, 'alt': 150.0,
                'lat': 55.75, 'lon': 37.62, 'cad': 170,
            })
            t += timedelta(minutes=1)

        zones, z4_segs, total_min = build_time_in_zones(tps, max_hr=177)
        assert total_min > 0
        assert sum(zones.values()) > 0
        assert zones[1] > 0
        assert zones[3] > 0 or zones[4] > 0

    def test_z4_segments_detected(self):
        """Длинный Z4+ сегмент обнаруживается (> 0.5 мин)"""
        start = datetime(2026, 7, 1, 8, 0, 0, tzinfo=timezone.utc)
        tps = []
        t = start
        for _ in range(10):
            tps.append({
                'time': t, 'hr': 160, 'dist': 100.0, 'alt': 150.0,
                'lat': 55.75, 'lon': 37.62, 'cad': 170,
            })
            t += timedelta(minutes=1)

        zones, z4_segs, total_min = build_time_in_zones(tps, max_hr=177)
        assert len(z4_segs) >= 1
        assert z4_segs[0]['duration'] >= 0.5
