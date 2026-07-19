# Тесты классификации тренировок (Training classification tests)
from src.analysis.classify import classify_training


def _default_zones(total_min=60):
    """Зоны по умолчанию: 50% в Z2, остальное распределено"""
    return {1: total_min * 0.1, 2: total_min * 0.5, 3: total_min * 0.25,
            4: total_min * 0.1, 5: total_min * 0.05}


def _no_z4_zones(total_min=60):
    """Зоны без Z4/Z5 — для проверки recovery/long без влияния Z4"""
    return {1: total_min * 0.15, 2: total_min * 0.60, 3: total_min * 0.25,
            4: 0, 5: 0}


class TestClassifyTraining:
    def test_interval_by_oscillation_and_hr_correlated(self):
        """oscillation_count >= 2 AND hr_correlated AND segments >= 3 → interval"""
        t_type, seg_count = classify_training(
            var_count=0,
            time_in_zone=_default_zones(),
            total_duration_min=60,
            max_hr=177,
            z4_plus_segments=[],
            avg_hr=140,
            oscillation_count=4,
            min_oscillations=3,
            hr_correlated=True,
            segments_len=5,
        )
        assert t_type == 'interval'

    def test_interval_by_oscillation_and_high_hr(self):
        """oscillation_count >= 2 AND avg_hr >= Z3 AND segments >= 3 → interval"""
        t_type, _ = classify_training(
            var_count=0,
            time_in_zone=_default_zones(),
            total_duration_min=60,
            max_hr=177,
            z4_plus_segments=[],
            avg_hr=160,
            oscillation_count=3,
            min_oscillations=3,
            segments_len=4,
        )
        assert t_type == 'interval'

    def test_interval_by_oscillations_and_hr_correlated(self):
        """oscillation_count >= 2 AND hr_correlated AND segments >= 3 → interval"""
        t_type, _ = classify_training(
            var_count=0,
            time_in_zone=_default_zones(),
            total_duration_min=60,
            max_hr=177,
            z4_plus_segments=[],
            avg_hr=140,
            oscillation_count=2,
            hr_correlated=True,
            min_oscillations=2,
            segments_len=3,
        )
        assert t_type == 'interval'

    def test_tempo_one_variable_km(self):
        """var_count == 1, без осцилляций → tempo"""
        t_type, seg_count = classify_training(
            var_count=1,
            time_in_zone=_default_zones(),
            total_duration_min=50,
            max_hr=177,
            z4_plus_segments=[],
            avg_hr=150,
        )
        assert t_type == 'tempo'
        assert seg_count == 1

    def test_long_run(self):
        """Длительность >= 90 мин, Z2 >= 50%, нет Z4+ сегментов, z4 < 15% → long"""
        zones = _no_z4_zones(100)
        t_type, _ = classify_training(
            var_count=0,
            time_in_zone=zones,
            total_duration_min=100,
            max_hr=177,
            z4_plus_segments=[],
            avg_hr=130,
        )
        assert t_type == 'long'

    def test_recovery(self):
        """avg_hr <= 0.70*max_hr, нет Z4+ сегментов, z4 < 5% → recovery"""
        zones = _no_z4_zones(30)
        t_type, _ = classify_training(
            var_count=0,
            time_in_zone=zones,
            total_duration_min=25,
            max_hr=177,
            z4_plus_segments=[],
            avg_hr=120,
        )
        assert t_type == 'recovery'

    def test_default_tempo(self):
        """Нет особых условий → tempo"""
        t_type, seg_count = classify_training(
            var_count=0,
            time_in_zone=_default_zones(45),
            total_duration_min=45,
            max_hr=177,
            z4_plus_segments=[{'duration': 10, 'avg_hr': 160}],
            avg_hr=145,
            oscillation_count=0,
            hr_correlated=False,
        )
        assert t_type == 'tempo'

    def test_interval_segments_count(self):
        """Интервал: segments_count = max(var_count, oscillation_count)"""
        _, seg_count = classify_training(
            var_count=4,
            time_in_zone=_default_zones(),
            total_duration_min=60,
            max_hr=177,
            z4_plus_segments=[],
            avg_hr=160,
            oscillation_count=6,
            hr_correlated=True,
            min_oscillations=2,
            segments_len=6,
        )
        assert seg_count == 6

    def test_long_with_z4_segment_becomes_tempo(self):
        """Длительная тренировка с длинным Z4+ сегментом → НЕ long"""
        zones = {1: 10, 2: 60, 3: 15, 4: 10, 5: 5}
        t_type, _ = classify_training(
            var_count=0,
            time_in_zone=zones,
            total_duration_min=100,
            max_hr=177,
            z4_plus_segments=[{'duration': 10, 'avg_hr': 160}],
            avg_hr=130,
        )
        assert t_type != 'long'

    def test_zero_duration_does_not_crash(self):
        """Нулевая длительность → без ошибок"""
        t_type, _ = classify_training(
            var_count=0,
            time_in_zone={1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
            total_duration_min=0,
            max_hr=177,
            z4_plus_segments=[],
            avg_hr=130,
        )
        assert t_type in ('tempo', 'recovery')

    def test_high_var_count_no_oscillations_is_tempo(self):
        """var_count >= 3, 0 осцилляций → tempo (не interval без oscillations)"""
        t_type, seg_count = classify_training(
            var_count=5,
            time_in_zone=_default_zones(),
            total_duration_min=60,
            max_hr=177,
            z4_plus_segments=[],
            avg_hr=140,
            oscillation_count=0,
        )
        assert t_type == 'tempo'

    def test_var_count_2_oscillation_1_not_interval(self):
        """var_count=2, oscillation_count=1 без HR → tempo"""
        t_type, _ = classify_training(
            var_count=2,
            time_in_zone=_default_zones(),
            total_duration_min=60,
            max_hr=177,
            z4_plus_segments=[],
            avg_hr=140,
            oscillation_count=1,
            hr_correlated=False,
            min_oscillations=3,
        )
        assert t_type == 'tempo'

    def test_recovery_with_long_z4_becomes_tempo(self):
        """Recovery с длинным Z4+ сегментом → tempo"""
        t_type, _ = classify_training(
            var_count=0,
            time_in_zone=_default_zones(30),
            total_duration_min=25,
            max_hr=177,
            z4_plus_segments=[{'duration': 10, 'avg_hr': 160}],
            avg_hr=120,
        )
        assert t_type == 'tempo'

    def test_easy_stable_low_hr(self):
        """avg_hr <= 0.75*max_hr, z2 >= 60%, нет длинных Z4 → easy"""
        zones = _no_z4_zones(40)
        t_type, _ = classify_training(
            var_count=0,
            time_in_zone=zones,
            total_duration_min=40,
            max_hr=177,
            z4_plus_segments=[],
            avg_hr=130,
        )
        assert t_type == 'easy'

    def test_easy_not_with_long_z4_segment(self):
        """easy с длинным Z4+ сегментом → tempo"""
        zones = _no_z4_zones(40)
        t_type, _ = classify_training(
            var_count=0,
            time_in_zone=zones,
            total_duration_min=40,
            max_hr=177,
            z4_plus_segments=[{'duration': 5, 'avg_hr': 165}],
            avg_hr=130,
        )
        assert t_type == 'tempo'

    def test_easy_low_z2_becomes_tempo(self):
        """easy с z2 < 60% → tempo (fallback)"""
        zones = {1: 5, 2: 30, 3: 40, 4: 20, 5: 5}
        t_type, _ = classify_training(
            var_count=0,
            time_in_zone=zones,
            total_duration_min=100,
            max_hr=177,
            z4_plus_segments=[],
            avg_hr=130,
        )
        assert t_type == 'tempo'

    def test_easy_hr_above_recovery_threshold(self):
        """easy: avg_hr в [0.70, 0.75] → easy (not recovery)"""
        zones = _no_z4_zones(40)
        t_type, _ = classify_training(
            var_count=0,
            time_in_zone=zones,
            total_duration_min=40,
            max_hr=177,
            z4_plus_segments=[],
            avg_hr=130,
        )
        assert t_type == 'easy'

    def test_recovery_avg_hr_threshold(self):
        """recovery: avg_hr_pct <= 0.70 → recovery (not easy)"""
        zones = _no_z4_zones(30)
        t_type, _ = classify_training(
            var_count=0,
            time_in_zone=zones,
            total_duration_min=25,
            max_hr=177,
            z4_plus_segments=[],
            avg_hr=120,
        )
        assert t_type == 'recovery'
