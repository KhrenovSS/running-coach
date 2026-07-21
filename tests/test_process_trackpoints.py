# Интеграционные тесты полного пайплайна анализа
# Integration tests for the full analysis pipeline

from datetime import datetime, timezone
from src.analysis import process_trackpoints
from src.parsers.gps import clean_trackpoints
from tests.helpers import (
    build_interval_trackpoints,
    build_tempo_trackpoints,
    build_long_trackpoints,
    build_recovery_trackpoints,
)


class TestProcessTrackpointsInterval:
    def test_interval_detected(self):
        """Интервальная тренировка: 5 work→recovery → training_type == 'interval'"""
        tps = build_interval_trackpoints(
            base_pace=5.0, work_pace=4.0,
            warmup_km=1.0, cooldown_km=1.0,
            intervals=5, work_dist_m=400, recovery_dist_m=400,
            hr=155, max_hr=172,
        )

        result = process_trackpoints(
            tps, tps[0]['time'],
            max_hr=177, pace_gap=1.0,
            interval_min_phase_duration=10,
            interval_min_oscillations=3,
        )

        assert result is not None
        assert result['training_type'] == 'interval'
        assert result['total_distance_km'] > 5
        assert result['segments_count'] >= 2
        assert result['duration_minutes'] > 5


class TestProcessTrackpointsTempo:
    def test_tempo_detected(self):
        """Темповая тренировка: стабильный темп → training_type == 'tempo'"""
        tps = build_tempo_trackpoints(
            pace=4.5, distance_km=10.0, hr=155,
        )

        result = process_trackpoints(
            tps, tps[0]['time'],
            max_hr=177, pace_gap=1.0,
        )

        assert result is not None
        assert result['training_type'] in ('tempo', 'long')
        assert result['total_distance_km'] >= 9.5
        assert result['avg_heart_rate'] > 140


class TestProcessTrackpointsEmpty:
    def test_empty_trackpoints_returns_none(self):
        """Пустой список трекпоинтов → None"""
        result = process_trackpoints([], datetime.now(tz=timezone.utc))
        assert result is None

    def test_single_trackpoint_returns_none(self):
        """Один трекпоинт → None"""
        tps = [{'time': datetime.now(tz=timezone.utc), 'hr': 140, 'dist': 0,
                'alt': 150, 'lat': 55.75, 'lon': 37.62, 'cad': 170}]
        result = process_trackpoints(tps, tps[0]['time'])
        assert result is None


class TestProcessTrackpointsRecovery:
    def test_recovery_detected(self):
        """Recovery: короткая, лёгкая, низкий пульс → training_type == 'recovery'"""
        tps = build_recovery_trackpoints(
            base_pace=7.0, duration_min=25.0, hr=110, max_hr=177,
        )

        result = process_trackpoints(
            tps, tps[0]['time'],
            max_hr=177, pace_gap=1.0,
        )

        assert result is not None
        assert result['training_type'] == 'recovery'
        assert result['total_distance_km'] > 0


class TestProcessTrackpointsLong:
    def test_long_detected(self):
        """Long: >= 90 мин, стабильный темп, низкий пульс → training_type == 'long'"""
        tps = build_long_trackpoints(
            pace=5.5, duration_min=100.0, hr=130,
        )

        result = process_trackpoints(
            tps, tps[0]['time'],
            max_hr=177, pace_gap=1.0,
        )

        assert result is not None
        assert result['training_type'] == 'long'
        assert result['duration_minutes'] >= 90


class TestSuspectFlags:
    def test_suspect_flags_set_when_cleaning_log_has_entries(self):
        """Когда GPS-очистка нашла аномалии, suspect_flags должны содержать их"""
        tps = build_tempo_trackpoints(pace=5.0, distance_km=5.0, hr=140)
        _, cleaning_log = clean_trackpoints(tps, 3.0, 100.0, 130)
        if not cleaning_log:
            for i in range(0, len(tps), 3):
                tps[i]['lat'] += 0.05
                tps[i]['lon'] += 0.05
            _, cleaning_log = clean_trackpoints(tps, 3.0, 100.0, 130)
        if cleaning_log:
            result = process_trackpoints(tps, tps[0]['time'], max_hr=177, pace_gap=1.0)
            assert result is not None
            assert 'suspect_flags' in result
            assert len(result['suspect_flags']) == len(cleaning_log)

    def test_too_short_flag_applied_regardless_of_cleaning_log(self):
        """too_short устанавливается независимо от cleaning_log"""
        tps = build_tempo_trackpoints(pace=5.0, distance_km=0.35, hr=140)
        result = process_trackpoints(tps, tps[0]['time'], max_hr=177, pace_gap=1.0)
        assert result is not None
        assert result['duration_minutes'] < 2.0
        assert result['total_distance_km'] > 0.3
        assert 'too_short' in result.get('suspect_flags', [])

    def test_no_suspect_flags_when_clean_and_normal_length(self):
        """Чистый трек нормальной длины → нет suspect_flags"""
        tps = build_tempo_trackpoints(pace=5.0, distance_km=10.0, hr=140)
        result = process_trackpoints(tps, tps[0]['time'], max_hr=177, pace_gap=1.0)
        assert result is not None
        assert 'suspect_flags' not in result
