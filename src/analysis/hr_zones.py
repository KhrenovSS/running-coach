# Пульсовые зоны: расчёт зоны и полосы по пульсу (Heart rate zones: zone and band calculation)
#
# Две лестницы (F4/M3.1, METRICS_GUIDE §8): при валидном LTHR — зоны от порога
# (Фицджеральд: Z1 ≤81%, Z2 ≤89%, Z3 ≤100%, Z4 ≤105% LTHR); без LTHR — fallback
# %max_hr (историческая). Все потребители передают lthr опционально: None → fallback.
# (Two ladders: LTHR-anchored when available, %max_hr fallback otherwise.)

from src.config.constants import (
    HR_ZONE_1_MAX_PCT,
    HR_ZONE_2_MAX_PCT,
    HR_ZONE_3_MAX_PCT,
    HR_ZONE_4_MAX_PCT,
    LTHR_SANITY_MIN,
    LTHR_ZONE_1_MAX_PCT,
    LTHR_ZONE_2_MAX_PCT,
    LTHR_ZONE_3_MAX_PCT,
    LTHR_ZONE_4_MAX_PCT,
)

_MAX_HR_PCTS = (HR_ZONE_1_MAX_PCT, HR_ZONE_2_MAX_PCT,
                HR_ZONE_3_MAX_PCT, HR_ZONE_4_MAX_PCT)
_LTHR_PCTS = (LTHR_ZONE_1_MAX_PCT, LTHR_ZONE_2_MAX_PCT,
              LTHR_ZONE_3_MAX_PCT, LTHR_ZONE_4_MAX_PCT)


def lthr_valid(max_hr: int, lthr: int | None) -> bool:
    """Санити LTHR: в физиологичном диапазоне и ниже max_hr (иначе fallback)."""
    return lthr is not None and max_hr > 0 and LTHR_SANITY_MIN < lthr < max_hr


def zone_bounds(max_hr: int, lthr: int | None = None) -> tuple[float, float, float, float]:
    """Потолки Z1–Z4 в уд/мин (Z5 — выше последнего). LTHR-лестница при валидном lthr.
    (Z1–Z4 ceilings in bpm; the LTHR ladder when lthr is valid, %max_hr otherwise.)"""
    if lthr_valid(max_hr, lthr):
        return tuple(lthr * p for p in _LTHR_PCTS)
    return tuple(max_hr * p for p in _MAX_HR_PCTS)


def get_zone(hr: int, max_hr: int, lthr: int | None = None) -> int:
    """
    Определить пульсовую зону (1-5) по пульсу
    Determine HR zone (1-5) from heart rate
    """
    if max_hr <= 0:
        return 1
    for zone, ceil in enumerate(zone_bounds(max_hr, lthr), 1):
        if hr <= ceil:
            return zone
    return 5


def get_band(hr: int, max_hr: int, lthr: int | None = None) -> str:
    """
    Определить полосу нагрузки: easy / moderate / hard
    Determine load band: easy / moderate / hard
    """
    zone = get_zone(hr, max_hr, lthr)
    return 'easy' if zone <= 2 else 'moderate' if zone == 3 else 'hard'


def zone_ceiling_hr(zone: int, max_hr: int, lthr: int | None = None) -> int | None:
    """
    Потолок зоны в уд/мин — обратная к get_zone: floor, чтобы значение
    гарантированно оставалось внутри зоны.
    Zone ceiling in bpm — inverse of get_zone: floored so the value stays in-zone.
    Z5 и невалидные входы → None (у Z5 потолок — сам max_hr).
    """
    if max_hr <= 0:
        return None
    bounds = zone_bounds(max_hr, lthr)
    if not 1 <= zone <= len(bounds):
        return None
    return int(bounds[zone - 1])
