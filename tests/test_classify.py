# Тесты классификации тренировок (Training classification tests)
from src.analysis.classify import classify_training


def _default_zones(total_min=60):
    """Зоны по умолчанию: 50% в Z2, остальное распределено"""
    return {1: total_min * 0.1, 2: total_min * 0.5, 3: total_min * 0.25,
            4: total_min * 0.1, 5: total_min * 0.05}


class TestClassifyTraining:
    def test_interval_by_var_count(self):
        """var_count >= 3 → interval"""
        t_type, seg_count = classify_training(
            var_count=3,
            time_in_zone=_default_zones(),
            total_duration_min=60,
            max_hr=177,
            z4_plus_segments=[],
            avg_hr=140,
        )
        assert t_type == 'interval'

    def test_interval_by_oscillation_count(self):
        """oscillation_count >= min_oscillations → interval"""
        t_type, _ = classify_training(
            var_count=0,
            time_in_zone=_default_zones(),
            total_duration_min=60,
            max_hr=177,
            z4_plus_segments=[],
            avg_hr=140,
            oscillation_count=4,
            min_oscillations=3,
        )
        assert t_type == 'interval'

    def test_interval_by_oscillations_and_hr_correlated(self):
        """oscillation_count >= 2 AND hr_correlated → interval"""
        t_type, _ = classify_training(
            var_count=0,
            time_in_zone=_default_zones(),
            total_duration_min=60,
            max_hr=177,
            z4_plus_segments=[],
            avg_hr=140,
            oscillation_count=2,
            hr_correlated=True,
            min_oscillations=3,
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
        """Длительность >= 90 мин, Z2 >= 50%, нет Z4+ сегментов → long"""
        zones = {1: 10, 2: 60, 3: 15, 4: 10, 5: 5}
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
        """avg_hr <= 0.75*max_hr, нет Z4+ сегментов → recovery"""
        t_type, _ = classify_training(
            var_count=0,
            time_in_zone=_default_zones(30),
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
            avg_hr=140,
            oscillation_count=6,
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
