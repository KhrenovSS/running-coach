import fitdecode
from datetime import datetime
from src.analysis import process_trackpoints
from src.config import settings

# Константа для конвертации полуокружностей в градусы (Semicircles to degrees)
SEMICIRCLE_TO_DEG = 180.0 / 2**31


def _iso(t) -> str | None:
    """datetime → ISO-строка для JSON-колонок (datetime to ISO string for JSON columns)."""
    return t.isoformat() if t is not None else None


def _lap_row(ldata: dict) -> dict:
    """Компактная строка lap-сообщения: метры/секунды/уд-мин; None-поля опущены.
    (Compact lap row: meters/seconds/bpm; None fields omitted.)"""
    speed = ldata.get('enhanced_avg_speed') or ldata.get('avg_speed')
    row = {
        'start_time': _iso(ldata.get('start_time')),
        'distance_m': round(ldata['total_distance']) if ldata.get('total_distance') is not None else None,
        'timer_s': round(ldata['total_timer_time']) if ldata.get('total_timer_time') is not None else None,
        'elapsed_s': round(ldata['total_elapsed_time']) if ldata.get('total_elapsed_time') is not None else None,
        'avg_hr': ldata.get('avg_heart_rate'),
        'max_hr': ldata.get('max_heart_rate'),
        'min_hr': ldata.get('min_heart_rate'),
        'avg_speed_ms': round(speed, 3) if speed is not None else None,
        'avg_cadence': ldata.get('avg_running_cadence'),
        'ascent_m': ldata.get('total_ascent'),
        'descent_m': ldata.get('total_descent'),
    }
    return {k: v for k, v in row.items() if v is not None}


def _device_summary(sdata: dict) -> dict:
    """Эталоны часов из session-сообщения (watch-reported reference values).

    Дистанция/время/шаги/динамика — независимый от нашего пайплайна источник
    для кросс-чеков (F2/F7) и оценки по шагам (total_strides × avg_step_length).
    """
    def _r(key, ndigits=None, factor=1.0):
        v = sdata.get(key)
        if v is None:
            return None
        v = v * factor
        return round(v, ndigits) if ndigits is not None else round(v)

    summary = {
        'distance_m': _r('total_distance'),
        'timer_s': _r('total_timer_time'),
        'elapsed_s': _r('total_elapsed_time'),
        'avg_speed_ms': _r('enhanced_avg_speed', 3) or _r('avg_speed', 3),
        'max_speed_ms': _r('enhanced_max_speed', 3) or _r('max_speed', 3),
        'avg_hr': sdata.get('avg_heart_rate'),
        'max_hr': sdata.get('max_heart_rate'),
        'min_hr': sdata.get('min_heart_rate'),
        'total_strides': sdata.get('total_strides'),
        'avg_step_length_mm': _r('avg_step_length'),
        'avg_power_w': sdata.get('avg_power'),
        'avg_stance_time_ms': _r('avg_stance_time'),
        'avg_vertical_oscillation_mm': _r('avg_vertical_oscillation', 1),
        'avg_vertical_ratio_pct': _r('avg_vertical_ratio', 1),
        'total_ascent_m': sdata.get('total_ascent'),
        'total_descent_m': sdata.get('total_descent'),
        'avg_temperature_c': sdata.get('avg_temperature'),
        # Effort Pace — developer-поле Coros: собственный grade-adjusted pace часов
        # (Coros own grade-adjusted pace, developer field) — эталон для нашего GAP (F7)
        'effort_pace_ms': _r('Effort Pace', 3),
    }
    return {k: v for k, v in summary.items() if v is not None}


