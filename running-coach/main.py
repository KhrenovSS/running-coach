# Импорт FastAPI и компонентов (FastAPI and component imports)
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from src.models import SessionLocal, TrainingSession, WeightMeasurement, get_settings
from src.parsers.tcx_parser import parse_tcx, weather_icon
import shutil
import os
import tempfile

# Создание экземпляра FastAPI (Create FastAPI app instance)
app = FastAPI()
os.makedirs("uploads", exist_ok=True)

# Словарь типов тренировок на русском (Training type labels in Russian)
TRAINING_TYPES_RU = {
    'interval': 'Интервальная',
    'long': 'Длинная',
    'recovery': 'Восстановительная',
    'tempo': 'Темповая',
}

# Цвета для пульсовых зон (Heart rate zone colors)
ZONE_COLORS = ['', '#e8f5e9', '#c8e6c9', '#fff3e0', '#ffccbc', '#ffcdd2']

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

# Основная функция рендеринга главной страницы (Main page render function)
def render_page():
    db = SessionLocal()
    all_sessions = db.query(TrainingSession).order_by(TrainingSession.begin_ts.desc()).all()
    settings = get_settings()
    weight_measurements = db.query(WeightMeasurement).order_by(WeightMeasurement.measured_at).all()
    db.close()

    import json
    weight_json = json.dumps([{
        'date': wm.measured_at.strftime('%Y-%m-%d'),
        'weight': wm.weight_kg,
    } for wm in weight_measurements])

    latest = all_sessions[0].begin_ts if all_sessions else None
    week_stats = month_stats = None
    if latest:
        from datetime import timedelta
        week_cut = latest - timedelta(days=7)
        month_cut = latest - timedelta(days=30)
        week_sessions = [s for s in all_sessions if s.begin_ts >= week_cut]
        month_sessions = [s for s in all_sessions if s.begin_ts >= month_cut]
        week_stats = calc_stats(week_sessions)
        month_stats = calc_stats(month_sessions)

    rows = ""
    for s in all_sessions[:20]:
        t = s.begin_ts.strftime("%d.%m.%Y %H:%M") if s.begin_ts else ""
        dur = fmt_duration(s.duration_minutes)
        if s.weather_code is not None and s.avg_temperature is not None:
            temp_str = f"{weather_icon(s.weather_code)} {s.avg_temperature}°"
        elif s.avg_temperature is not None:
            temp_str = f"{s.avg_temperature}°"
        else:
            temp_str = "—"
        elev_str = f"↑{s.elevation_gain}" if s.elevation_gain is not None else ""
        warn = "⚠️" if s.suspect_flags else ""
        rows += f"<tr onclick=\"window.location='/session/{s.id}'\" style='cursor:pointer'>"
        rows += f"<td>{warn} {t}</td><td>{dur}</td><td>{s.total_distance_km:.2f}</td><td>{s.avg_heart_rate}</td>"
        rows += f"<td>{TRAINING_TYPES_RU.get(s.training_type, s.training_type)}</td><td>{s.segments_count}</td><td>{temp_str}</td><td>{elev_str}</td></tr>"

    week_bars = render_zone_bars(week_stats['zone_min'], week_stats['total_min'], settings.max_hr) if week_stats else ""
    month_bars = render_zone_bars(month_stats['zone_min'], month_stats['total_min'], settings.max_hr) if month_stats else ""
    week_types = render_type_row(week_stats['type_count']) if week_stats else ""
    month_types = render_type_row(month_stats['type_count']) if month_stats else ""

    return MAIN_HTML.format(
        rows=rows, max_hr=settings.max_hr, weight=settings.weight,
        week_km=week_stats['total_km'] if week_stats else 0,
        week_dur=week_stats['total_dur'] if week_stats else "",
        week_bars=week_bars,
        week_types=week_types,
        month_km=month_stats['total_km'] if month_stats else 0,
        month_dur=month_stats['total_dur'] if month_stats else "",
        month_bars=month_bars,
        month_types=month_types,
        weight_json=weight_json,
    )


