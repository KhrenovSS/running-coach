# Оркестратор анализа тренировок: GPS, сегментация, классификация, погода
# Training analysis orchestrator: GPS, segmentation, classification, weather

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from src.utils.logger import get_logger
from src.parsers.gps import clean_trackpoints
from src.parsers.weather import fetch_weather, get_weather_code_at_time, get_temp_at_time
from src.analysis.hr_zones import get_zone
from src.analysis.segment import build_time_in_zones, segment_by_pace
from src.analysis.segment_km import km_segment_fallback
from src.analysis.classify import classify_training
from src.analysis.oscillation import detect_pace_oscillations, compute_hr_lag_correlation
from src.analysis.utils import (
    format_duration, calc_elevation, find_timezone,
    compute_rolling_pace, interpolate_paces, smooth_paces,
    is_km_segmentation, serialize_trackpoints, build_hr_pace_series,
    smoothed_hr_peak, early_peak_suspect, pauses_to_offsets, TrackpointDict, AnalysisResult,
)
from src.analysis.gps_quality import (
    raw_gps_stats, build_gps_quality, clean_windows, estimate_distance_by_cadence,
)
from src.config import settings
from src.config.constants import STRIDE_DEFAULT_M

logger = get_logger("analysis")


def process_trackpoints(trackpoints: list[TrackpointDict], start_time_utc: datetime,
                          max_hr: int = settings.default_max_hr, max_credible_pace: float = 3.0,
                         lthr: int | None = None,
                         max_gps_jump_m: float = 100.0, min_hr_for_fast_pace: int = 130,
                         pace_gap: float = 1.0,
                         pauses: list[dict] | None = None,
                         interval_min_phase_duration: int = 60,
                         interval_min_phase_distance_m: int = 200,
                         interval_hr_lag_sec: int = 5,
                         interval_min_oscillations: int = 3) -> AnalysisResult | None:
    """
    Полный пайплайн анализа тренировки из трекпоинтов.
    Full training analysis pipeline from trackpoints.

    Пайплайн:
    1. Очистка GPS (gps.py)
    2. Накопительная дистанция
    3. Пульсовые зоны (segment.py → hr_zones.py)
    4. Сегментация по темпу + осцилляции (segment.py + oscillation.py)
    5. Классификация (classify.py)
    6. Осцилляции темпа + HR-lag (oscillation.py) — НОВОЕ
    7. Погода, каденс, высота
    8. HR/pace серия для графика
    """
    if len(trackpoints) < 2:
        return None

    if start_time_utc.tzinfo is None:
        start_time_utc = start_time_utc.replace(tzinfo=timezone.utc)

    # Квалиметрия и оценка по шагам — по СЫРЫМ точкам, до очистки и пересборки dist
    # (Quality counters & cadence estimate — over RAW points, before cleaning mutates dist)
    raw_stats = raw_gps_stats(trackpoints, max_credible_pace)
    distance_estimate = None
    if raw_stats is not None:
        distance_estimate = estimate_distance_by_cadence(
            trackpoints, clean_windows(trackpoints, max_credible_pace),
            fallback_stride_m=STRIDE_DEFAULT_M,
        )

    trackpoints, cleaning_log = clean_trackpoints(
        trackpoints, max_credible_pace, max_gps_jump_m, min_hr_for_fast_pace
    )

    if len(trackpoints) < 2:
        return _empty_result(start_time_utc, cleaning_log)

    # Накопительная дистанция с фильтрацией аномальных скачков
    # (Cumulative distance with anomalous jump filtering)
    orig_dists = [tp['dist'] for tp in trackpoints]
    cumulative = 0.0
    dropped_time_min = 0.0  # время выброшенных дельт — исключается из avg_pace (#277)
    for i, tp in enumerate(trackpoints):
        if orig_dists[i] is None:
            continue
        if i == 0:
            cumulative = orig_dists[i]
            tp['dist'] = cumulative
            continue
        prev_orig = orig_dists[i-1]
        if prev_orig is not None and tp['time'] is not None and trackpoints[i-1]['time'] is not None:
            raw_delta = orig_dists[i] - prev_orig
            t_delta = (tp['time'] - trackpoints[i-1]['time']).total_seconds() / 60
            if raw_delta > 0 and t_delta > 0:
                pace = t_delta / (raw_delta / 1000)
                if pace >= max_credible_pace:
                    cumulative += raw_delta
                else:
                    # Дистанция выброшена как GPS-мусор → её время тоже не должно
                    # попадать в темп, иначе avg_pace медленнее реальности (кейс №37)
                    # (dropped distance must drop its time too, or pace skews slow)
                    dropped_time_min += t_delta
            elif raw_delta > 0:
                cumulative += raw_delta
        tp['dist'] = cumulative

    hr_values = [tp['hr'] for tp in trackpoints if tp['hr'] is not None]
    distances = [tp['dist'] for tp in trackpoints if tp['dist'] is not None]
    if not distances or not hr_values:
        return _empty_result(start_time_utc, cleaning_log)

    total_dist_km = distances[-1] / 1000
    avg_hr = round(sum(hr_values) / len(hr_values))
    max_hr_val = max(hr_values)

    # Вердикт по качеству GPS: dropped_dist_pct требует пересобранной дистанции
    # (GPS quality verdict: dropped_dist_pct needs the rebuilt distance)
    gps_quality = build_gps_quality(raw_stats, total_dist_km)
    gps_unreliable = bool(gps_quality and gps_quality.get('unreliable'))

    start_ts = trackpoints[0]['time']
    times = []
    hrs = []
    dists = []
    if start_ts:
        for tp in trackpoints:
            if tp['time'] and tp['hr'] is not None and tp['dist'] is not None:
                t_sec = (tp['time'] - start_ts).total_seconds()
                times.append(t_sec)
                hrs.append(tp['hr'])
                dists.append(tp['dist'])

    # #286: паузы записи часов (device_summary.pauses) → длительность и темп = moving-time
    pauses_sec = pauses_to_offsets(pauses, trackpoints[0]['time']) if trackpoints else []
    time_in_zone, z4_plus_segments, total_duration_min = build_time_in_zones(
        trackpoints, max_hr, lthr=lthr, pauses_sec=pauses_sec or None)

    segments, var_count = segment_by_pace(
        trackpoints, max_hr, total_dist_km, lthr=lthr,
        min_oscillations=interval_min_oscillations,
        pace_gap=pace_gap,
        min_phase_duration_sec=interval_min_phase_duration,
        max_credible_pace=max_credible_pace,
    )

    # Осцилляции темпа + HR-lag корреляция (Pace oscillations + HR lag correlation)
    oscillation_count = 0
    hr_correlated = False
    if len(times) >= 10:
        raw_pace_for_osc = compute_rolling_pace(times, dists)
        filled_paces = interpolate_paces(raw_pace_for_osc)
        if filled_paces:
            smoothed_osc = smooth_paces(filled_paces)
            oscillation_count, _ = detect_pace_oscillations(
                smoothed_osc, times, distances=dists,
                pace_gap=pace_gap,
                min_phase_duration_sec=interval_min_phase_duration,
                min_phase_distance_m=interval_min_phase_distance_m,
            )
            _, hr_correlated = compute_hr_lag_correlation(
                times, filled_paces, hrs, lag_sec=interval_hr_lag_sec,
            )

    # Проверка: если сегменты — км-блоки, сбрасываем сигналы интервалов
    # (Check: if segments are km-based blocks, don't classify as interval)
    if is_km_segmentation(segments, total_dist_km):
        var_count = 0
        oscillation_count = 0
        hr_correlated = False

    # GPS недостоверен → темповые сигналы мусорные: классификация только по HR-зонам
    # (GPS unreliable → pace-derived signals are garbage: classify by HR zones only)
    if gps_unreliable:
        var_count = 0
        oscillation_count = 0
        hr_correlated = False

    # Время для темпа: выброшенные GPS-дельты исключены (#277, кейс №37 7.61→8.06);
    # при gps_unreliable оценка по шагам покрывает всю тренировку — полное время
    # (pace time excludes dropped-GPS deltas; the cadence estimate spans full duration)
    pace_time_min = (total_duration_min if gps_unreliable
                     else max(total_duration_min - dropped_time_min, 0.0))

    t_type, segments_count = classify_training(
        var_count, time_in_zone, total_duration_min, max_hr,
        z4_plus_segments, avg_hr, lthr=lthr,
        oscillation_count=oscillation_count,
        hr_correlated=hr_correlated,
        min_oscillations=interval_min_oscillations,
        segments_len=len(segments),
        avg_pace=(round(pace_time_min / total_dist_km, 2)
                  if total_dist_km > 0 and not gps_unreliable else None),
    )

    # Для не-интервалов — всегда км-блоки (по умолчанию),
    # для интервалов — oscillation/change-point сегменты
    # (For non-interval trainings — always km-blocks, for interval — oscillation segments)
    if t_type != 'interval':
        km_segments, km_var = km_segment_fallback(trackpoints, max_hr, total_dist_km, lthr=lthr)
        if km_segments:
            segments = km_segments
            var_count = km_var
            segments_count = len(km_segments)

    hr_pace_series = build_hr_pace_series(times, hrs, dists, var_count)

    positions = [(tp['lat'], tp['lon']) for tp in trackpoints if tp['lat'] is not None and tp['lon'] is not None]
    tz_name = find_timezone(positions)
    local_tz = ZoneInfo(tz_name) if tz_name else ZoneInfo(settings.timezone)
    begin_ts = start_time_utc

    avg_temperature = None
    weather_code = None
    total_elevation_gain = None
    total_elevation_loss = None
    altitudes_all = [tp['alt'] for tp in trackpoints if tp['alt'] is not None]
    if altitudes_all:
        total_elevation_gain, total_elevation_loss = calc_elevation(altitudes_all)

    if positions:
        mid_idx = len(positions) // 2
        center_lat, center_lon = positions[mid_idx]
        begin_local = start_time_utc.astimezone(local_tz)
        date_str = begin_local.strftime("%Y-%m-%d")
        weather = fetch_weather(center_lat, center_lon, date_str)
        if weather:
            avg_temperature = get_temp_at_time(weather, begin_local)
            weather_code = get_weather_code_at_time(weather, begin_local)
            cumul_min = 0.0
            for seg in segments:
                seg_mid_min = cumul_min + seg['duration_min'] / 2
                seg_dt = begin_local + timedelta(minutes=seg_mid_min)
                seg['temperature'] = get_temp_at_time(weather, seg_dt)
                seg['weather_code'] = get_weather_code_at_time(weather, seg_dt)
                cumul_min += seg['duration_min']

    # cad==0 — стояние: в средний каденс не входит (#282, единый контракт с cadence_block)
    all_cads = [tp['cad'] for tp in trackpoints if tp['cad']]
    avg_cadence = round(sum(all_cads) / len(all_cads)) if all_cads else None

    # GPS недостоверен → дистанция заменяется оценкой по шагам (решение владельца 01.09.2026),
    # GPS-число сохраняется в gps_quality.gps_distance_km; нет каденса → честное "unknown"
    # (GPS unreliable → distance replaced by the cadence estimate; original kept in gps_quality)
    if gps_unreliable:
        if distance_estimate is not None:
            gps_quality['distance'] = distance_estimate
            total_dist_km = distance_estimate['estimated_km']
        else:
            gps_quality['distance'] = {'source': 'gps', 'quality': 'unknown'}

    # Пик по скользящей медиане: и для адаптивного max_hr, и для UI (#280 —
    # одиночный спайк датчика не должен становиться «максимумом» тренировки)
    # (rolling-median peak feeds both adaptive max HR and the UI max)
    hr_peak = smoothed_hr_peak(hr_values)
    # #238: ранний пик на медленном темпе — глюк датчика: пик без первого окна + флаг
    from src.config.constants import (EARLY_PEAK_DELTA_BPM, EARLY_PEAK_PACE_SLACK_MIN_KM,
                                      EARLY_PEAK_WINDOW_SEC)
    peak_late, early_suspect = early_peak_suspect(
        times, hrs, dists, window_sec=EARLY_PEAK_WINDOW_SEC,
        pace_slack_min_km=EARLY_PEAK_PACE_SLACK_MIN_KM, delta_bpm=EARLY_PEAK_DELTA_BPM)
    if early_suspect and peak_late is not None:
        hr_peak = peak_late

    result = {
        'begin_ts': begin_ts,
        'total_distance_km': total_dist_km,
        'avg_heart_rate': avg_hr,
        'max_heart_rate': hr_peak or max_hr_val,
        'hr_peak_smoothed': hr_peak,
        'training_type': t_type,
        'training_type_auto': t_type,        # сырой ярлык — резолвер по плану пишет поверх (04.09.2026)
        'training_type_source': 'auto',
        'segments_count': segments_count,
        'duration_minutes': round(total_duration_min, 1),
        'segments_json': segments,
        'hr_pace_series': hr_pace_series,
        'avg_temperature': avg_temperature,
        'weather_code': weather_code,
        'elevation_gain': total_elevation_gain,
        'elevation_loss': total_elevation_loss,
        'avg_cadence': avg_cadence,
        'timezone': tz_name,
        'trackpoints_json': serialize_trackpoints(trackpoints),
        'avg_pace': round(pace_time_min / total_dist_km, 2) if total_dist_km > 0 else None,
        'gps_quality': gps_quality,
    }

    # suspect_flags — строки-причины (web/коуч ждут строки); количественный ущерб — в gps_quality
    # (suspect_flags are reason strings; quantitative damage lives in gps_quality)
    suspect_flags = []
    if cleaning_log:
        result['cleaning_log'] = cleaning_log
        suspect_flags = sorted({r for entry in cleaning_log for r in entry.get('reason', [])})
    if gps_unreliable:
        suspect_flags.append('gps_unreliable')
    if pauses_sec:
        # moving-time: сколько секунд пауз часов вычтено (в лог, не в колонку)
        result.setdefault('cleaning_log', [])
        result['cleaning_log'] = list(result['cleaning_log']) + [{
            'stage': 'pauses', 'reason': [],
            'pause_sec': round(sum(b - a for a, b in pauses_sec))}]
    if result['duration_minutes'] < 2.0 and result['total_distance_km'] > 0.3:
        suspect_flags.append('too_short')
    if early_suspect:
        suspect_flags.append('hr_early_peak')       # #238: ранний пик пульса отброшен
    if suspect_flags:
        result['suspect_flags'] = suspect_flags

    return result


def _empty_result(start_time_utc: datetime, cleaning_log: list) -> AnalysisResult:
    """Пустой результат при ошибке или слишком короткой тренировке"""
    return {
        'begin_ts': start_time_utc,
        'total_distance_km': 0,
        'avg_heart_rate': 0,
        'max_heart_rate': 0,
        'training_type': 'invalid',
        'segments_count': 0,
        'duration_minutes': 0,
        'segments_json': [],
        'hr_pace_series': [],
        'avg_temperature': None,
        'weather_code': None,
        'elevation_gain': 0,
        'elevation_loss': 0,
        'avg_cadence': None,
        'timezone': None,
        'cleaning_log': cleaning_log,
        'avg_pace': None,
        'gps_quality': None,
    }



