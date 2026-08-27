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
    if max_hr <= 0:
        return 1
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


_ZONE_MAX_PCT = {
    1: HR_ZONE_1_MAX_PCT,
    2: HR_ZONE_2_MAX_PCT,
    3: HR_ZONE_3_MAX_PCT,
    4: HR_ZONE_4_MAX_PCT,
}


def zone_ceiling_hr(zone: int, max_hr: int) -> int | None:
    """
    Потолок зоны в уд/мин — обратная к get_zone: floor, чтобы значение
    гарантированно оставалось внутри зоны.
    Zone ceiling in bpm — inverse of get_zone: floored so the value stays in-zone.
    Z5 и невалидные входы → None (у Z5 потолок — сам max_hr).
    """
    if max_hr <= 0:
        return None
    pct = _ZONE_MAX_PCT.get(zone)
    if pct is None:
        return None
    return int(max_hr * pct)