MAIN_HTML = '''
<!DOCTYPE html>
<html lang='ru'>
<head>
    <meta charset='UTF-8'>
    <title>AI Running Coach</title>
    <script src='https://cdn.jsdelivr.net/npm/chart.js@4'></script>
    <style>
        body {{ font-family: sans-serif; max-width: 98%; margin: 20px 30px; line-height: 1.6; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
        th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #4CAF50; color: white; }}
        tr:hover {{ background: #f1f1f1; }}
        h2, h3 {{ color: #333; }}
        .settings {{ background: #e8f5e9; padding: 15px; border-radius: 8px; margin-bottom: 20px; display: flex; gap: 20px; align-items: center; flex-wrap: wrap; }}
        .settings a {{ margin-left: auto; }}
        .btn {{ display: inline-block; padding: 6px 14px; background: #4CAF50; color: white; text-decoration: none; border-radius: 5px; font-size: 14px; border: none; cursor: pointer; }}
        .btn:hover {{ background: #45a049; }}
        input[type=number] {{ width: 70px; padding: 4px; }}
        .stats-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin: 15px 0; }}
        .stats-card {{ border: 1px solid #ddd; border-radius: 8px; padding: 15px; background: #fafafa; }}
        .stats-card h4 {{ margin: 0 0 8px 0; color: #4CAF50; }}
        .stats-summary {{ display: flex; gap: 15px; flex-wrap: wrap; font-size: 14px; margin-bottom: 10px; }}
        .stats-summary span {{ background: #e8f5e9; padding: 4px 10px; border-radius: 4px; }}
        .overlay {{ display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(255,255,255,0.9); z-index: 999; justify-content: center; align-items: center; flex-direction: column; }}
        .overlay.active {{ display: flex; }}
        .spinner {{ border: 4px solid #e0e0e0; border-top: 4px solid #4CAF50; border-radius: 50%; width: 40px; height: 40px; animation: spin 0.8s linear infinite; }}
        @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
    </style>
</head>
<body>
    <div class='overlay' id='uploadOverlay'>
        <div class='spinner'></div>
        <p style='margin-top:16px;font-size:18px;color:#333;'>Обработка файлов…</p>
    </div>

    <h2>🏃 AI Running Coach</h2>

    <div class='settings'>
        <span><b>ЧССмакс:</b> {max_hr} уд/мин</span>
        <span id='weightToggle' style='cursor:pointer' onclick='toggleWeightChart()'><b>Вес:</b> {weight} кг ▾</span>
        <input type='file' name='files' accept='.tcx' multiple id='fileInput' style='display:none'>
        <button type='button' class='btn' onclick='document.getElementById("fileInput").click()' style='margin-left:auto'>&#128206; Загрузить TCX</button>
        <a href='/settings' class='btn'>⚙️ Настройки</a>
    </div>
    <div id='weightChartContainer' style='display:none; margin-bottom:15px'>
        <div class='stats-card'>
            <h4>📉 Динамика веса</h4>
            <div style='max-height:300px; overflow-y:auto;'>
                <table style='margin-top:5px'>
                    <thead><tr><th>Дата</th><th>Вес, кг</th></tr></thead>
                    <tbody id='weightTableBody'></tbody>
                </table>
            </div>
            <canvas id='weightChart' height='100' style='margin-top:10px'></canvas>
        </div>
    </div>
    <script>
    document.getElementById('fileInput').addEventListener('change', function() {{
        if (!this.files.length) return;
        document.getElementById('uploadOverlay').classList.add('active');
        const fd = new FormData();
        for (const f of this.files) fd.append('files', f);
        fetch('/upload', {{ method: 'POST', body: fd }})
            .then(() => window.location.href = '/')
            .catch(() => window.location.href = '/');
    }});
    </script>

    <div class='stats-grid'>
        <div class='stats-card'>
            <h4>Неделя (7 дней)</h4>
            <div class='stats-summary'>
                <span>📏 {week_km} км</span>
                <span>⏱ {week_dur}</span>
            </div>
            <div style='font-size:12px;color:#888;margin-bottom:4px'>Пульс</div>
            <div>{week_bars}</div>
            <div style='font-size:13px;color:#555;margin-top:6px'>{week_types}</div>
        </div>
        <div class='stats-card'>
            <h4>Месяц (30 дней)</h4>
            <div class='stats-summary'>
                <span>📏 {month_km} км</span>
                <span>⏱ {month_dur}</span>
            </div>
            <div style='font-size:12px;color:#888;margin-bottom:4px'>Пульс</div>
            <div>{month_bars}</div>
            <div style='font-size:13px;color:#555;margin-top:6px'>{month_types}</div>
        </div>
    </div>

    <script>
    const weightData = {weight_json};
    let weightChart = null;

    function toggleWeightChart() {{
        const container = document.getElementById('weightChartContainer');
        const toggle = document.getElementById('weightToggle');
        if (container.style.display === 'none') {{
            container.style.display = 'block';
            toggle.innerHTML = '<b>Вес:</b> {weight} кг ▴';
            renderWeightChart();
            renderWeightTable();
        }} else {{
            container.style.display = 'none';
            toggle.innerHTML = '<b>Вес:</b> {weight} кг ▾';
        }}
    }}

    function renderWeightTable() {{
        const tbody = document.getElementById('weightTableBody');
        tbody.innerHTML = weightData.map(d =>
            `<tr><td>${{d.date}}</td><td>${{d.weight}}</td></tr>`
        ).join('');
    }}

    function renderWeightChart() {{
        if (weightData.length < 2) return;
        if (weightChart) {{
            weightChart.destroy();
            weightChart = null;
        }}
        weightChart = new Chart(document.getElementById('weightChart'), {{
            type: 'line',
            data: {{
                labels: weightData.map(d => d.date),
                datasets: [{{
                    label: 'Вес (кг)',
                    data: weightData.map(d => d.weight),
                    borderColor: '#4CAF50',
                    backgroundColor: 'transparent',
                    tension: 0.4,
                    pointRadius: 5,
                    pointBackgroundColor: '#4CAF50',
                    pointBorderColor: '#fff',
                    pointBorderWidth: 2,
                }}]
            }},
            options: {{
                responsive: true,
                scales: {{
                    x: {{ title: {{ display: true, text: 'Дата' }} }},
                    y: {{ title: {{ display: true, text: 'кг' }}, beginAtZero: false }},
                }},
                plugins: {{ legend: {{ display: false }} }}
            }}
        }});
    }}
    </script>

    <h3>Последние 20 тренировок</h3>
    <table>
            <thead>
                <tr><th>Дата</th><th>Длит.</th><th>Дист., км</th><th>Пульс, bpm</th><th>Тип</th><th>Отрезки</th><th>Погода</th><th>Набор</th></tr>
            </thead>
        <tbody>
            {rows}
        </tbody>
    </table>
</body>
</html>
'''