# Извлечь активность из FIT-файла БЕЗ обработки: трекпоинты + лапы + паузы + эталоны часов
# (Extract raw FIT activity: trackpoints + laps + pauses + watch summary; no processing)
def extract_fit_activity(file_path, coros_cadence_workaround=False):
    trackpoints = []
    calories = None
    laps: list[dict] = []
    device_summary: dict = {}
    timer_events: list[tuple[str, datetime]] = []

    with fitdecode.FitReader(file_path, check_crc=True) as fit:
        for frame in fit:
            if frame.frame_type != fitdecode.FIT_FRAME_DATA:
                continue
            # Обработка record-сообщений (трэкпоинты) (Parse record messages — trackpoints)
            if frame.name == 'record':
                data = {f.name: f.value for f in frame.fields}
                t = data.get('timestamp')
                if t is None:
                    continue
                hr = data.get('heart_rate')
                dist = data.get('distance')
                alt = data.get('enhanced_altitude') or data.get('altitude')
                cad = data.get('cadence')
                if cad is not None and cad < 100 and coros_cadence_workaround:
                    cad = cad * 2
                lat = None
                lon = None
                if 'position_lat' in data and data['position_lat'] is not None:
                    lat = data['position_lat'] * SEMICIRCLE_TO_DEG
                if 'position_long' in data and data['position_long'] is not None:
                    lon = data['position_long'] * SEMICIRCLE_TO_DEG
                # Расчёт дистанции через скорость, если distance отсутствует (Calculate distance from speed if missing)
                if dist is None:
                    speed = data.get('enhanced_speed') or data.get('speed')
                    if speed is not None and trackpoints:
                        last_tp = trackpoints[-1]
                        if last_tp['time'] and t and last_tp['dist'] is not None:
                            dt = (t - last_tp['time']).total_seconds()
                            dist = last_tp['dist'] + speed * dt
                tp = {
                    'time': t, 'hr': hr, 'dist': dist,
                    'alt': alt, 'lat': lat, 'lon': lon, 'cad': cad,
                }
                # Каналы динамики бега (F1, #285): опциональные ключи — только при наличии
                # значения, чтобы не раздувать trackpoints_json на часах без этих метрик
                # (running dynamics channels: optional keys, present only when the watch writes them)
                if data.get('power') is not None:
                    tp['pw'] = int(data['power'])
                if data.get('stance_time') is not None:
                    tp['st'] = round(data['stance_time'])
                if data.get('vertical_oscillation') is not None:
                    tp['vo'] = round(data['vertical_oscillation'], 1)
                if data.get('vertical_ratio') is not None:
                    tp['vr'] = round(data['vertical_ratio'], 1)
                if data.get('step_length') is not None:
                    tp['sl'] = round(data['step_length'])
                trackpoints.append(tp)
            # Session: калории + эталоны часов (calories + watch-reported summary)
            elif frame.name == 'session':
                sdata = {f.name: f.value for f in frame.fields}
                cal = sdata.get('total_calories')
                if cal is not None:
                    calories = int(cal)
                device_summary.update(_device_summary(sdata))
            # Lap: авто-км и ручные круги — разметка структуры от часов (watch lap marks)
            elif frame.name == 'lap':
                ldata = {f.name: f.value for f in frame.fields}
                lap = _lap_row(ldata)
                if lap.get('distance_m') or lap.get('timer_s'):
                    laps.append(lap)
            # Event timer start/stop: точные границы пауз записи (exact pause boundaries)
            elif frame.name == 'event':
                edata = {f.name: f.value for f in frame.fields}
                if edata.get('event') == 'timer' and edata.get('timestamp'):
                    et = edata.get('event_type')
                    if et in ('start', 'stop_all', 'stop'):
                        timer_events.append((et, edata['timestamp']))

    # Паузы: stop → следующий start (pauses: stop until the next start)
    pauses = []
    stop_ts = None
    for et, t in sorted(timer_events, key=lambda x: x[1]):
        if et in ('stop_all', 'stop'):
            stop_ts = t
        elif et == 'start' and stop_ts is not None:
            dur = (t - stop_ts).total_seconds()
            if dur > 0:
                pauses.append({'start': _iso(stop_ts), 'end': _iso(t),
                               'duration_s': round(dur)})
            stop_ts = None
    if pauses:
        device_summary['pauses'] = pauses

    return {
        'trackpoints': trackpoints,
        'calories': calories,
        'laps': laps,
        'device_summary': device_summary,
    }


# Совместимость: старый интерфейс (трекпоинты + калории) поверх extract_fit_activity
# (Compat wrapper: legacy (trackpoints, calories) interface over extract_fit_activity)
def extract_fit_trackpoints(file_path, coros_cadence_workaround=False):
    activity = extract_fit_activity(file_path, coros_cadence_workaround=coros_cadence_workaround)
    return activity['trackpoints'], activity['calories']


# Парсинг FIT-файла (FIT file parsing)
def parse_fit(file_path, max_hr=None, max_credible_pace=3.0, max_gps_jump_m=100.0, min_hr_for_fast_pace=130, coros_cadence_workaround=False):
    if max_hr is None:
        max_hr = settings.default_max_hr
    activity = extract_fit_activity(file_path, coros_cadence_workaround=coros_cadence_workaround)
    trackpoints = activity['trackpoints']
    if not trackpoints:
        return None
    start_time_utc = trackpoints[0]['time']
    result = process_trackpoints(trackpoints, start_time_utc, max_hr,
                                  max_credible_pace, max_gps_jump_m, min_hr_for_fast_pace)
    if result is None:
        return None
    if activity['calories'] is not None:
        result['calories'] = activity['calories']
    # F1 (#285): разметка от часов — лапы и эталоны session (+паузы) в колонки сессии
    # (watch-provided structure: laps and session reference values)
    result['laps_json'] = activity['laps'] or None
    result['device_summary'] = activity['device_summary'] or None
    return result
