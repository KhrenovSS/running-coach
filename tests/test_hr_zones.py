# Тесты пульсовых зон (HR zones tests)
from src.analysis.hr_zones import get_zone, get_band, zone_ceiling_hr


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


class TestGetZoneEdgeCases:
    def test_max_hr_zero_returns_zone1(self):
        """>max_hr=0 → защита ZeroDivisionError → Z1"""
        assert get_zone(100, 0) == 1
        assert get_zone(0, 0) == 1
        assert get_zone(200, 0) == 1

    def test_hr_none_does_not_crash(self):
        """None HR не должен падать"""
        assert get_zone(0, 177) == 1

    def test_hr_equals_max_hr(self):
        """HR == max_hr → Z5"""
        assert get_zone(177, 177) == 5

    def test_hr_above_max_hr(self):
        """HR > max_hr → Z5"""
        assert get_zone(180, 177) == 5

    def test_all_zones_for_given_max_hr(self):
        """Проверить все 5 зон для max_hr=200"""
        assert get_zone(139, 200) == 1  # 69.5% ≤ 70% → Z1
        assert get_zone(141, 200) == 2  # 70.5% > 70%, ≤ 80% → Z2
        assert get_zone(174, 200) == 3  # 87% ≤ 87% → Z3
        assert get_zone(175, 200) == 4  # 87.5% > 87%, ≤ 93% → Z4
        assert get_zone(187, 200) == 5  # 93.5% > 93% → Z5


class TestZoneCeilingHr:
    def test_ceilings_for_max_hr_177(self):
        """Табличные потолки зон для max_hr=177 (floor: значение внутри зоны)."""
        assert zone_ceiling_hr(1, 177) == 123  # 177·0.70 = 123.9
        assert zone_ceiling_hr(2, 177) == 141  # 177·0.80 = 141.6
        assert zone_ceiling_hr(3, 177) == 153  # 177·0.87 = 153.99
        assert zone_ceiling_hr(4, 177) == 164  # 177·0.93 = 164.61

    def test_zone5_has_no_ceiling(self):
        """Z5 — потолка нет (сам max_hr)."""
        assert zone_ceiling_hr(5, 177) is None

    def test_invalid_inputs(self):
        """Невалидные max_hr/зона → None, не исключение."""
        assert zone_ceiling_hr(2, 0) is None
        assert zone_ceiling_hr(2, -5) is None
        assert zone_ceiling_hr(0, 177) is None

    def test_roundtrip_ceiling_stays_in_zone(self):
        """Обратность: get_zone(потолок зоны) == сама зона."""
        for max_hr in (160, 177, 200):
            for zone in (1, 2, 3, 4):
                assert get_zone(zone_ceiling_hr(zone, max_hr), max_hr) == zone