SESSION_HTML = '''
<!DOCTYPE html>
<html lang='ru'>
<head>
    <meta charset='UTF-8'>
    <title>Тренировка — AI Running Coach</title>
    <script src='https://cdn.jsdelivr.net/npm/chart.js@4'></script>
    <style>
        body {{ font-family: sans-serif; max-width: 98%; margin: 20px 30px; line-height: 1.6; }}
        .card {{ border: 1px solid #ccc; padding: 20px; border-radius: 10px; background: #f9f9f9; margin-bottom: 20px; }}
        .info {{ display: grid; grid-template-columns: 1fr 1fr 1fr 1fr 1fr; gap: 10px; margin: 15px 0; }}
        .info-item {{ background: white; padding: 10px; border-radius: 6px; text-align: center; }}
        .info-item b {{ display: block; font-size: 20px; color: #4CAF50; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
        th, td {{ padding: 8px; text-align: center; border-bottom: 1px solid #ddd; }}
        th {{ background: #4CAF50; color: white; }}
        .zone-z1 {{ background: #e8f5e9; }}
        .zone-z2 {{ background: #c8e6c9; }}
        .zone-z3 {{ background: #fff3e0; }}
        .zone-z4 {{ background: #ffccbc; }}
        .zone-z5 {{ background: #ffcdd2; }}
        .btn {{ display: inline-block; padding: 8px 20px; background: #4CAF50; color: white; text-decoration: none; border-radius: 5px; }}
        .btn:hover {{ background: #45a049; }}
        .btn-danger {{ background: #e53935; }}
        .btn-danger:hover {{ background: #c62828; }}
    </style>
</head>
<body>
    <h2>🏃 {type_ru} {suspect_badge}</h2>
    <p style='color:#666;'>{date}</p>
    {suspect_detail}

    <div class='card'>
        <div class='info'>
            <div class='info-item'><b>{dist}</b> км</div>
            <div class='info-item'><b>{dur}</b></div>
            <div class='info-item'><b>{hr}</b> bpm</div>
            <div class='info-item'><b>{temp_display}</b></div>
            <div class='info-item'><b>↑{elev_gain}</b> / ↓{elev_loss} м</div>
        </div>

        <h3>Пульс и темп</h3>
        <canvas id='hrPaceChart' height='100'></canvas>
        <script>
        const raw = {chart_json};
        if (raw.length > 0) {{
            const step = Math.max(1, Math.floor(raw.length / 200));
            const data = raw.filter((_, i) => i % step === 0);
            if (data[data.length-1] !== raw[raw.length-1]) data.push(raw[raw.length-1]);
            new Chart(document.getElementById('hrPaceChart'), {{
                type: 'line',
                data: {{
                    datasets: [{{
                        label: 'Пульс (bpm)',
                        data: data.map(d => ({{x: d.dist_km, y: d.hr}})),
                        borderColor: '#e53935',
                        backgroundColor: 'transparent',
                        yAxisID: 'y',
                        cubicInterpolationMode: 'monotone',
                        tension: 0.4,
                        pointRadius: 0,
                    }}, {{
                        label: 'Темп (мин/км)',
                        data: data.map(d => ({{x: d.dist_km, y: d.pace}})),
                        borderColor: '#1e88e5',
                        backgroundColor: 'transparent',
                        yAxisID: 'y1',
                        cubicInterpolationMode: 'monotone',
                        tension: 0.4,
                        pointRadius: 0,
                    }}]
                }},
                options: {{
                    responsive: true,
                    interaction: {{ mode: 'index', intersect: false }},
                    scales: {{
                        x: {{ type: 'linear', title: {{ display: true, text: 'Дистанция, км' }}, ticks: {{ stepSize: 0.25, autoSkip: false }} }},
                        y: {{ title: {{ display: true, text: 'Пульс, bpm' }}, position: 'left' }},
                        y1: {{ title: {{ display: true, text: 'Темп, мин/км' }}, position: 'right', reverse: true }},
                    }}
                }}
            }});
        }}
        </script>

        <h3>Детали по отрезкам</h3>
        <table>
            <thead>
                <tr><th>#</th><th>Зона</th><th>Длит.</th><th>Дист., км</th><th>Пульс, bpm</th><th>Темп</th><th>↑/↓ м</th><th>Погода</th></tr>
            </thead>
            <tbody>
                {segments_rows}
            </tbody>
        </table>
    </div>

    <div style='margin-top: 20px; display: flex; gap: 10px;'>
        <a href='/' class='btn'>&larr; Назад к списку</a>
        <form action='/session/{session_id}/delete' method='post' style='display:inline' onsubmit='return confirm("Удалить тренировку?")'>
            <button type='submit' class='btn btn-danger'>Удалить</button>
        </form>
    </div>
</body>
</html>
'''

