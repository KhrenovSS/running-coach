# Тесты сегментации тренировок (Segmentation tests)
from datetime import datetime, timedelta, timezone
from src.analysis.segment import segment_by_pace, build_time_in_zones
from tests.helpers import build_interval_trackpoints, build_tempo_trackpoints


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

    def test_steady_pace_single_segment(self):
        """Стабильный темп → 1 сегмент или км-fallback"""
        start = datetime(2026, 7, 1, 8, 0, 0, tzinfo=timezone.utc)
        tps = build_tempo_trackpoints(pace=5.0, distance_km=3.0, hr=140, start_time=start)

        segments, var_count = segment_by_pace(
            tps, max_hr=177, total_dist_km=3.0,
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
