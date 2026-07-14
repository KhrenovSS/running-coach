# Вспомогательные функции для статистики и отображения (Statistics and display helpers)

from src.config.constants import (
    HR_ZONE_1_MAX_PCT,
    HR_ZONE_2_MAX_PCT,
    HR_ZONE_3_MAX_PCT,
    HR_ZONE_4_MAX_PCT,
)

# Названия месяцев (Month names in Russian)
MONTHS_RU = ['', 'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
             'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']
MONTHS_RU_SHORT = ['', 'Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн',
                   'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек']


# Форматирование длительности в человекочитаемый вид (Format duration for display)
def fmt_duration(minutes):
    if not minutes:
        return ""
    m = int(minutes)
    if m >= 60:
        h = m // 60
        rest = m % 60
        return f"{h}ч {rest}мин" if rest else f"{h}ч"
    return f"{m}мин"


# Расчёт статистики по списку тренировок (Calculate statistics for a list of sessions)
def calc_stats(sessions):
    total_km = 0.0
    total_duration_min = 0.0
    zone_min = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0}
    type_count = {}
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


# Расчёт диапазонов пульсовых зон (Calculate heart rate zone ranges)
def zone_ranges(max_hr):
    r = {}
    r[1] = f"≤{round(HR_ZONE_1_MAX_PCT * max_hr)}"
    r[2] = f"{round(HR_ZONE_1_MAX_PCT * max_hr) + 1}–{round(HR_ZONE_2_MAX_PCT * max_hr)}"
    r[3] = f"{round(HR_ZONE_2_MAX_PCT * max_hr) + 1}–{round(HR_ZONE_3_MAX_PCT * max_hr)}"
    r[4] = f"{round(HR_ZONE_3_MAX_PCT * max_hr) + 1}–{round(HR_ZONE_4_MAX_PCT * max_hr)}"
    r[5] = f"{round(HR_ZONE_4_MAX_PCT * max_hr) + 1}–{max_hr}"
    return r


# Данные пульсовых зон для шаблона (HR zone data for template)
def get_zone_bars_data(zone_min, total_min, max_hr):
    """Вернуть список зон с процентами и цветами (Return zone list with pct and colors)"""
    if not total_min:
        return []
    colors = {1: '#e8f5e9', 2: '#c8e6c9', 3: '#fff3e0', 4: '#ffccbc', 5: '#ffcdd2'}
    zr = zone_ranges(max_hr)
    zones = []
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


# Типы тренировок с русскими названиями (Training types with Russian labels)
TRAINING_TYPE_LABELS = {
    'interval': 'Интервальная',
    'tempo': 'Темповая',
    'long': 'Длинная',
    'recovery': 'Восстановительная',
}


# Построить навигацию по годам/месяцам (Build year/month navigation)
def get_nav_data(all_sessions, sel_year, sel_month):
    """
    Вернуть данные для навигации по годам/месяцам.
    Return navigation data for year/month navigation.

    Returns: (years_data, sel_year, sel_month, title)
    years_data = {year: sorted_months_list}
    """
    years = {}
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

    years_data = {y: sorted(years[y]) for y in sorted_years}
    return years_data, sel_year, sel_month, title