SETTINGS_PAGE = '''
<!DOCTYPE html>
<html lang='ru'>
<head>
    <meta charset='UTF-8'>
    <title>Настройки — AI Running Coach</title>
    <style>
        body {{ font-family: sans-serif; max-width: 500px; margin: 50px auto; line-height: 1.6; padding: 0 20px; }}
        .card {{ border: 1px solid #ccc; padding: 20px; border-radius: 10px; background: #f9f9f9; }}
        label {{ display: block; margin: 15px 0 5px; }}
        input[type=number] {{ width: 120px; padding: 8px; font-size: 16px; }}
        .btn {{ display: inline-block; padding: 8px 20px; background: #4CAF50; color: white; text-decoration: none; border-radius: 5px; font-size: 16px; border: none; cursor: pointer; }}
        .btn:hover {{ background: #45a049; }}
    </style>
</head>
<body>
    <h2>⚙️ Настройки</h2>
    <div class='card'>
        <form action='/settings' method='post'>
            <label><b>Максимальный пульс (ЧССмакс):</b></label>
            <input type='number' name='max_hr' value='{max_hr}' min='100' max='250'>
            <label><b>Вес (кг):</b></label>
            <input type='number' name='weight' value='{weight}' min='30' max='250' step='0.1'>
            <hr>
            <h4>Детекция ошибочных тренировок (Bogus session detection)</h4>
            <label><b>Мин. темп (мин/км):</b> темп быстрее этого считается ошибкой</label>
            <input type='number' name='max_credible_pace' value='{max_credible_pace}' min='2.0' max='6.0' step='0.1'>
            <label><b>Макс. GPS-скачок (м):</b> прыжок координат больше этого — ошибка</label>
            <input type='number' name='max_gps_jump_m' value='{max_gps_jump_m}' min='10' max='500' step='10'>
            <label><b>Мин. пульс для быстрого темпа:</b> если пульс ниже, а темп быстрее — ошибка</label>
            <input type='number' name='min_hr_for_fast_pace' value='{min_hr_for_fast_pace}' min='90' max='180'>
            <br><br>
            <button type='submit' class='btn'>Сохранить</button>
            <a href='/' class='btn' style='background:#888;'>&larr; Назад</a>
        </form>
        <h4>Зоны пульса (при ЧССмакс = {max_hr})</h4>
        <table>
            <tr><th>Зона</th><th>% от ЧССмакс</th><th>Пульс</th></tr>
            <tr><td>Z1</td><td>50-60%</td><td>{z1}</td></tr>
            <tr><td>Z2</td><td>60-70%</td><td>{z2}</td></tr>
            <tr><td>Z3</td><td>70-80%</td><td>{z3}</td></tr>
            <tr><td>Z4</td><td>80-90%</td><td>{z4}</td></tr>
            <tr><td>Z5</td><td>90-100%</td><td>{z5}</td></tr>
        </table>
    </div>
</body>
</html>
'''


