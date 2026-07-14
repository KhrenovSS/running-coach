# Пульсовые зоны: расчёт зоны и полосы по пульсу (Heart rate zones: zone and band calculation)

from src.config.constants import (
    HR_ZONE_1_MAX_PCT,
    HR_ZONE_2_MAX_PCT,
    HR_ZONE_3_MAX_PCT,
    HR_ZONE_4_MAX_PCT,
)


def get_zone(hr: int, max_hr: int) -> int:
    """
    Определить пульсовую зону (1-5) по пульсу и максимальному пульсу
    Determine HR zone (1-5) from heart rate and max HR
    """
    pct = hr / max_hr * 100
    if pct <= HR_ZONE_1_MAX_PCT * 100:
        return 1
    elif pct <= HR_ZONE_2_MAX_PCT * 100:
        return 2
    elif pct <= HR_ZONE_3_MAX_PCT * 100:
        return 3
    elif pct <= HR_ZONE_4_MAX_PCT * 100:
        return 4
    else:
        return 5


def get_band(hr: int, max_hr: int) -> str:
    """
    Определить полосу нагрузки: easy / moderate / hard
    Determine load band: easy / moderate / hard
    """
    zone = get_zone(hr, max_hr)
    return 'easy' if zone <= 2 else 'moderate' if zone == 3 else 'hard'
