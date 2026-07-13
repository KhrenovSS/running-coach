# Пульсовые зоны: расчёт зоны и полосы по пульсу (Heart rate zones: zone and band calculation)


def get_zone(hr: int, max_hr: int) -> int:
    """
    Определить пульсовую зону (1-5) по пульсу и максимальному пульсу
    Determine HR zone (1-5) from heart rate and max HR
    """
    pct = hr / max_hr * 100
    if pct <= 70:
        return 1
    elif pct <= 80:
        return 2
    elif pct <= 87:
        return 3
    elif pct <= 93:
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