# Событие при запуске сервера: инициализация БД и миграции (Startup event: DB init and migrations)
@app.on_event("startup")
def startup():
    from src.models import init_db, engine
    from datetime import datetime
    init_db()
    try:
        from sqlalchemy import text, JSON as SA_JSON
        with engine.connect() as conn:
            # Миграция колонок training_sessions (Migrate training_sessions columns)
            cols_to_add = {
                'weather_code': 'INTEGER',
                'hr_pace_series': 'JSON',
                'suspect_flags': 'JSON',
            }
            for col, col_type in cols_to_add.items():
                try:
                    conn.execute(text(f"ALTER TABLE training_sessions ADD COLUMN {col} {col_type}"))
                except Exception:
                    pass
            # Миграция колонок user_settings (Migrate user_settings columns)
            settings_cols = {
                'max_credible_pace': 'FLOAT DEFAULT 3.0',
                'max_gps_jump_m': 'FLOAT DEFAULT 100.0',
                'min_hr_for_fast_pace': 'INTEGER DEFAULT 130',
            }
            for col, col_type in settings_cols.items():
                try:
                    conn.execute(text(f"ALTER TABLE user_settings ADD COLUMN {col} {col_type}"))
                except Exception:
                    pass
            conn.commit()
    except Exception:
        pass
    settings = get_settings()
    db = SessionLocal()
    try:
        # Ре-валидация существующих сессий без suspect_flags (Re-validate sessions missing flags)
        from src.parsers.tcx_parser import detect_suspicious
        sessions = db.query(TrainingSession).filter(TrainingSession.suspect_flags.is_(None)).all()
        for s in sessions:
            flags = detect_suspicious({
                'segments_json': s.segments_json or [],
                'avg_heart_rate': s.avg_heart_rate,
                'total_distance_km': s.total_distance_km,
                'duration_minutes': s.duration_minutes,
            }, trackpoints=None, max_hr=settings.max_hr,
               max_credible_pace=settings.max_credible_pace,
               max_gps_jump_m=settings.max_gps_jump_m,
               min_hr_for_fast_pace=settings.min_hr_for_fast_pace)
            if flags:
                s.suspect_flags = flags
                db.commit()
        # Первое измерение веса (First weight measurement)
        existing = db.query(WeightMeasurement).first()
        if not existing and settings.weight:
            wm = WeightMeasurement(weight_kg=settings.weight, measured_at=datetime.utcnow())
            db.add(wm)
            db.commit()
    except Exception:
        pass
    finally:
        db.close()


