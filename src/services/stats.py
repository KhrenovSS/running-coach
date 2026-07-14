# Вспомогательные функции для статистики и отображения (Statistics and display helpers)

from typing import Any

from src.config.constants import (
    HR_ZONE_1_MAX_PCT,
    HR_ZONE_2_MAX_PCT,
    HR_ZONE_3_MAX_PCT,
    HR_ZONE_4_MAX_PCT,
)

# Названия месяцев (Month names in Russian)
MONTHS_RU: list[str] = ['', 'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
                         'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']
MONTHS_RU_SHORT: list[str] = ['', 'Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн',
                              'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек']


def fmt_duration(minutes: float | None) -> str:
    if not minutes:
        return ""
    m = int(minutes)
    if m >= 60:
        h = m // 60
        rest = m % 60
        return f"{h}ч {rest}мин" if rest else f"{h}ч"
    return f"{m}мин"


def calc_stats(sessions: list[Any]) -> dict[str, Any]:
    total_km = 0.0
    total_duration_min = 0.0
    zone_min: dict[int, float] = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0}
    type_count: dict[str, int] = {}
    for s in sessions:
        total_km += s.total_distance_km or 0
        total_duration_min += s.duration_minutes or 0
        t = s.training_type
        type_count[t] = type_count.get(t, 0) + 1
        for seg in (s.segments_json or []):
            z = seg.get('zone')
            d = seg.get('duration_min', 0)
            if z and d:
                zone_min[z] = zone_min.get(z, 0) + d
    return {
        'total_km': round(total_km, 1),
        'total_dur': fmt_duration(total_duration_min),
        'total_min': round(total_duration_min),
        'zone_min': zone_min,
        'type_count': type_count,
    }


def zone_ranges(max_hr: int) -> dict[int, str]:
    r: dict[int, str] = {}
    r[1] = f"≤{round(HR_ZONE_1_MAX_PCT * max_hr)}"
    r[2] = f"{round(HR_ZONE_1_MAX_PCT * max_hr) + 1}–{round(HR_ZONE_2_MAX_PCT * max_hr)}"
    r[3] = f"{round(HR_ZONE_2_MAX_PCT * max_hr) + 1}–{round(HR_ZONE_3_MAX_PCT * max_hr)}"
    r[4] = f"{round(HR_ZONE_3_MAX_PCT * max_hr) + 1}–{round(HR_ZONE_4_MAX_PCT * max_hr)}"
    r[5] = f"{round(HR_ZONE_4_MAX_PCT * max_hr) + 1}–{max_hr}"
    return r


def get_zone_bars_data(zone_min: dict[int, float], total_min: float, max_hr: int) -> list[dict[str, Any]]:
    if not total_min:
        return []
    colors: dict[int, str] = {1: '#e8f5e9', 2: '#c8e6c9', 3: '#fff3e0', 4: '#ffccbc', 5: '#ffcdd2'}
    zr = zone_ranges(max_hr)
    zones: list[dict[str, Any]] = []
    for z in range(1, 6):
        val = zone_min.get(z, 0)
        pct = round(val / total_min * 100) if total_min else 0
        zones.append({
            'label': zr[z],
            'pct': pct,
            'color': colors[z],
            'duration': fmt_duration(val),
            'zone': z,
        })
    return zones


TRAINING_TYPE_LABELS: dict[str, str] = {
    'interval': 'Интервальная',
    'tempo': 'Темповая',
    'long': 'Длинная',
    'recovery': 'Восстановительная',
}


def get_nav_data(all_sessions: list[Any], sel_year: int | None, sel_month: int | None) -> tuple[dict[int, list[int]], int | None, int | None, str]:
    years: dict[int, set[int]] = {}
    for s in all_sessions:
        if s.begin_ts is None:
            continue
        y, m = s.begin_ts.year, s.begin_ts.month
        if y not in years:
            years[y] = set()
        years[y].add(m)

    if not years:
        return {}, None, None, ""

    sorted_years = sorted(years.keys(), reverse=True)

    if sel_year is None or sel_year not in years:
        sel_year = sorted_years[0]
    if sel_month is None or sel_month not in years[sel_year]:
        sel_month = max(years[sel_year])

    if sel_year and sel_month:
        title = f'Тренировки за {MONTHS_RU[sel_month]} {sel_year}'
    elif sel_year:
        title = f'Тренировки за {sel_year} год'
    else:
        title = 'Все тренировки'

    years_data: dict[int, list[int]] = {y: sorted(years[y]) for y in sorted_years}
    return years_data, sel_year, sel_month, title
