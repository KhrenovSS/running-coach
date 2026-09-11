# Утилиты анализа: форматирование, высота, часовой пояс, пики пульса, паузы, сериализация
# Analysis utilities: formatting, elevation, timezone, HR peaks, pauses, serialization
# (ряды темпа — analysis/pace_series.py, #329)

from datetime import datetime
from statistics import median
from typing import TypedDict
from timezonefinder import TimezoneFinder

from src.config.constants import ELEV_HYSTERESIS_M, HR_SMOOTH_MEDIAN_WINDOW


class TrackpointDict(TypedDict, total=False):
    """Трекпоинт: точка записи с данными датчиков (Trackpoint: sensor data point)"""
    time: datetime | None
    hr: int | None
    dist: float | None        # Накопительная дистанция в метрах (cumulative distance in meters)
    lat: float | None
    lon: float | None
    alt: float | None
    cad: int | None            # Каденс (cadence, spm)


class AnalysisResult(TypedDict, total=False):
    """Результат process_trackpoints (process_trackpoints result)"""
    begin_ts: datetime
    total_distance_km: float
    avg_heart_rate: int
    max_heart_rate: int
    hr_peak_smoothed: int | None
    training_type: str
    segments_count: int
    duration_minutes: float
    segments_json: list[dict]
    hr_pace_series: list[dict]
    avg_temperature: int | None
    weather_code: int | None
    elevation_gain: int | None
    elevation_loss: int | None
    avg_cadence: int | None
    timezone: str | None
    trackpoints_json: list[dict]
    cleaning_log: list[dict] | None
    suspect_flags: list[str] | None
    avg_pace: float | None
    gps_quality: dict | None
    laps_json: list[dict] | None      # F1: лапы часов (добавляет parse_fit, не пайплайн)
    device_summary: dict | None       # F1: эталоны session-сообщения + паузы записи

_tf = TimezoneFinder()


def format_pace(min_per_km: float | None) -> str | None:
    """
    Форматировать темп из мин/км в M:SS
    Format pace from min/km to M:SS
    """
    if min_per_km is None or min_per_km <= 0:
        return None
    m = int(min_per_km)
    s = round((min_per_km - m) * 60)
    if s >= 60:
        m += 1
        s = 0
    return f"{m}:{s:02d}"


def format_duration(duration_min: float | None) -> str | None:
    """
    Форматировать длительность из минут в M:SS
    Format duration from minutes to M:SS
    """
    if duration_min is None or duration_min <= 0:
        return None
    m = int(duration_min)
    s = round((duration_min - m) * 60)
    if s >= 60:
        m += 1
        s = 0
    return f"{m}:{s:02d}"


def calc_elevation(altitudes: list[float | None],
                   hysteresis_m: float = ELEV_HYSTERESIS_M) -> tuple[int, int]:
    """Набор и спуск высоты с гистерезисом (#253): подъём засчитывается, когда высота ушла от
    опорного экстремума на ≥ hysteresis_m — так считают часы; шум барометра ±0.5 м в сумму не
    попадает. None внутри ряда — forward-fill (разрыв барометра не даёт фиктивной дельты).
    hysteresis_m=0 → прежняя наивная сумма дельт (совместимость).
    (Elevation gain/loss with hysteresis: a reversal counts only after the altitude moves
    ≥ threshold away from the last extremum; None gaps are forward-filled.)
    """
    known = [a for a in altitudes if a is not None]
    if len(known) < 2:
        return 0, 0
    gain = loss = 0.0
    ref = ext = float(known[0])   # ref — подтверждённый экстремум, ext — текущий кандидат
    direction = 0                 # 0 — ещё не определено, +1 вверх, −1 вниз
    prev = ref
    for a in altitudes:
        if a is None:
            continue
        a = float(a)
        if hysteresis_m <= 0:
            diff = a - prev
            if diff > 0:
                gain += diff
            else:
                loss -= diff
            prev = a
            continue
        if direction >= 0:
            if a > ext:
                ext = a
            if ext - a >= hysteresis_m:          # разворот вниз подтверждён
                gain += max(0.0, ext - ref)
                ref, ext, direction = ext, a, -1
        else:
            if a < ext:
                ext = a
            if a - ext >= hysteresis_m:          # разворот вверх подтверждён
                loss += max(0.0, ref - ext)
                ref, ext, direction = ext, a, 1
    if hysteresis_m > 0:                         # хвост по текущему направлению — только ≥ порога
        if direction >= 0 and ext - ref >= hysteresis_m:
            gain += ext - ref
        elif direction < 0 and ref - ext >= hysteresis_m:
            loss += ref - ext
    return round(gain), round(loss)


def find_timezone(positions: list[tuple[float | None, float | None]]) -> str | None:
    """
    Определить IANA-таймзону по GPS-координатам
    Determine IANA timezone from GPS coordinates
    """
    for lat, lon in positions:
        if lat is not None and lon is not None:
            tz = _tf.timezone_at(lat=lat, lng=lon)
            if tz:
                return tz
    return None