# Главная страница: список тренировок и статистика (Main page: session list and stats)
@app.get('/', response_class=HTMLResponse)
async def index():
    return render_page()


# Загрузка TCX-файлов (TCX file upload endpoint)
@app.post('/upload')
async def upload_files(files: list[UploadFile] = File(...)):
    settings = get_settings()
    db = SessionLocal()
    try:
        for file in files:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".tcx") as tmp:
                shutil.copyfileobj(file.file, tmp)
                tmp_path = tmp.name
            data = parse_tcx(tmp_path, max_hr=settings.max_hr,
                             max_credible_pace=settings.max_credible_pace,
                             max_gps_jump_m=settings.max_gps_jump_m,
                             min_hr_for_fast_pace=settings.min_hr_for_fast_pace)
            os.unlink(tmp_path)
            if data:
                exists = db.query(TrainingSession).filter(
                    TrainingSession.begin_ts == data['begin_ts']
                ).first()
                if not exists:
                    flags = data.pop('suspect_flags', None)
                    session = TrainingSession(**data)
                    if flags:
                        session.suspect_flags = flags
                    db.add(session)
                    db.commit()
    finally:
        db.close()
    return RedirectResponse(url='/', status_code=303)


# Детальный просмотр тренировки (Training session detail page)
@app.get('/session/{session_id}', response_class=HTMLResponse)
async def session_detail(session_id: int):
    db = SessionLocal()
    s = db.query(TrainingSession).filter(TrainingSession.id == session_id).first()
    db.close()
    if not s:
        return HTMLResponse("<h2>Тренировка не найдена</h2><a href='/'>Назад</a>", status_code=404)

    seg_rows = ""
    segs = s.segments_json or []
    for i, seg in enumerate(segs, 1):
        zone = seg.get('zone', '')
        cls = f"zone-z{zone}" if zone else ""
        pace = seg.get('pace') or "—"
        dur = seg.get('duration') or f"{seg['duration_min']:.0f}"
        elev = ""
        eg = seg.get('elevation_gain')
        el = seg.get('elevation_loss')
        if eg is not None and el is not None:
            elev = f"↑{eg}/↓{el}"
        temp = seg.get('temperature')
        wc = seg.get('weather_code')
        if wc is not None and temp is not None:
            temp_str = f"{weather_icon(wc)} {temp}°"
        elif temp is not None:
            temp_str = f"{temp}°"
        else:
            temp_str = "—"
        seg_rows += f"<tr class='{cls}'><td>{i}</td><td>Z{zone}</td><td>{dur}</td><td>{seg['distance_km']}</td><td>{seg['avg_hr']}</td><td>{pace}</td><td>{elev}</td><td>{temp_str}</td></tr>"

    eg_total = s.elevation_gain or 0
    el_total = s.elevation_loss or 0
    if s.weather_code is not None and s.avg_temperature is not None:
        temp_display = f"{weather_icon(s.weather_code)} {s.avg_temperature}°"
    elif s.avg_temperature is not None:
        temp_display = f"{s.avg_temperature}°"
    else:
        temp_display = "—"

    import json
    chart_json = json.dumps(s.hr_pace_series or [])

    suspect_badge = ""
    suspect_detail = ""
    if s.suspect_flags:
        flag_labels = {
            'pace_impossible': 'Нереальный темп (Impossible pace)',
            'hr_pace_mismatch': 'Пульс не соответствует темпу (HR/pace mismatch)',
            'gps_spike': 'Скачки GPS (GPS jumps)',
            'too_short': 'Слишком короткая тренировка (Too short)',
        }
        items = "".join(f"<li>{flag_labels.get(f, f)}</li>" for f in s.suspect_flags)
        suspect_badge = '<span style="background:#ff5722;color:white;padding:2px 10px;border-radius:4px;font-size:14px">⚠️ Ошибочные данные</span>'
        suspect_detail = f'<div style="background:#fff3e0;border:1px solid #ffccbc;border-radius:8px;padding:10px;margin-bottom:15px"><b>⚠️ Обнаружены проблемы:</b><ul style="margin:5px 0 0 0;padding-left:20px">{items}</ul></div>'

    return SESSION_HTML.format(
        session_id=s.id,
        suspect_badge=suspect_badge,
        suspect_detail=suspect_detail,
        type_ru=TRAINING_TYPES_RU.get(s.training_type, s.training_type),
        date=s.begin_ts.strftime("%d.%m.%Y %H:%M") if s.begin_ts else "",
        dist=f"{s.total_distance_km:.2f}",
        dur=fmt_duration(s.duration_minutes),
        hr=s.avg_heart_rate,
        temp_display=temp_display,
        elev_gain=eg_total,
        elev_loss=el_total,
        segments_rows=seg_rows,
        chart_json=chart_json,
    )


