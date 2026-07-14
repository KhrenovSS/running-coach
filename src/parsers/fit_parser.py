import fitdecode
from datetime import datetime
from src.analysis import process_trackpoints
from src.config import settings

# Константа для конвертации полуокружностей в градусы (Semicircles to degrees)
SEMICIRCLE_TO_DEG = 180.0 / 2**31

# Парсинг FIT-файла (FIT file parsing)
def parse_fit(file_path, max_hr=None, max_credible_pace=3.0, max_gps_jump_m=100.0, min_hr_for_fast_pace=130):
    if max_hr is None:
        max_hr = settings.default_max_hr
    trackpoints = []
    start_time_utc = None
    calories = None

    with fitdecode.FitReader(file_path, check_crc=False) as fit:
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
                if cad is not None and cad < 100:
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
                trackpoints.append({
                    'time': t, 'hr': hr, 'dist': dist,
                    'alt': alt, 'lat': lat, 'lon': lon, 'cad': cad,
                })
            # Обработка session-сообщений (калории) (Parse session messages — calories)
            elif frame.name == 'session':
                sdata = {f.name: f.value for f in frame.fields}
                cal = sdata.get('total_calories')
                if cal is not None:
                    calories = int(cal)

    if not trackpoints:
        return None
    start_time_utc = trackpoints[0]['time']
    result = process_trackpoints(trackpoints, start_time_utc, max_hr,
                                  max_credible_pace, max_gps_jump_m, min_hr_for_fast_pace)
    if result is None:
        return None
    if calories is not None:
        result['calories'] = calories
    return result
