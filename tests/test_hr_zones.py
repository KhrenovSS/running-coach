# Тесты пульсовых зон (HR zones tests)
from src.analysis.hr_zones import get_zone, get_band


class TestGetZone:
    def test_zone1_low_intensity(self):
        """Z1: пульс <= 70% от max_hr"""
        assert get_zone(120, 177) == 1
        assert get_zone(100, 177) == 1
        assert get_zone(1, 177) == 1

    def test_zone2_moderate(self):
        """Z2: пульс 71-80% от max_hr"""
        assert get_zone(124, 177) == 2
        assert get_zone(141, 177) == 2

    def test_zone3_tempo(self):
        """Z3: пульс 81-87% от max_hr"""
        assert get_zone(142, 177) == 3
        assert get_zone(153, 177) == 3  # 153/177 = 86.4% → Z3

    def test_zone4_threshold(self):
        """Z4: пульс 88-93% от max_hr"""
        assert get_zone(155, 177) == 4
        assert get_zone(164, 177) == 4

    def test_zone5_max(self):
        """Z5: пульс > 93% от max_hr"""
        assert get_zone(165, 177) == 5
        assert get_zone(177, 177) == 5
        assert get_zone(170, 177) == 5

    def test_boundary_70_percent(self):
        """Граница 70%: ровно 70% → Z1, 70.1% → Z2"""
        assert get_zone(123, 177) == 1  # 123/177 = 69.5%
        assert get_zone(124, 177) == 2  # 124/177 = 70.1%


class TestGetBand:
    def test_band_easy(self):
        """easy: Z1-Z2"""
        assert get_band(110, 177) == 'easy'
        assert get_band(130, 177) == 'easy'

    def test_band_moderate(self):
        """moderate: Z3"""
        assert get_band(145, 177) == 'moderate'

    def test_band_hard(self):
        """hard: Z4-Z5"""
        assert get_band(160, 177) == 'hard'
        assert get_band(175, 177) == 'hard'
