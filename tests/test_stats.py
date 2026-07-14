# Тесты функций статистики (Statistics functions tests)

from datetime import datetime, timezone
from src.services.stats import fmt_duration, calc_stats, zone_ranges, get_zone_bars_data, get_nav_data


class TestFmtDuration:
    def test_none_returns_empty(self):
        assert fmt_duration(None) == ""

    def test_zero_returns_empty(self):
        assert fmt_duration(0) == ""

    def test_minutes_only(self):
        assert fmt_duration(45) == "45мин"

    def test_hours_and_minutes(self):
        assert fmt_duration(125) == "2ч 5мин"

    def test_exact_hour(self):
        assert fmt_duration(60) == "1ч"

    def test_multiple_hours(self):
        assert fmt_duration(185) == "3ч 5мин"

    def test_less_than_minute(self):
        assert fmt_duration(0.5) == "0мин"


class FakeSession:
    def __init__(self, dist=0.0, dur=0.0, ttype='tempo', segs=None, begin_ts=None):
        self.total_distance_km = dist
        self.duration_minutes = dur
        self.training_type = ttype
        self.segments_json = segs or []
        self.begin_ts = begin_ts or datetime(2026, 7, 1, tzinfo=timezone.utc)


class TestCalcStats:
    def test_empty_sessions(self):
        stats = calc_stats([])
        assert stats['total_km'] == 0.0
        assert stats['total_min'] == 0
        assert stats['type_count'] == {}

    def test_single_session(self):
        s = FakeSession(dist=10.5, dur=55.0, ttype='tempo')
        stats = calc_stats([s])
        assert stats['total_km'] == 10.5
        assert stats['total_min'] == 55

    def test_multiple_sessions(self):
        sessions = [
            FakeSession(dist=10.0, dur=50.0, ttype='tempo'),
            FakeSession(dist=21.0, dur=110.0, ttype='long'),
            FakeSession(dist=5.0, dur=30.0, ttype='recovery'),
        ]
        stats = calc_stats(sessions)
        assert stats['total_km'] == 36.0
        assert stats['total_min'] == 190
        assert stats['type_count'] == {'tempo': 1, 'long': 1, 'recovery': 1}

    def test_zone_min_accumulates(self):
        segs = [
            {'zone': 3, 'duration_min': 20.0},
            {'zone': 4, 'duration_min': 10.0},
            {'zone': 3, 'duration_min': 5.0},
        ]
        s = FakeSession(dist=10.0, dur=60.0, ttype='tempo', segs=segs)
        stats = calc_stats([s])
        assert stats['zone_min'][3] == 25.0
        assert stats['zone_min'][4] == 10.0

    def test_none_segments_does_not_crash(self):
        s = FakeSession(dist=10.0, dur=60.0, ttype='tempo', segs=None)
        stats = calc_stats([s])
        assert stats['total_km'] == 10.0

    def test_duration_formatted_in_result(self):
        s = FakeSession(dist=21.0, dur=110.0, ttype='long')
        stats = calc_stats([s])
        assert stats['total_dur'] == "1ч 50мин"

    def test_type_count_tracks_types(self):
        sessions = [
            FakeSession(ttype='interval'),
            FakeSession(ttype='interval'),
            FakeSession(ttype='tempo'),
        ]
        stats = calc_stats(sessions)
        assert stats['type_count'] == {'interval': 2, 'tempo': 1}


class TestZoneRanges:
    def test_returns_5_zones(self):
        ranges = zone_ranges(177)
        assert len(ranges) == 5

    def test_zone1_lower_bound(self):
        ranges = zone_ranges(177)
        assert ranges[1].startswith("≤")

    def test_zone5_upper_bound(self):
        ranges = zone_ranges(177)
        assert str(177) in ranges[5]

    def test_different_max_hr(self):
        ranges = zone_ranges(200)
        assert str(200) in ranges[5]

    def test_zone_ranges_monotonic(self):
        ranges = zone_ranges(177)
        for z in range(1, 5):
            z_low = int(ranges[z].split('–')[0].replace('≤', '')) if '–' not in ranges[z] else int(ranges[z].split('–')[0])
            z_next_low = int(ranges[z+1].split('–')[0])
            assert z_low < z_next_low


class TestGetZoneBarsData:
    def test_empty_if_no_total_min(self):
        data = get_zone_bars_data({1: 0.0}, 0, 177)
        assert data == []

    def test_returns_5_entries(self):
        data = get_zone_bars_data({1: 30.0, 2: 20.0, 3: 10.0, 4: 5.0, 5: 0.0}, total_min=65.0, max_hr=177)
        assert len(data) == 5

    def test_percentages_sum_to_100(self):
        data = get_zone_bars_data({1: 30.0, 2: 20.0, 3: 10.0, 4: 5.0, 5: 0.0}, total_min=65.0, max_hr=177)
        total_pct = sum(d['pct'] for d in data)
        assert abs(total_pct - 100) < 2

    def test_includes_duration_string(self):
        data = get_zone_bars_data({1: 65.0}, total_min=65.0, max_hr=177)
        assert data[0]['duration'] == "1ч 5мин"


class TestGetNavData:
    def test_empty_sessions(self):
        data, year, month, title = get_nav_data([], None, None)
        assert data == {}
        assert title == ""

    def test_single_session(self):
        sessions = [FakeSession(begin_ts=datetime(2026, 7, 15, tzinfo=timezone.utc))]
        data, year, month, title = get_nav_data(sessions, None, None)
        assert 2026 in data
        assert 7 in data[2026]
        assert "Июль" in title

    def test_auto_selects_latest(self):
        sessions = [
            FakeSession(begin_ts=datetime(2025, 6, 1, tzinfo=timezone.utc)),
            FakeSession(begin_ts=datetime(2026, 7, 1, tzinfo=timezone.utc)),
        ]
        data, year, month, title = get_nav_data(sessions, None, None)
        assert year == 2026
        assert month == 7

    def test_none_begin_ts_skipped(self):
        s = FakeSession()
        s.begin_ts = None
        data, year, month, title = get_nav_data([s], None, None)
        assert data == {}
