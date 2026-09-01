# Квалиметрия GPS-трека и честная оценка дистанции по шагам при недостоверном GPS
# (GPS track quality assessment + honest cadence-based distance estimate for unreliable GPS)
#
# Кейс-мотиватор — сессия №42 (01.09.2026): 15 минут GPS-сбоя раздули дистанцию часов
# до 15.65 км, а очистка занизила её до 4.58 км; честная оценка по шагам ≈ 6.7 км.
# Схема результата и пороги — план "gps quality" (см. docs/coach/METRICS_GUIDE.md, CHANGELOG).

from src.config.constants import (
    GPS_QUALITY_MIN_POINTS,
    GPS_NO_POSITION_FLAG_PCT,
    GPS_NO_POSITION_TREADMILL_PCT,
    GPS_IMPOSSIBLE_SPEED_FLAG_PCT,
    GPS_DROPPED_DIST_FLAG_PCT,
    STRIDE_CALIB_MIN_CLEAN_S,
    STRIDE_SANITY_MIN_M,
    STRIDE_SANITY_MAX_M,
    CHART_MAX_PACE_MIN_PER_KM,
)
from src.utils.logger import get_logger

logger = get_logger("analysis.gps_quality")


def _delta_pace_min_km(prev: dict, cur: dict) -> float | None:
    """Темп дельты по device-дистанции, мин/км; None — дельта не оценивается.
    (Implied pace of one delta from device distance; None — not assessable.)"""
    if not (prev.get('time') and cur.get('time')):
        return None
    if prev.get('dist') is None or cur.get('dist') is None:
        return None
    delta_t = (cur['time'] - prev['time']).total_seconds() / 60
    delta_d = cur['dist'] - prev['dist']
    if delta_t <= 0 or delta_d <= 0:
        return None
    return delta_t / (delta_d / 1000)


def raw_gps_stats(trackpoints: list[dict], max_credible_pace: float) -> dict | None:
    """Счётчики качества по СЫРЫМ точкам (до очистки). None — трек слишком короткий.
    (Quality counters over RAW pre-cleaning trackpoints; None — track too short.)"""
    n_raw = len(trackpoints)
    if n_raw < GPS_QUALITY_MIN_POINTS:
        return None

    start_ts = trackpoints[0].get('time')
    no_position = 0
    impossible = 0
    assessed_deltas = 0
    bad_offsets_min: list[float] = []

    for i, tp in enumerate(trackpoints):
        bad = False
        if tp.get('lat') is None or tp.get('lon') is None:
            no_position += 1
            bad = True
        if i > 0:
            pace = _delta_pace_min_km(trackpoints[i - 1], tp)
            if pace is not None:
                assessed_deltas += 1
                if pace < max_credible_pace:
                    impossible += 1
                    bad = True
        if bad and start_ts and tp.get('time'):
            bad_offsets_min.append((tp['time'] - start_ts).total_seconds() / 60)

    dists = [tp['dist'] for tp in trackpoints if tp.get('dist') is not None]
    device_distance_km = (dists[-1] - dists[0]) / 1000 if len(dists) >= 2 else 0.0

    return {
        'n_raw': n_raw,
        'no_position_pct': round(no_position / n_raw, 3),
        'impossible_speed_pct': round(impossible / assessed_deltas, 3) if assessed_deltas else 0.0,
        'bad_first_min': round(min(bad_offsets_min), 1) if bad_offsets_min else None,
        'bad_last_min': round(max(bad_offsets_min), 1) if bad_offsets_min else None,
        'device_distance_km': round(device_distance_km, 3),
    }


def build_gps_quality(raw_stats: dict | None, rebuilt_dist_km: float) -> dict | None:
    """Собрать блок gps_quality и вынести вердикт unreliable.
    (Assemble the gps_quality block and decide the unreliable verdict.)"""
    if raw_stats is None:
        return None

    device_km = raw_stats['device_distance_km']
    dropped_pct = 0.0
    if device_km > 0:
        dropped_pct = max(0.0, (device_km - rebuilt_dist_km) / device_km)

    no_pos = raw_stats['no_position_pct']
    # Почти нет координат → дорожка/footpod: дистанция часов шаговая, GPS-критерии неприменимы
    # (Nearly no coordinates → treadmill/footpod: watch distance is stride-based, GPS criteria N/A)
    treadmill_like = no_pos >= GPS_NO_POSITION_TREADMILL_PCT
    unreliable = not treadmill_like and (
        raw_stats['impossible_speed_pct'] >= GPS_IMPOSSIBLE_SPEED_FLAG_PCT
        or dropped_pct >= GPS_DROPPED_DIST_FLAG_PCT
        or no_pos >= GPS_NO_POSITION_FLAG_PCT
    )

    quality = {
        'no_position_pct': no_pos,
        'impossible_speed_pct': raw_stats['impossible_speed_pct'],
        'dropped_dist_pct': round(dropped_pct, 3),
        'device_distance_km': device_km,
        'gps_distance_km': round(rebuilt_dist_km, 3),
        'bad_first_min': raw_stats['bad_first_min'],
        'bad_last_min': raw_stats['bad_last_min'],
        'unreliable': unreliable,
    }
    if unreliable:
        logger.warning(
            "GPS unreliable: no_pos=%.0f%% impossible=%.0f%% dropped=%.0f%% device=%.2fkm rebuilt=%.2fkm",
            no_pos * 100, raw_stats['impossible_speed_pct'] * 100, dropped_pct * 100,
            device_km, rebuilt_dist_km,
        )
    return quality