# Страница настроек (Settings page)
@app.get('/settings', response_class=HTMLResponse)
async def settings_page():
    settings = get_settings()
    m = settings.max_hr
    z1 = f"{round(m * 0.5)}-{round(m * 0.6)}"
    z2 = f"{round(m * 0.6)}-{round(m * 0.7)}"
    z3 = f"{round(m * 0.7)}-{round(m * 0.8)}"
    z4 = f"{round(m * 0.8)}-{round(m * 0.9)}"
    z5 = f"{round(m * 0.9)}-{round(m)}"
    return SETTINGS_PAGE.format(max_hr=m, weight=settings.weight, z1=z1, z2=z2, z3=z3, z4=z4, z5=z5,
                                max_credible_pace=settings.max_credible_pace,
                                max_gps_jump_m=settings.max_gps_jump_m,
                                min_hr_for_fast_pace=settings.min_hr_for_fast_pace)


# Удаление тренировки (Delete training session)
@app.post('/session/{session_id}/delete')
async def session_delete(session_id: int):
    db = SessionLocal()
    try:
        s = db.query(TrainingSession).filter(TrainingSession.id == session_id).first()
        if s:
            db.delete(s)
            db.commit()
    finally:
        db.close()
    return RedirectResponse(url='/', status_code=303)


# Сохранение настроек (Save settings)
@app.post('/settings')
async def settings_save(max_hr: int = Form(...), weight: float = Form(...),
                        max_credible_pace: float = Form(3.0),
                        max_gps_jump_m: float = Form(100.0),
                        min_hr_for_fast_pace: int = Form(130)):
    from src.models import UserSettings
    from datetime import datetime
    db = SessionLocal()
    try:
        s = db.query(UserSettings).first()
        if s:
            old_weight = s.weight
            s.max_hr = max_hr
            s.weight = weight
            s.max_credible_pace = max_credible_pace
            s.max_gps_jump_m = max_gps_jump_m
            s.min_hr_for_fast_pace = min_hr_for_fast_pace
            if weight != old_weight:
                wm = WeightMeasurement(weight_kg=weight, measured_at=datetime.utcnow())
                db.add(wm)
            db.commit()
    finally:
        db.close()
    return RedirectResponse(url='/', status_code=303)
