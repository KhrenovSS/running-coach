# Импорт библиотек: XML, дата/время (Library imports)
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# Импорт общей логики обработки (Import shared processing logic)
from src.analysis import process_trackpoints
from .weather import weather_icon
from src.config import settings

# Пространство имён Garmin TCX (Garmin TCX XML namespace)
NS = {
    'tcx': 'http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2',
    'tpx': 'http://www.garmin.com/xmlschemas/ActivityExtension/v2',
}


# Основная функция парсинга TCX-файла (Main TCX file parsing function)
def parse_tcx(file_path, max_hr=None, max_credible_pace=3.0, max_gps_jump_m=100.0, min_hr_for_fast_pace=130):
    if max_hr is None:
        max_hr = settings.default_max_hr
    # Парсинг XML и получение корневого элемента (Parse XML and get root element)
    tree = ET.parse(file_path)
    root = tree.getroot()

    # Извлечение времени старта из TCX (Extract start time from TCX)
    start_time_str = root.findtext('.//tcx:StartTime', namespaces=NS) or root.findtext('.//tcx:Id', namespaces=NS)
    start_time_utc = datetime.fromisoformat(start_time_str.replace('Z', '+00:00')) if start_time_str else datetime.now(timezone.utc)

    # Парсинг всех trackpoint (Parse all trackpoints)
    trackpoints = []
    for tp in root.findall('.//tcx:Trackpoint', NS):
        time_str = tp.findtext('tcx:Time', namespaces=NS)
        hr_str = tp.findtext('tcx:HeartRateBpm/tcx:Value', namespaces=NS)
        dist_str = tp.findtext('tcx:DistanceMeters', namespaces=NS)
        alt_str = tp.findtext('tcx:AltitudeMeters', namespaces=NS)
        lat_str = tp.findtext('tcx:Position/tcx:LatitudeDegrees', namespaces=NS)
        lon_str = tp.findtext('tcx:Position/tcx:LongitudeDegrees', namespaces=NS)
        # Парсинг каденса из секции Extensions/TPX (Parse cadence from Extensions/TPX)
        cad_str = tp.findtext('tcx:Extensions/tpx:RunCadence', namespaces=NS)
        t = datetime.fromisoformat(time_str.replace('Z', '+00:00')) if time_str else None
        hr = int(hr_str) if hr_str else None
        dist = float(dist_str) if dist_str else None
        alt = float(alt_str) if alt_str else None
        lat = float(lat_str) if lat_str else None
        lon = float(lon_str) if lon_str else None
        cad = int(float(cad_str)) if cad_str else None
        trackpoints.append({'time': t, 'hr': hr, 'dist': dist, 'alt': alt, 'lat': lat, 'lon': lon, 'cad': cad})

    # Обработка через общий процессор (Process through shared pipeline)
    return process_trackpoints(trackpoints, start_time_utc, max_hr,
                                max_credible_pace, max_gps_jump_m, min_hr_for_fast_pace)