def clean_windows(trackpoints: list[dict], max_credible_pace: float) -> list[tuple[int, int]]:
    """Непрерывные спаны индексов с координатами и правдоподобным темпом дельт —
    опора для калибровки длины шага.
    (Contiguous index spans with coordinates and plausible delta pace — stride calibration base.)"""
    windows: list[tuple[int, int]] = []
    start: int | None = None
    for i in range(1, len(trackpoints)):
        prev, cur = trackpoints[i - 1], trackpoints[i]
        pace = _delta_pace_min_km(prev, cur)
        ok = (
            cur.get('lat') is not None and cur.get('lon') is not None
            and prev.get('lat') is not None and prev.get('lon') is not None
            and pace is not None
            and max_credible_pace <= pace <= CHART_MAX_PACE_MIN_PER_KM
        )
        if ok:
            if start is None:
                start = i - 1
        elif start is not None:
            windows.append((start, i - 1))
            start = None
    if start is not None:
        windows.append((start, len(trackpoints) - 1))
    return windows


def _steps_between(prev: dict, cur: dict) -> float:
    """Шаги за дельту: каденс (шаги/мин) × длительность. 0 — нет данных.
    (Steps over one delta: cadence (steps/min) × duration; 0 — no data.)"""
    if not (prev.get('time') and cur.get('time')):
        return 0.0
    cad = cur.get('cad')
    if cad is None or cad <= 0:
        return 0.0
    dt_min = (cur['time'] - prev['time']).total_seconds() / 60
    if dt_min <= 0:
        return 0.0
    return cad * dt_min


def estimate_distance_by_cadence(trackpoints: list[dict], windows: list[tuple[int, int]],
                                 fallback_stride_m: float | None = None) -> dict | None:
    """Оценка дистанции: интеграл каденса × длина шага, калиброванная по чистым окнам.
    quality: "estimate" — шаг откалиброван по этой тренировке; "rough" — дефолтный шаг.
    None — каденса нет, оценка невозможна.
    (Distance estimate: cadence integral × stride length calibrated on clean windows.)"""
    total_steps = 0.0
    for i in range(1, len(trackpoints)):
        total_steps += _steps_between(trackpoints[i - 1], trackpoints[i])
    if total_steps <= 0:
        return None

    # Калибровка шага по чистым окнам (stride calibration on clean windows)
    clean_dist_m = 0.0
    clean_steps = 0.0
    clean_dur_s = 0.0
    for ws, we in windows:
        first, last = trackpoints[ws], trackpoints[we]
        if first.get('dist') is not None and last.get('dist') is not None:
            clean_dist_m += max(0.0, last['dist'] - first['dist'])
        if first.get('time') and last.get('time'):
            clean_dur_s += (last['time'] - first['time']).total_seconds()
        for i in range(ws + 1, we + 1):
            clean_steps += _steps_between(trackpoints[i - 1], trackpoints[i])

    stride_m = None
    quality = None
    if clean_dur_s >= STRIDE_CALIB_MIN_CLEAN_S and clean_steps > 0:
        candidate = clean_dist_m / clean_steps
        if STRIDE_SANITY_MIN_M <= candidate <= STRIDE_SANITY_MAX_M:
            stride_m = candidate
            quality = 'estimate'
    if stride_m is None:
        if fallback_stride_m is None:
            return None
        stride_m = fallback_stride_m
        quality = 'rough'

    return {
        'source': 'cadence_estimate',
        'quality': quality,
        'steps': round(total_steps),
        'stride_m': round(stride_m, 3),
        'calib_clean_min': round(clean_dur_s / 60, 1),
        'estimated_km': round(total_steps * stride_m / 1000, 3),
    }