def smoothed_hr_peak(hr_values: list[int], window: int = HR_SMOOTH_MEDIAN_WINDOW) -> int | None:
    """
    Пик пульса по скользящей медиане: одиночные выбросы датчика (230 на 1 сэмпл)
    исчезают, устойчивый высокий пульс сохраняется.
    (HR peak over a rolling median: single-sample sensor spikes vanish,
    sustained high HR survives.)
    """
    if not hr_values:
        return None
    n = len(hr_values)
    if n < window:
        return int(median(hr_values))
    half = window // 2
    return int(max(
        median(hr_values[max(0, i - half):min(n, i + half + 1)])
        for i in range(n)
    ))


def pauses_to_offsets(pauses: list[dict] | None, track_start) -> list[tuple[float, float]]:
    """device_summary.pauses (ISO start/end) → [(start_sec, end_sec)] от начала трека (#286).
    Мусор/None → []. (Watch pauses as second offsets from track start.)"""
    from datetime import datetime
    out: list[tuple[float, float]] = []
    if not pauses or track_start is None:
        return out
    for p in pauses:
        try:
            s = p.get("start"); e = p.get("end")
            s_dt = datetime.fromisoformat(s) if isinstance(s, str) else s
            e_dt = datetime.fromisoformat(e) if isinstance(e, str) else e
            if s_dt is None or e_dt is None:
                continue
            a = (s_dt - track_start).total_seconds()
            b = (e_dt - track_start).total_seconds()
            if b > a:
                out.append((a, b))
        except (TypeError, ValueError, AttributeError):
            continue
    return sorted(out)


def pause_overlap_sec(t0: float, t1: float, pauses_sec: list[tuple[float, float]] | None) -> float:
    """Сколько секунд интервала [t0, t1] приходится на паузы записи (#286)."""
    if not pauses_sec or t1 <= t0:
        return 0.0
    total = 0.0
    for a, b in pauses_sec:
        lo, hi = max(t0, a), min(t1, b)
        if hi > lo:
            total += hi - lo
    return total


def early_peak_suspect(times: list[float], hrs: list[int], dists: list[float], *,
                       window_sec: int, pace_slack_min_km: float, delta_bpm: int) -> tuple[int | None, bool]:
    """Ранний пик пульса на медленном темпе = глюк оптического датчика (#238).

    Возвращает (пик без первого окна, suspect): suspect=True, когда сглаженный пик всей
    тренировки лежит в первые window_sec, темп там медленнее медианы сессии на
    pace_slack_min_km и пик остального участка ниже на delta_bpm и больше.
    (Early peak at slow pace → optical-sensor glitch; use the peak after the window.)
    """
    if len(times) < 3 or len(times) != len(hrs) or len(times) != len(dists):
        return None, False
    t0 = times[0]
    early = [i for i, t in enumerate(times) if t - t0 <= window_sec]
    late = [i for i, t in enumerate(times) if t - t0 > window_sec]
    if len(early) < 2 or len(late) < 3:
        return None, False
    peak_all = smoothed_hr_peak(hrs)
    peak_late = smoothed_hr_peak([hrs[i] for i in late])
    if peak_all is None or peak_late is None or peak_all - peak_late < delta_bpm:
        return peak_late, False
    peak_early = smoothed_hr_peak([hrs[i] for i in early])
    if peak_early is None or peak_early < peak_all:
        return peak_late, False

    def _pace(idx: list[int]) -> float | None:
        dd = dists[idx[-1]] - dists[idx[0]]
        dt = times[idx[-1]] - times[idx[0]]
        return (dt / 60.0) / (dd / 1000.0) if dd > 0 and dt > 0 else None

    early_pace, all_pace = _pace(early), _pace(list(range(len(times))))
    if early_pace is None or all_pace is None:
        return peak_late, False
    return peak_late, early_pace >= all_pace + pace_slack_min_km


def is_km_segmentation(segments: list[dict], total_dist_km: float) -> bool:
    """
    Проверить, являются ли сегменты км-блоками.
    Check if segments are km-based blocks.
    Км-блок: все сегменты ~1.0км (±0.15), последний может быть короче.
    """
    if not segments:
        return False
    num_km = max(1, int(total_dist_km))
    if abs(len(segments) - num_km) > 1 and abs(len(segments) - (num_km + 1)) > 1:
        return False
    for i, s in enumerate(segments):
        d = s.get('distance_km', 0)
        if i < len(segments) - 1:
            if d < 0.85 or d > 1.15:
                return False
        else:
            if d > 1.15:
                return False
    return True


def serialize_trackpoints(trackpoints: list[dict]) -> list[dict]:
    """
    Сериализовать трекпоинты для JSON-хранилища (Serialize trackpoints for JSON storage)
    Конвертирует datetime → ISO-строку для JSON. Сохраняет None-значения.
    """
    result = []
    for tp in trackpoints:
        serialized = {}
        for k, v in tp.items():
            if hasattr(v, 'isoformat'):
                serialized[k] = v.isoformat()
            else:
                serialized[k] = v
        result.append(serialized)
    return result
