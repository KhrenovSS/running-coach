# Тесты очистки GPS-данных (GPS cleaning tests)

import math
from datetime import datetime, timezone

from src.parsers.gps import clean_trackpoints, haversine_m


def _tp(lat, lon, time=None, dist=0.0, hr=140, alt=150):
    if time is None:
        time = datetime(2026, 7, 1, 8, 0, 0, tzinfo=timezone.utc)
    return {'time': time, 'hr': hr, 'dist': dist, 'alt': alt, 'lat': lat, 'lon': lon, 'cad': 170}


class TestHaversine:
    def test_zero_distance(self):
        d = haversine_m(55.75, 37.62, 55.75, 37.62)
        assert d == 0.0

    def test_known_distance(self):
        d = haversine_m(55.75, 37.62, 55.76, 37.63)
        assert d > 0
        assert d < 2000

    def test_moscow_spb_approx(self):
        d = haversine_m(55.7558, 37.6173, 59.9343, 30.3351)
        assert 600000 < d < 700000

    def test_sqrt_negative_protected(self):
        d = haversine_m(55.75, 37.62, 55.75, 37.62)
        assert d >= 0


class TestCleanTrackpoints:
    def test_clean_normal_track(self):
        tps = [_tp(55.75, 37.62, dist=i*100.0) for i in range(20)]
        cleaned, log = clean_trackpoints(tps)
        assert len(cleaned) == len(tps)
        assert log == []

    def test_removes_gps_spike(self):
        tps = [
            _tp(55.75, 37.62, dist=0.0),
            _tp(55.75, 37.62, dist=100.0),
            _tp(55.76, 37.63, dist=200.0),
            _tp(55.75, 37.62, dist=300.0),
            _tp(55.75, 37.621, dist=400.0),
        ]
        cleaned, log = clean_trackpoints(tps, max_gps_jump_m=50.0)
        assert len(cleaned) < len(tps)

    def test_removes_impossible_pace(self):
        from datetime import timedelta
        base = datetime(2026, 7, 1, 8, 0, 0, tzinfo=timezone.utc)
        tps = [
            _tp(55.75, 37.62, dist=0.0, hr=120, time=base),
            _tp(55.751, 37.621, dist=100.0, hr=120, time=base + timedelta(seconds=10)),
            _tp(55.752, 37.622, dist=500.0, hr=120, time=base + timedelta(seconds=20)),
            _tp(55.753, 37.623, dist=600.0, hr=120, time=base + timedelta(seconds=30)),
        ]
        cleaned, log = clean_trackpoints(tps, max_credible_pace=3.0, min_hr_for_fast_pace=130)
        assert len(cleaned) < len(tps)

    def test_fewer_than_3_points_returns_unchanged(self):
        tps = [_tp(55.75, 37.62), _tp(55.751, 37.621)]
        cleaned, log = clean_trackpoints(tps)
        assert len(cleaned) == 2
        assert log == []

    def test_none_coords_skipped(self):
        tps = [
            _tp(55.75, 37.62, dist=0.0),
            _tp(None, None, dist=100.0),
            _tp(55.751, 37.621, dist=200.0),
        ]
        cleaned, log = clean_trackpoints(tps, max_gps_jump_m=1.0)
        assert len(cleaned) >= 1

    def test_cleaning_log_format(self):
        tps = [
            _tp(55.75, 37.62, dist=0.0),
            _tp(55.76, 37.63, dist=200.0),
            _tp(55.75, 37.62, dist=400.0),
        ]
        cleaned, log = clean_trackpoints(tps, max_gps_jump_m=10.0)
        if log:
            entry = log[0]
            assert 'removed_count' in entry
            assert 'reason' in entry
            assert isinstance(entry['reason'], list)

    def test_high_hr_overrides_pace_check(self):
        tps = [
            _tp(55.75, 37.62, dist=0.0, hr=160),
            _tp(55.751, 37.621, dist=500.0, hr=165),
            _tp(55.752, 37.622, dist=1000.0, hr=170),
        ]
        cleaned, log = clean_trackpoints(tps, max_credible_pace=3.0, min_hr_for_fast_pace=130)
        assert len(cleaned) == 3

    def test_too_short_after_cleaning(self):
        tps = [
            _tp(55.75, 37.62, dist=0.0, hr=120),
            _tp(55.76, 37.63, dist=50.0, hr=120),
            _tp(55.77, 37.64, dist=100.0, hr=120),
        ]
        cleaned, log = clean_trackpoints(tps, max_gps_jump_m=1.0)
        if len(cleaned) < 2:
            assert any('too_short' in str(r) for entry in log for r in entry['reason'])
