# Интеграционные тесты полного пайплайна анализа
# Integration tests for the full analysis pipeline

from datetime import datetime, timedelta, timezone

import pytest

from src.analysis import process_trackpoints
from src.parsers.gps import clean_trackpoints
from tests.helpers import (
    build_interval_trackpoints,
    build_tempo_trackpoints,
    build_long_trackpoints,
    build_recovery_trackpoints,
    build_gps_glitch_trackpoints,
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
            # suspect_flags — уникальные строки-причины из cleaning_log (не dict'ы)
            # (suspect_flags are unique reason strings, not raw log dicts)
            expected = {r for entry in cleaning_log for r in entry['reason']}
            assert set(result['suspect_flags']) >= expected
            assert all(isinstance(f, str) for f in result['suspect_flags'])

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


class TestGpsUnreliablePipeline:
    """Кейс-42 (01.09.2026): 15 мин GPS-сбоя → пайплайн честно помечает трек
    недостоверным и подменяет дистанцию оценкой по шагам."""

    @pytest.fixture(autouse=True)
    def _no_weather(self, monkeypatch):
        # офлайн: погодный API не дёргаем (offline: no weather API calls)
        monkeypatch.setattr("src.analysis.fetch_weather", lambda *a, **k: None)

    def test_case42_distance_replaced_by_cadence_estimate(self):
        tps = build_gps_glitch_trackpoints()   # 15' сбой (5.7 м/с) + 30' чисто
        device_km = tps[-1]['dist'] / 1000     # раздутая device-дистанция ~9.5 км

        result = process_trackpoints(tps, tps[0]['time'], max_hr=177, pace_gap=1.0)

        assert result is not None
        gq = result['gps_quality']
        assert gq is not None and gq['unreliable'] is True
        assert 'gps_unreliable' in result['suspect_flags']
        # дистанция — оценка по шагам, не мусор часов и не урезанный GPS
        est = gq['distance']
        assert est['source'] == 'cadence_estimate'
        assert est['quality'] == 'estimate'
        assert result['total_distance_km'] == est['estimated_km']
        assert result['total_distance_km'] < device_km * 0.8
        assert gq['gps_distance_km'] < est['estimated_km']  # урезанный GPS сохранён
        # темп пересчитан от оценки (pace recomputed from the estimate)
        assert result['avg_pace'] == pytest.approx(
            result['duration_minutes'] / est['estimated_km'], rel=0.02)
        # темповые сигналы мусорные → классификация не «интервалы»
        assert result['training_type'] != 'interval'

    def test_clean_track_distance_not_replaced(self):
        tps = build_gps_glitch_trackpoints(glitch_min=0, clean_min=45,
                                           clean_pace=7.0)
        device_km = tps[-1]['dist'] / 1000

        result = process_trackpoints(tps, tps[0]['time'], max_hr=177, pace_gap=1.0)

        assert result is not None
        gq = result['gps_quality']
        assert gq is not None and gq['unreliable'] is False
        assert 'distance' not in gq                       # оценка не подмешана
        assert result['total_distance_km'] == pytest.approx(device_km, rel=0.01)
        assert 'gps_unreliable' not in result.get('suspect_flags', [])


class TestAveragingFixesF0:
    """F0 — аудит усреднений (BACKLOG #277/#280/#282): время выброшенных
    GPS-дельт не размывает avg_pace; одиночный HR-спайк не становится
    максимумом; cad=0 (стояние) не входит в средний каденс."""

    @pytest.fixture(autouse=True)
    def _no_weather(self, monkeypatch):
        # офлайн: погодный API не дёргаем (offline: no weather API calls)
        monkeypatch.setattr("src.analysis.fetch_weather", lambda *a, **k: None)

    @staticmethod
    def _tps_with_fast_gps_deltas(n_clean_before=240, n_fast=12, n_clean_after=96):
        """Чистый бег 6:00/км (дельты 5с) с врезкой быстрых GPS-дельт 30 м/5с
        (implied pace 2.78 < max_credible_pace=3.0). HR=140 ≥ 130 → очистка
        точки НЕ удаляет, дистанцию выбрасывает пересборка (#277).
        Доля мусора мала → gps_quality остаётся reliable."""
        start = datetime(2026, 7, 1, 8, 0, 0, tzinfo=timezone.utc)
        tps = []
        state = {'t': start, 'dist': 0.0, 'lat': 55.75}

        def add(dd):
            state['dist'] += dd
            tps.append({'time': state['t'], 'hr': 140, 'dist': state['dist'],
                        'alt': 150.0, 'lat': state['lat'], 'lon': 37.62, 'cad': 170})
            state['t'] += timedelta(seconds=5)
            state['lat'] += 0.00001

        clean_dd = 5 / 60 / 6.0 * 1000            # 13.89 м за 5с при 6:00/км
        for _ in range(n_clean_before):
            add(clean_dd)
        for _ in range(n_fast):
            add(30.0)                              # 2.78 мин/км — GPS-мусор
        for _ in range(n_clean_after):
            add(clean_dd)
        return tps

    def test_dropped_gps_deltas_time_excluded_from_avg_pace(self):
        """#277: время выброшенных дельт не входит в avg_pace —
        чистое время / чистая дистанция, а не полное время / дистанция."""
        tps = self._tps_with_fast_gps_deltas()
        result = process_trackpoints(tps, tps[0]['time'], max_hr=177, pace_gap=1.0)

        assert result is not None
        gq = result['gps_quality']
        assert gq is not None and gq['unreliable'] is False   # мусора мало
        # 12 быстрых дельт × 5с = 1.0 мин выброшенного времени
        dropped_min = 12 * 5 / 60
        expected = (result['duration_minutes'] - dropped_min) / result['total_distance_km']
        naive = result['duration_minutes'] / result['total_distance_km']
        assert result['avg_pace'] == pytest.approx(expected, abs=0.03)
        assert result['avg_pace'] == pytest.approx(6.0, abs=0.1)  # честный темп бега
        assert result['avg_pace'] < naive - 0.15   # старое поведение — медленнее

    def test_single_hr_spike_not_session_max(self):
        """#280: одиночный спайк 230 на 1 сэмпл не становится max_heart_rate —
        максимум берётся из сглаженного пика (медиана 5)."""
        tps = build_tempo_trackpoints(pace=5.0, distance_km=5.0, hr=140)
        tps[len(tps) // 2]['hr'] = 230
        result = process_trackpoints(tps, tps[0]['time'], max_hr=177, pace_gap=1.0)

        assert result is not None
        assert result['max_heart_rate'] < 230
        assert result['max_heart_rate'] <= 150       # рядом с фоном 140–145
        assert result['max_heart_rate'] == result['hr_peak_smoothed']

    def test_avg_cadence_ignores_zero_samples(self):
        """#282: cad=0 (стояние на месте) исключается из среднего каденса —
        и в итоговом avg_cadence, и в км-сегментах (_build_segment_stats)."""
        tps = build_tempo_trackpoints(pace=5.0, distance_km=5.0, hr=140)  # cad=175
        for tp in tps[::3]:
            tp['cad'] = 0
        result = process_trackpoints(tps, tps[0]['time'], max_hr=177, pace_gap=1.0)

        assert result is not None
        assert result['avg_cadence'] == 175          # нули не размыли среднее
        seg_cads = [s['avg_cadence'] for s in result['segments_json']
                    if s.get('avg_cadence') is not None]
        assert seg_cads and all(c == 175 for c in seg_cads)

    def test_avg_cadence_none_when_all_zero(self):
        """#282 edge: каденс весь нулевой → честный None, не 0."""
        tps = build_tempo_trackpoints(pace=6.0, distance_km=2.0, hr=140)
        for tp in tps:
            tp['cad'] = 0
        result = process_trackpoints(tps, tps[0]['time'], max_hr=177, pace_gap=1.0)
        assert result is not None
        assert result['avg_cadence'] is None
