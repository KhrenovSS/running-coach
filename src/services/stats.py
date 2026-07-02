# Вспомогательные функции для статистики и отображения (Statistics and display helpers)

# Цвета для пульсовых зон (Heart rate zone colors)
ZONE_COLORS = ['', '#e8f5e9', '#c8e6c9', '#fff3e0', '#ffccbc', '#ffcdd2']

# Названия месяцев (Month names in Russian)
MONTHS_RU = ['', 'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
             'Июль', 'Август', 'Сентябрь', 'Окторябрь', 'Ноябрь', 'Декабрь']
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
    r[1] = f"≤{round(0.70 * max_hr)}"
    r[2] = f"{round(0.70 * max_hr) + 1}–{round(0.80 * max_hr)}"
    r[3] = f"{round(0.80 * max_hr) + 1}–{round(0.87 * max_hr)}"
    r[4] = f"{round(0.87 * max_hr) + 1}–{round(0.93 * max_hr)}"
    r[5] = f"{round(0.93 * max_hr) + 1}–{max_hr}"
    return r


# Рендер HTML-полосок пульсовых зон (Render zone bar HTML)
def render_zone_bars(zone_min, total_min, max_hr):
    if not total_min:
        return ""
    bars = ""
    colors = {1: '#e8f5e9', 2: '#c8e6c9', 3: '#fff3e0', 4: '#ffccbc', 5: '#ffcdd2'}
    zr = zone_ranges(max_hr)
    for z in range(1, 6):
        val = zone_min.get(z, 0)
        pct = round(val / total_min * 100) if total_min else 0
        bars += f"<div style='display:flex;align-items:center;gap:6px;margin:3px 0;white-space:nowrap'><div style='width:90px;font-size:12px'>{zr[z]} уд/мин</div><div style='height:20px;width:{pct}%;background:{colors[z]};border-radius:4px;min-width:4px'></div><div style='font-size:12px;color:#666;margin-left:4px'>{fmt_duration(val)}</div></div>"
    return bars


# Рендер строки с количеством тренировок по типам (Render training type count row)
def render_type_row(type_count):
    labels = {'interval': 'Интервальная', 'tempo': 'Темповая', 'long': 'Длинная', 'recovery': 'Восстановительная'}
    parts = []
    for key, label in labels.items():
        c = type_count.get(key, 0)
        if c:
            parts.append(f"{label}: {c}")
    return ", ".join(parts) if parts else "—"


# Построить навигацию по годам/месяцам (Build year/month navigation)
def build_nav_html(all_sessions, sel_year, sel_month):
    # Собираем уникальные (год, месяц) из всех тренировок
    years = {}
    for s in all_sessions:
        if s.begin_ts is None:
            continue
        y, m = s.begin_ts.year, s.begin_ts.month
        if y not in years:
            years[y] = set()
        years[y].add(m)

    if not years:
        return ""

    sorted_years = sorted(years.keys(), reverse=True)

    # Если год/месяц не указаны — выбираем последний месяц с данными
    if sel_year is None or sel_year not in years:
        sel_year = sorted_years[0]
    if sel_month is None or sel_month not in years[sel_year]:
        sel_month = max(years[sel_year])

    html = '<div class="ym-nav">'

    # Строка годов (Year row)
    html += '<div class="year-row">'
    for y in sorted_years:
        cls = 'ym-pill active-year' if y == sel_year else 'ym-pill'
        html += f'<a href="/?year={y}" class="{cls}">{y}</a>'
    html += '</div>'

    # Строка месяцев (Month row)
    html += '<div class="month-row">'
    for m in sorted(years[sel_year]):
        cls = 'ym-pill active-month' if m == sel_month else 'ym-pill'
        html += f'<a href="/?year={sel_year}&month={m}" class="{cls}">{MONTHS_RU_SHORT[m]}</a>'
    html += '</div>'

    # Заголовок (Title)
    if sel_year and sel_month:
        title = f'Тренировки за {MONTHS_RU[sel_month]} {sel_year}'
    elif sel_year:
        title = f'Тренировки за {sel_year} год'
    else:
        title = 'Все тренировки'
    html += f'<div class="ym-title">{title}</div>'
    html += '</div>'

    return html, sel_year, sel_month
