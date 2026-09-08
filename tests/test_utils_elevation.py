# Набор/спуск высоты с гистерезисом (#253, 08.09.2026)

from src.analysis.utils import calc_elevation
from src.config.constants import ELEV_HYSTERESIS_M


def test_noise_around_plateau_gives_zero_with_hysteresis_but_not_naive():
    """Шум барометра ±0.5 м на ровном: гистерезис 2 м → 0/0; наивная сумма (порог 0) — > 0."""
    alts = [100 + (0.5 if i % 2 else -0.5) for i in range(200)]
    assert calc_elevation(alts) == (0, 0)
    gain, loss = calc_elevation(alts, hysteresis_m=0)
    assert gain > 50 and loss > 50


def test_step_climb_counted_once():
    """Подъём 10 м ступеньками по 1 м с дрожанием ±0.4 → 10 набора, спуск 0; обратно — 0/10."""
    up = [100 + i + (0.4 if i % 2 else 0.0) for i in range(11)]
    assert calc_elevation(up) == (10, 0)
    down = list(reversed(up))
    assert calc_elevation(down) == (0, 10)
    assert calc_elevation(up + down) == (10, 10)


def test_hill_and_valley_reversals():
    """Холм 100→130→100 и долина →80→100: набор 50, спуск 50 при любом пороге ≤ 2."""
    alts = [100, 110, 120, 130, 120, 110, 100, 90, 80, 90, 100]
    assert calc_elevation(alts) == (50, 50)
    assert calc_elevation(alts, hysteresis_m=0) == (50, 50)


def test_none_gaps_do_not_create_delta():
    """Разрыв барометра (None) не даёт фиктивной дельты: forward-fill."""
    alts = [100, 101, None, None, 101, 102, None, 103]
    assert calc_elevation(alts) == (3, 0)
    assert calc_elevation([None, None]) == (0, 0)
    assert calc_elevation([100]) == (0, 0)


def test_small_dip_below_threshold_is_absorbed():
    """Провал на 1.5 м во время подъёма (меньше порога) не разрывает подъём и не даёт спуска."""
    alts = [100, 102, 104, 102.5, 104, 106, 108]
    assert ELEV_HYSTERESIS_M == 2.0
    assert calc_elevation(alts) == (8, 0)
