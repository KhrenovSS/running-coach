# Парсинг FIT-файлов (FIT file parser)
# FIT — бинарный формат, стандарт для спортивных часов (Garmin, Coros, Polar, Suunto)
from datetime import datetime
from .common import process_trackpoints

# Константа для конвертации полуокружностей в градусы (Semicircles to degrees)
SEMICIRCLE_TO_DEG = 180.0 / 2**31


# Основная функция парсинга FIT-файла (Main FIT file parsing function)
def parse_fit(file_path, max_hr=177, max_credible_pace=3.0, max_gps_jump_m=100.0, min_hr_for_fast_pace=130):
    from fitparse import FitFile

    fitfile = FitFile(file_path)
    fitfile.parse()

    trackpoints = []
    start_time_utc = None

    for record in fitfile.get_messages('record'):
        data = {}
        for field in record:
            data[field.name] = field.value

        t = data.get('timestamp')
        if t is None:
            continue

        hr = data.get('heart_rate')
        dist = data.get('distance')  # метры, накопленная (cumulative meters)
        alt = data.get('enhanced_altitude') or data.get('altitude')
        cad = data.get('cadence')  # шагов/мин для бега (steps per minute for running)

        # Конвертация полуокружностей в градусы (Convert semicircles to degrees)
        lat = None
        lon = None
        if 'position_lat' in data and data['position_lat'] is not None:
            lat = data['position_lat'] * SEMICIRCLE_TO_DEG
        if 'position_long' in data and data['position_long'] is not None:
            lon = data['position_long'] * SEMICIRCLE_TO_DEG

        # Если нет дистанции — попробуем рассчитать из скорости (If no distance, try speed)
        if dist is None:
            speed = data.get('enhanced_speed') or data.get('speed')
            if speed is not None and trackpoints:
                last_tp = trackpoints[-1]
                if last_tp['time'] and t and last_tp['dist'] is not None:
                    dt = (t - last_tp['time']).total_seconds()
                    dist = last_tp['dist'] + speed * dt

        trackpoints.append({
            'time': t,
            'hr': hr,
            'dist': dist,
            'alt': alt,
            'lat': lat,
            'lon': lon,
            'cad': cad,
        })

    if not trackpoints:
        return None

    start_time_utc = trackpoints[0]['time']

    # Обработка через общий процессор (Process through shared pipeline)
    result = process_trackpoints(trackpoints, start_time_utc, max_hr,
                                  max_credible_pace, max_gps_jump_m, min_hr_for_fast_pace)
    if result is None:
        return None

    # Парсинг session-сообщений: дополнительные метрики (Parse session messages for extra metrics)
    for session in fitfile.get_messages('session'):
        sdata = {}
        for field in session:
            sdata[field.name] = field.value

        te = sdata.get('total_training_effect')
        if te is not None:
            result['training_effect'] = round(float(te), 1)

        ate = sdata.get('anaerobic_training_effect')
        if ate is not None:
            result['anaerobic_training_effect'] = round(float(ate), 1)

        # VO2max — может быть в session или в record, берём из session
        for vo2_key in ('vo2max_value', 'vo2max', 'estimated_vo2max'):
            vo2 = sdata.get(vo2_key)
            if vo2 is not None:
                result['vo2max'] = round(float(vo2), 1)
                break

        cal = sdata.get('total_calories')
        if cal is not None:
            result['calories'] = int(cal)

    # Если VO2max не нашёлся в session, проверим в developer_data или record
    if 'vo2max' not in result:
        for record in fitfile.get_messages('record'):
            for field in record:
                if field.name in ('vo2max_value', 'vo2max', 'estimated_vo2max') and field.value is not None:
                    result['vo2max'] = round(float(field.value), 1)
                    break
            if 'vo2max' in result:
                break

    return result
