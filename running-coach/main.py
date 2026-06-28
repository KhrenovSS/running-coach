# Импорт FastAPI и компонентов (FastAPI and component imports)
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from src.models import SessionLocal, TrainingSession, WeightMeasurement, get_settings
from src.parsers.tcx_parser import parse_tcx
from src.parsers.fit_parser import parse_fit
from src.parsers.common import weather_icon
from src.logger import get_logger
logger = get_logger("app")
import shutil
import os
import tempfile
import uuid
import threading
import time
from pathlib import Path

# Создание экземпляра FastAPI (Create FastAPI app instance)
app = FastAPI()
os.makedirs("uploads", exist_ok=True)

# Хранилище для загруженных TCX, ожидающих подтверждения (Pending uploads awaiting user confirmation)
PENDING_DIR = Path("/tmp/opencode/uploads")
PENDING_DIR.mkdir(parents=True, exist_ok=True)
_pending = {}  # temp_id -> dict with 'path', 'filename', 'data'
_sync_tasks = {}  # task_id -> dict with progress info
_sync_tasks_lock = threading.Lock()

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

# Названия месяцев (Month names in Russian)
MONTHS_RU = ['', 'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
             'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']
MONTHS_RU_SHORT = ['', 'Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн',
                   'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек']

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


# Основная функция рендеринга главной страницы (Main page render function)
def render_page(year=None, month=None):
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

    # Навигация (Navigation)
    nav_html = ""
    sel_year, sel_month = year, month
    if all_sessions:
        nav_result = build_nav_html(all_sessions, sel_year, sel_month)
        if nav_result:
            nav_html, sel_year, sel_month = nav_result

    # Фильтруем или показываем последние 20 (Filter or show latest 20)
    if sel_year and sel_month:
        filtered = [s for s in all_sessions
                    if s.begin_ts and s.begin_ts.year == sel_year and s.begin_ts.month == sel_month]
    else:
        filtered = all_sessions[:20]

    rows = ""
    for s in filtered:
        t = s.begin_ts.strftime("%d.%m.%Y %H:%M") if s.begin_ts else ""
        dur = fmt_duration(s.duration_minutes)
        eg = s.elevation_gain
        el = s.elevation_loss
        if eg is not None and el is not None:
            elev_str = f"↑{eg} / ↓{el}"
        elif eg is not None:
            elev_str = f"↑{eg}"
        elif el is not None:
            elev_str = f"↓{el}"
        else:
            elev_str = ""
        warn = ""
        if s.cleaning_log:
            warn = "✂️"
        elif s.suspect_flags:
            warn = "⚠️"
        cad_str = str(s.avg_cadence) if s.avg_cadence is not None else "—"
        cal_str = f"{s.calories}" if s.calories is not None else ""
        extra_str = cal_str
        rows += f"<tr onclick=\"window.location='/session/{s.id}'\" style='cursor:pointer'>"
        rows += f"<td>{warn} {t}</td><td>{dur}</td><td>{s.total_distance_km:.2f}</td><td>{s.avg_heart_rate}</td>"
        rows += f"<td>{TRAINING_TYPES_RU.get(s.training_type, s.training_type)}</td><td>{cad_str}</td><td>{elev_str}</td><td>{extra_str}</td></tr>"

    if not rows:
        rows = "<tr><td colspan='8' style='color:#888;padding:30px;'>Нет тренировок за выбранный период</td></tr>"

    week_bars = render_zone_bars(week_stats['zone_min'], week_stats['total_min'], settings.max_hr) if week_stats else ""
    month_bars = render_zone_bars(month_stats['zone_min'], month_stats['total_min'], settings.max_hr) if month_stats else ""
    week_types = render_type_row(week_stats['type_count']) if week_stats else ""
    month_types = render_type_row(month_stats['type_count']) if month_stats else ""

    return MAIN_HTML.format(
        rows=rows, nav_html=nav_html, max_hr=settings.max_hr, weight=settings.weight,
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
        th, td {{ padding: 10px; text-align: center; border-bottom: 1px solid #ddd; }}
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
        .sync-status {{ padding: 6px 10px; border-radius: 4px; margin-top: 6px; font-size: 13px; }}
        .sync-ok {{ background: #e8f5e9; color: #2e7d32; }}
        .sync-error {{ background: #ffebee; color: #c62828; }}
        .ym-nav {{ margin: 10px 0; }}
        .year-row, .month-row {{ display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 6px; }}
        .ym-pill {{ display: inline-block; padding: 4px 12px; border-radius: 14px; font-size: 13px;
                    text-decoration: none; color: #555; background: #f0f0f0; border: 1px solid #ddd; }}
        .ym-pill:hover {{ background: #e0e0e0; }}
        .active-year {{ background: #4CAF50; color: white; border-color: #4CAF50; }}
        .active-month {{ background: #2196F3; color: white; border-color: #2196F3; }}
        .ym-title {{ font-size: 14px; color: #666; margin-bottom: 8px; font-weight: bold; }}
    </style>
</head>
<body>
    <div class='overlay' id='uploadOverlay'>
        <div class='spinner'></div>
        <p style='margin-top:16px;font-size:18px;color:#333;'>Обработка файлов…</p>
        <p id='progressText' style='margin-top:8px;font-size:15px;color:#555;'></p>
        <div style='margin-top:12px;width:300px;background:#e0e0e0;border-radius:6px;height:10px;overflow:hidden;'>
            <div id='progressBar' style='width:0%;background:#4CAF50;border-radius:6px;height:10px;transition:width 0.3s;'></div>
        </div>
    </div>
    <div class='overlay' id='syncOverlay'>
        <div class='spinner'></div>
        <p style='margin-top:16px;font-size:18px;color:#333;' id='syncStatusText'>Синхронизация Coros…</p>
        <p id='syncProgressText' style='margin-top:8px;font-size:15px;color:#555;'></p>
        <div style='margin-top:12px;width:300px;background:#e0e0e0;border-radius:6px;height:10px;overflow:hidden;'>
            <div id='syncProgressBar' style='width:0%;background:#2196F3;border-radius:6px;height:10px;transition:width 0.3s;'></div>
        </div>
    </div>

    <h2>🏃 AI Running Coach</h2>

    <div class='settings'>
        <span><b>ЧССмакс:</b> {max_hr} уд/мин</span>
        <span id='weightToggle' style='cursor:pointer' onclick='toggleWeightChart()'><b>Вес:</b> {weight} кг ▾</span>
        <input type='file' name='files' accept='.tcx,.fit' multiple id='fileInput' style='display:none'>
        <button type='button' class='btn' onclick='document.getElementById("fileInput").click()'>&#128206; Загрузить TCX/FIT</button>
        <button type='button' class='btn' id='corosSyncBtn' style='background:#2196F3'>🔄 Coros Sync</button>
        <a href='/settings' class='btn'>⚙️ Настройки</a>
        <div id='corosSyncStatus' style='width:100%;margin-top:6px;font-size:13px;'></div>
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
    document.getElementById('fileInput').addEventListener('change', async function() {{
        if (!this.files.length) return;
        const files = Array.from(this.files);
        const total = files.length;
        let processed = 0;
        let allSaved = 0;

        const overlay = document.getElementById('uploadOverlay');
        const progressText = document.getElementById('progressText');
        const progressBar = document.getElementById('progressBar');

        overlay.classList.add('active');

        for (const file of files) {{
            const fd = new FormData();
            fd.append('files', file);
            try {{
                const resp = await fetch('/upload', {{ method: 'POST', body: fd }});
                const text = await resp.text();
                let j;
                try {{
                    j = JSON.parse(text);
                }} catch (e) {{
                    continue;
                }}
                allSaved += j.saved || 0;
            }} catch (e) {{
                // ignore network errors for individual files
            }}
            processed++;
            const pct = Math.round(processed / total * 100);
            progressText.textContent = `Обработано ${{processed}} из ${{total}} (${{pct}}%)`;
            progressBar.style.width = pct + '%';
        }}

        window.location.href = '/';
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

    <script>
    async function syncCoros() {{
        const btn = document.getElementById('corosSyncBtn');
        const statusDiv = document.getElementById('corosSyncStatus');
        const overlay = document.getElementById('syncOverlay');
        const statusText = document.getElementById('syncStatusText');
        const progressText = document.getElementById('syncProgressText');
        const progressBar = document.getElementById('syncProgressBar');
        btn.disabled = true;
        btn.textContent = '🔄 Синхронизация…';
        statusDiv.className = 'sync-status';
        statusDiv.textContent = 'Запуск...';
        overlay.classList.add('active');
        statusText.textContent = 'Подключение к Coros...';
        progressText.textContent = '';
        progressBar.style.width = '0%';
        try {{
            const resp = await fetch('/coros/sync', {{ method: 'POST' }});
            const j = await resp.json();
            if (j.status !== 'started') {{
                overlay.classList.remove('active');
                statusDiv.className = 'sync-status sync-error';
                statusDiv.textContent = '❌ ' + (j.message || 'Ошибка запуска');
                btn.disabled = false;
                btn.textContent = '🔄 Coros Sync';
                return;
            }}
            const taskId = j.task_id;
            let done = false;
            while (!done) {{
                await new Promise(r => setTimeout(r, 800));
                const sr = await fetch('/coros/sync/status/' + taskId);
                const sp = await sr.json();
                statusText.textContent = sp.message || '';
                if (sp.total > 0) {{
                    const pct = Math.round(sp.current / sp.total * 100);
                    progressText.textContent = sp.current + ' из ' + sp.total;
                    progressBar.style.width = pct + '%';
                }}
                if (sp.step === 'done' || sp.step === 'error') {{
                    done = true;
                    overlay.classList.remove('active');
                    if (sp.step === 'error') {{
                        statusDiv.className = 'sync-status sync-error';
                        statusDiv.textContent = '❌ ' + (sp.message || 'Ошибка');
                    }} else if (sp.synced > 0) {{
                        statusDiv.className = 'sync-status sync-ok';
                        statusDiv.textContent = '✅ Синхронизировано: ' + sp.synced;
                        if (sp.total_found) statusDiv.textContent += ' (найдено ' + sp.total_found + ')';
                        window.location.href = '/';
                    }} else {{
                        statusDiv.className = 'sync-status sync-ok';
                        statusDiv.textContent = '✅ ' + (sp.message || 'Новых тренировок нет');
                        setTimeout(() => {{ statusDiv.textContent = ''; }}, 5000);
                    }}
                }}
            }}
        }} catch (e) {{
            overlay.classList.remove('active');
            statusDiv.className = 'sync-status sync-error';
            statusDiv.textContent = '❌ ' + e.message;
        }} finally {{
            btn.disabled = false;
            btn.textContent = '🔄 Coros Sync';
        }}
    }}

    document.getElementById('corosSyncBtn').addEventListener('click', syncCoros);
    </script>

    {nav_html}
    <table>
            <thead>
                <tr><th>Дата</th><th>Длительность</th><th>Дист., км</th><th>Пульс, уд/мин</th><th>Тип</th><th>Каденс</th><th>Набор</th><th>Энергозатраты, ккал</th></tr>
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
        .info {{ display: grid; grid-template-columns: 1fr 1fr 1fr 1fr 1fr 1fr 1fr; gap: 10px; margin: 15px 0; }}
        .info-item {{ background: white; padding: 8px; border-radius: 6px; text-align: center; display: flex; flex-direction: column; align-items: center; gap: 1px; }}
        .info-item b {{ font-size: 20px; color: #4CAF50; font-weight: bold; }}
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
        .info-label {{ font-size: 13px; font-weight: bold; color: #444; }}
        .info-unit {{ font-size: 12px; font-weight: bold; color: #666; }}
    </style>
</head>
<body>
    <h2>🏃 {type_ru} {suspect_badge}</h2>
    <p style='color:#666;'>{date}</p>
    {suspect_detail}
    <p style='color:#666;font-size:14px;margin:0 0 10px 0'>{background_info}</p>

    <div class='card'>
        <div class='info'>
            <div class='info-item'><span class='info-label'>Дистанция</span><b>{dist}</b><span class='info-unit'>км</span></div>
            <div class='info-item'><span class='info-label'>Общее время</span><b>{dur}</b><span class='info-unit'></span></div>
            <div class='info-item'><span class='info-label'>Пульс</span><b>{hr}</b><span class='info-unit'>уд/мин</span></div>
            <div class='info-item'><span class='info-label'>Каденс</span><b>{cadence}</b><span class='info-unit'></span></div>
            <div class='info-item'><span class='info-label'>Подъем</span><b>{elev_gain}</b><span class='info-unit'>м</span></div>
            <div class='info-item'><span class='info-label'>Спуск</span><b>{elev_loss}</b><span class='info-unit'>м</span></div>
            <div class='info-item'><span class='info-label'>Калории</span><b>{cal}</b><span class='info-unit'>ккал</span></div>
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
                        label: 'Пульс (уд/мин)',
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
                        y: {{ title: {{ display: true, text: 'Пульс, уд/мин' }}, position: 'left' }},
                        y1: {{ title: {{ display: true, text: 'Темп, мин/км' }}, position: 'right', reverse: true }},
                    }}
                }}
            }});
        }}
        </script>

        <h3>Детали по отрезкам</h3>
        <table>
            <thead>
                <tr><th>#</th><th>Зона</th><th>Длительность</th><th>Дист., км</th><th>Пульс, уд/мин</th><th>Каденс</th><th>Темп</th><th>↑ м</th><th>↓ м</th></tr>
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
            <hr>
            <h4>Синхронизация Coros (Coros sync)</h4>
            <label><b>Email Coros Training Hub:</b></label>
            <input type='email' name='coros_email' value='{coros_email}' style='width:250px;padding:6px;font-size:14px'>
            <label><b>Пароль Coros:</b></label>
            <input type='password' name='coros_password' value='{coros_password}' style='width:250px;padding:6px;font-size:14px'>
            <div style='font-size:12px;color:#888;margin-top:4px'>Пароль хранится локально в БД. Используется только для связи с Coros API.</div>
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
    # Очистка старых pending-файлов (Cleanup old pending uploads)
    for f in PENDING_DIR.glob("*.tcx"):
        f.unlink(missing_ok=True)
    _pending.clear()
    try:
        from sqlalchemy import text, JSON as SA_JSON
        with engine.connect() as conn:
            # Миграция колонок training_sessions (Migrate training_sessions columns)
            cols_to_add = {
                'weather_code': 'INTEGER',
                'hr_pace_series': 'JSON',
                'suspect_flags': 'JSON',
                'cleaning_log': 'JSON',
                'avg_cadence': 'INTEGER',
                'calories': 'INTEGER',
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
                'coros_email': 'VARCHAR(255)',
                'coros_password': 'VARCHAR(255)',
                'last_coros_sync': 'DATETIME',
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
async def index(year: Optional[int] = None, month: Optional[int] = None):
    return render_page(year=year, month=month)


# Загрузка TCX-файлов (TCX file upload endpoint)
@app.post('/upload')
async def upload_files(files: list[UploadFile] = File(...)):
    settings = get_settings()
    db = SessionLocal()
    problems = []
    saved = 0
    try:
        for file in files:
            ext = os.path.splitext(file.filename or '')[1].lower()
            suffix = ".fit" if ext == ".fit" else ".tcx"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                shutil.copyfileobj(file.file, tmp)
                tmp_path = tmp.name
            if ext == ".fit":
                data = parse_fit(tmp_path, max_hr=settings.max_hr,
                                 max_credible_pace=settings.max_credible_pace,
                                 max_gps_jump_m=settings.max_gps_jump_m,
                                 min_hr_for_fast_pace=settings.min_hr_for_fast_pace)
            else:
                data = parse_tcx(tmp_path, max_hr=settings.max_hr,
                                 max_credible_pace=settings.max_credible_pace,
                                 max_gps_jump_m=settings.max_gps_jump_m,
                                 min_hr_for_fast_pace=settings.min_hr_for_fast_pace)
            if data is None:
                logger.warning("Загрузка: не удалось распарсить %s (Upload: parse failed)", file.filename)
                os.unlink(tmp_path)
                continue
            cleaning_log = data.get('cleaning_log', [])
            # Сомнительные тренировки тоже сохраняем сразу (Save problematic sessions directly)
            # Сохраняем тренировку (Save training)
            exists = db.query(TrainingSession).filter(
                TrainingSession.begin_ts == data['begin_ts']
            ).first()
            if not exists:
                cleaning_log_val = data.pop('cleaning_log', None)
                flags_val = data.pop('suspect_flags', None)
                session = TrainingSession(**data)
                if cleaning_log_val:
                    session.cleaning_log = cleaning_log_val
                if flags_val:
                    session.suspect_flags = flags_val
                db.add(session)
                db.commit()
                saved += 1
            os.unlink(tmp_path)
    finally:
        db.close()
    return JSONResponse({'saved': saved})


# Подтверждение сомнительных тренировок (Confirm problematic uploads)
@app.post('/upload/confirm')
async def confirm_upload(temp_ids: list[str] = Form(...)):
    db = SessionLocal()
    confirmed = 0
    try:
        for temp_id in temp_ids:
            pending = _pending.pop(temp_id, None)
            if not pending:
                continue
            data = pending['data']
            exists = db.query(TrainingSession).filter(
                TrainingSession.begin_ts == data['begin_ts']
            ).first()
            if not exists:
                cleaning_log_val = data.pop('cleaning_log', None)
                flags_val = data.pop('suspect_flags', None)
                session = TrainingSession(**data)
                if cleaning_log_val:
                    session.cleaning_log = cleaning_log_val
                if flags_val:
                    session.suspect_flags = flags_val
                db.add(session)
                db.commit()
                confirmed += 1
            Path(pending['path']).unlink(missing_ok=True)
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
        eg = seg.get('elevation_gain')
        el = seg.get('elevation_loss')
        seg_eg = str(eg) if eg is not None else "—"
        seg_el = str(el) if el is not None else "—"
        cad_seg = seg.get('avg_cadence')
        cad_seg_str = str(cad_seg) if cad_seg is not None else "—"
        seg_rows += f"<tr class='{cls}'><td>{i}</td><td>Z{zone}</td><td>{dur}</td><td>{seg['distance_km']}</td><td>{seg['avg_hr']}</td><td>{cad_seg_str}</td><td>{pace}</td><td>{seg_eg}</td><td>{seg_el}</td></tr>"

    eg_total = s.elevation_gain or 0
    el_total = s.elevation_loss or 0
    if s.weather_code is not None and s.avg_temperature is not None:
        temp_display = f"{weather_icon(s.weather_code)} {s.avg_temperature}°"
    elif s.avg_temperature is not None:
        temp_display = f"{s.avg_temperature}°"
    else:
        temp_display = None
    background_info = temp_display if temp_display else ""

    import json
    chart_json = json.dumps(s.hr_pace_series or [])

    suspect_badge = ""
    suspect_detail = ""
    reason_labels = {
        'pace_impossible': 'Нереальный темп (Impossible pace)',
        'hr_pace_mismatch': 'Пульс не соответствует темпу (HR/pace mismatch)',
        'gps_spike': 'Скачки GPS (GPS jumps)',
        'too_short': 'Слишком короткая тренировка (Too short)',
        'anomaly': 'Аномалия (Anomaly)',
    }
    if s.cleaning_log:
        items = ""
        total_removed_dur = 0
        total_removed_dist = 0
        for entry in s.cleaning_log:
            reasons = ", ".join(reason_labels.get(r, r) for r in (entry.get('reason') or ['unknown']))
            removed_dur = entry.get('removed_dur_s', 0)
            removed_dist = entry.get('removed_dist_m', 0)
            total_removed_dur += removed_dur
            total_removed_dist += removed_dist
            dur_str = f"{removed_dur // 60}:{removed_dur % 60:02d}" if removed_dur else "—"
            items += f"<li>Удалён участок: {entry.get('removed_count', '?')} точек, {removed_dist}м, {dur_str} — {reasons}</li>"
        if items:
            suspect_badge = '<span style="background:#ff9800;color:white;padding:2px 10px;border-radius:4px;font-size:14px">✂️ Очищено</span>'
            suspect_detail = f'<div style="background:#fff3e0;border:1px solid #ffccbc;border-radius:8px;padding:10px;margin-bottom:15px"><b>✂️ Удалены ошибочные участки тренировки:</b><ul style="margin:5px 0 0 0;padding-left:20px">{items}</ul></div>'
    elif s.suspect_flags:
        items = "".join(f"<li>{reason_labels.get(f, f)}</li>" for f in s.suspect_flags)
        suspect_badge = '<span style="background:#ff5722;color:white;padding:2px 10px;border-radius:4px;font-size:14px">⚠️ Ошибочные данные</span>'
        suspect_detail = f'<div style="background:#fff3e0;border:1px solid #ffccbc;border-radius:8px;padding:10px;margin-bottom:15px"><b>⚠️ Обнаружены проблемы:</b><ul style="margin:5px 0 0 0;padding-left:20px">{items}</ul></div>'

    cadence_display = str(s.avg_cadence) if s.avg_cadence is not None else "—"
    cal = str(s.calories) if s.calories is not None else "—"

    return SESSION_HTML.format(
        session_id=s.id,
        suspect_badge=suspect_badge,
        suspect_detail=suspect_detail,
        type_ru=TRAINING_TYPES_RU.get(s.training_type, s.training_type),
        date=s.begin_ts.strftime("%d.%m.%Y %H:%M") if s.begin_ts else "",
        dist=f"{s.total_distance_km:.2f}",
        dur=fmt_duration(s.duration_minutes),
        hr=s.avg_heart_rate,
        cadence=cadence_display,
        cal=cal,
        background_info=background_info,
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
                                min_hr_for_fast_pace=settings.min_hr_for_fast_pace,
                                coros_email=settings.coros_email or '',
                                coros_password=settings.coros_password or '')


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
                        min_hr_for_fast_pace: int = Form(130),
                        coros_email: str = Form(''),
                        coros_password: str = Form('')):
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
            s.coros_email = coros_email or None
            s.coros_password = coros_password or None
            if weight != old_weight:
                wm = WeightMeasurement(weight_kg=weight, measured_at=datetime.utcnow())
                db.add(wm)
            db.commit()
    finally:
        db.close()
    return RedirectResponse(url='/', status_code=303)


# Просмотр лога операций (View operation log)
@app.get('/logs')
async def view_logs(lines: int = 100):
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.log")
    if not os.path.exists(log_path):
        return HTMLResponse("<html><body><h2>Лог пуст</h2></body></html>")
    with open(log_path, "r", encoding="utf-8") as f:
        all_lines = f.readlines()
    tail = all_lines[-lines:]
    html = "<html><head><meta charset='utf-8'><title>Лог операций</title>"
    html += "<style>body{font-family:monospace;font-size:13px;background:#1e1e1e;color:#d4d4d4;padding:20px}"
    html += ".INFO{color:#4ec9b0}.WARNING{color:#ce9178}.ERROR{color:#f44747}.DEBUG{color:#808080}"
    html += "a{color:#569cd6;text-decoration:none;margin-right:10px}</style></head><body>"
    html += "<h2>📋 Лог операций</h2>"
    html += f"<p>Последние {len(tail)} строк (<a href='/logs?lines=50'>50</a> "
    html += f"<a href='/logs?lines=200'>200</a> <a href='/logs?lines=1000'>все</a>)</p>"
    html += "<pre>"
    for line in tail:
        level = "INFO" if " [INFO] " in line else ("WARNING" if " [WARNING] " in line else
                ("ERROR" if " [ERROR] " in line else "DEBUG"))
        html += f"<span class='{level}'>{line.strip()}</span>\n"
    html += "</pre></body></html>"
    return HTMLResponse(html)


# Синхронизация тренировок с Coros — запуск в фоне (Coros sync — background task)
@app.post('/coros/sync')
async def coros_sync():
    from src.coros_client import CorosClient, CorosAuthError, CorosAPIError
    from src.parsers.fit_parser import parse_fit
    from src.models import UserSettings
    import tempfile

    db = SessionLocal()
    try:
        us = db.query(UserSettings).first()
        if not us or not us.coros_email or not us.coros_password:
            return JSONResponse({'status': 'error', 'message': 'Coros credentials not configured.'})
    finally:
        db.close()

    task_id = str(uuid.uuid4())
    progress = {
        'task_id': task_id, 'step': 'queued', 'message': 'В очереди...',
        'total': 0, 'current': 0, 'synced': 0, 'errors': [], 'total_found': 0, 'done': False,
    }
    with _sync_tasks_lock:
        _sync_tasks[task_id] = progress

    def _run():
        db = SessionLocal()
        try:
            us = db.query(UserSettings).first()
            progress['step'] = 'auth'
            progress['message'] = 'Подключение к Coros...'
            logger.info("Запуск синхронизации Coros (Coros sync started)")
            client = CorosClient(us.coros_email, us.coros_password, timeout=15)
            client.authenticate()
            logger.info("Аутентификация Coros пройдена (Coros auth successful)")

            progress['step'] = 'fetch'
            progress['message'] = 'Получение списка активностей...'
            activities = client.list_activities(limit=50, since=None)
            progress['total_found'] = len(activities)
            logger.info("Получено активностей из Coros: %d", len(activities))

            if not activities:
                progress['step'] = 'done'
                progress['message'] = 'Нет новых беговых активностей'
                progress['done'] = True
                logger.info("Синхронизация Coros: нет беговых активностей")
                return

            # Фильтруем новые (не в БД)
            existing_times = {r[0] for r in db.query(TrainingSession.begin_ts).all()}
            def already_imported(ts):
                for et in existing_times:
                    if et is not None and abs((et - ts).total_seconds()) < 120:
                        return True
                return False

            new_acts = [a for a in activities if not already_imported(a['start_time'])]
            if not new_acts:
                progress['step'] = 'done'
                progress['message'] = 'Все активности уже импортированы'
                progress['total'] = 0
                progress['done'] = True
                logger.info("Синхронизация Coros: все активности уже в БД")
                return

            progress['total'] = len(new_acts)
            synced = 0
            max_act_ts = us.last_coros_sync
            latest_ts = us.last_coros_sync

            for i, act in enumerate(new_acts):
                progress['step'] = 'download'
                progress['current'] = i + 1
                progress['message'] = f'Скачивание {i+1}/{len(new_acts)}: {act["name"]}'
                logger.info("Загрузка новой активности: %s (%s)", act['name'], act['start_time'])

                tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.fit')
                tmp.close()
                try:
                    ok = client.download_fit(act['id'], act['sport_type'], tmp.name)
                    if not ok:
                        logger.warning("Не удалось скачать FIT для %s", act['name'])
                        progress['errors'].append(f"{act['name']}: download failed")
                        os.unlink(tmp.name)
                        continue

                    progress['step'] = 'parse'
                    progress['message'] = f'Обработка {i+1}/{len(new_acts)}: {act["name"]}'
                    data = parse_fit(tmp.name, max_hr=us.max_hr,
                                     max_credible_pace=us.max_credible_pace,
                                     max_gps_jump_m=us.max_gps_jump_m,
                                     min_hr_for_fast_pace=us.min_hr_for_fast_pace)
                    if data is None:
                        logger.warning("Не удалось распарсить FIT для %s", act['name'])
                        progress['errors'].append(f"{act['name']}: parse failed")
                        os.unlink(tmp.name)
                        continue

                    cleaning_log = data.pop('cleaning_log', None)
                    flags_val = data.pop('suspect_flags', None)
                    if data.get('training_type') in ('invalid', None):
                        logger.warning("Некорректные данные для %s", act['name'])
                        progress['errors'].append(f"{act['name']}: invalid data")
                        os.unlink(tmp.name)
                        continue

                    session = TrainingSession(**data)
                    if cleaning_log:
                        session.cleaning_log = cleaning_log
                    if flags_val:
                        session.suspect_flags = flags_val
                    db.add(session)
                    db.commit()
                    synced += 1
                    progress['synced'] = synced
                    logger.info("Активность сохранена: %s (%s)", act['name'], act['start_time'])
                    if latest_ts is None or act['start_time'] > latest_ts:
                        latest_ts = act['start_time']
                except Exception as e:
                    logger.exception("Ошибка при обработке %s", act['name'])
                    progress['errors'].append(f"{act['name']}: {str(e)}")
                finally:
                    if os.path.exists(tmp.name):
                        os.unlink(tmp.name)
                if max_act_ts is None or act['start_time'] > max_act_ts:
                    max_act_ts = act['start_time']

            if max_act_ts is not None and (us.last_coros_sync is None or max_act_ts > us.last_coros_sync):
                us.last_coros_sync = max_act_ts
                db.commit()
                logger.info("last_coros_sync обновлён: %s", max_act_ts)

            logger.info("Синхронизация Coros завершена: synced=%d, errors=%d", synced, len(progress['errors']))
            progress['step'] = 'done'
            progress['message'] = f'Синхронизировано: {synced}'
            progress['done'] = True
        except CorosAuthError as e:
            progress['step'] = 'error'
            progress['message'] = f'Ошибка аутентификации Coros: {e}'
            progress['done'] = True
            logger.error("Coros auth error: %s", e)
        except CorosAPIError as e:
            progress['step'] = 'error'
            progress['message'] = f'Ошибка Coros API: {e}'
            progress['done'] = True
            logger.error("Coros API error: %s", e)
        except Exception as e:
            if 'Timeout' in type(e).__name__:
                progress['message'] = 'Таймаут подключения к Coros'
            elif 'ConnectionError' in type(e).__name__:
                progress['message'] = 'Не удалось подключиться к Coros'
            else:
                progress['message'] = f'Ошибка: {type(e).__name__}: {e}'
            progress['step'] = 'error'
            progress['done'] = True
            logger.error("Coros sync error", exc_info=True)
        finally:
            db.close()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return JSONResponse({'task_id': task_id, 'status': 'started'})


# Статус фоновой синхронизации Coros (Background Coros sync status)
@app.get('/coros/sync/status/{task_id}')
async def coros_sync_status(task_id: str):
    with _sync_tasks_lock:
        p = _sync_tasks.get(task_id)
    if not p:
        return JSONResponse({'status': 'error', 'message': 'Task not found'})
    return JSONResponse(p)
