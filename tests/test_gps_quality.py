# Тесты квалиметрии GPS и оценки дистанции по шагам (GPS quality + cadence estimate)
# Кейс-мотиватор — сессия №42 (01.09.2026): 15 минут GPS-сбоя в начале тренировки.

import pytest

from src.analysis.gps_quality import (
    build_gps_quality,
    clean_windows,
    estimate_distance_by_cadence,
    raw_gps_stats,
)
from src.config.constants import (
    GPS_IMPOSSIBLE_SPEED_FLAG_PCT,
    GPS_QUALITY_MIN_POINTS,
    STRIDE_CALIB_MIN_CLEAN_S,
    STRIDE_DEFAULT_M,
    STRIDE_SANITY_MAX_M,
    STRIDE_SANITY_MIN_M,
)
from tests.helpers import build_gps_glitch_trackpoints

MAX_CREDIBLE_PACE = 3.0  # как в process_trackpoints по умолчанию (pipeline default)

# Геометрия кейса-42: 15 мин сбоя (5.7 м/с, 25% точек без координат) + 30 мин чисто
GLITCH_MIN = 15.0
CLEAN_MIN = 30.0
CLEAN_PACE = 6.9
CAD = 156


def _case42():
    return build_gps_glitch_trackpoints(
        glitch_min=GLITCH_MIN, clean_min=CLEAN_MIN, glitch_speed_ms=5.7,
        clean_pace=CLEAN_PACE, cad=CAD, no_pos_every=4)


# --- raw_gps_stats ---

def test_raw_stats_case42_counters():
    """Кейс-42: доля дыр координат ≈ 25% от первых 15 мин (≈8.3% трека),
    доля невозможных дельт ≥ порога флага, сбой локализован в начале."""
    tps = _case42()
    stats = raw_gps_stats(tps, MAX_CREDIBLE_PACE)
    assert stats is not None
    assert stats['n_raw'] == len(tps)
    # 25% * (15/45) = 0.0833 — точек без координат (no-position share)
    assert stats['no_position_pct'] == pytest.approx(0.083, abs=0.005)
    assert stats['impossible_speed_pct'] >= GPS_IMPOSSIBLE_SPEED_FLAG_PCT
    assert stats['impossible_speed_pct'] == pytest.approx(0.33, abs=0.02)
    # сбой — с первой минуты и до ~15-й (glitch spans the first ~15 minutes)
    assert stats['bad_first_min'] == 0.0
    assert 14.5 <= stats['bad_last_min'] <= 15.1
    # device-дистанция раздута сбоем: 5.13 км мусора + ~4.35 км чистых
    expected_device = (tps[-1]['dist'] - tps[0]['dist']) / 1000
    assert stats['device_distance_km'] == pytest.approx(expected_device, abs=0.01)
    assert stats['device_distance_km'] > 9.0


def test_raw_stats_short_track_returns_none():
    """Короче GPS_QUALITY_MIN_POINTS — квалиметрия честно не считается."""
    tps = _case42()[:GPS_QUALITY_MIN_POINTS - 1]
    assert raw_gps_stats(tps, MAX_CREDIBLE_PACE) is None
    assert build_gps_quality(None, 5.0) is None


# --- build_gps_quality: вердикт unreliable ---

def test_build_quality_case42_unreliable():
    tps = _case42()
    stats = raw_gps_stats(tps, MAX_CREDIBLE_PACE)
    clean_km = CLEAN_MIN / CLEAN_PACE  # пересобранная дистанция ≈ чистая часть
    quality = build_gps_quality(stats, clean_km)
    assert quality is not None
    assert quality['unreliable'] is True
    # пайплайн выбросил бы мусорную дистанцию сбоя → dropped >= порога
    assert quality['dropped_dist_pct'] > 0.2
    assert quality['gps_distance_km'] == pytest.approx(clean_km, abs=0.01)
    assert quality['device_distance_km'] == stats['device_distance_km']


def test_build_quality_clean_track_reliable():
    """45 мин чистого трека с координатами → unreliable=False."""
    tps = build_gps_glitch_trackpoints(glitch_min=0, clean_min=45, clean_pace=7.0)
    stats = raw_gps_stats(tps, MAX_CREDIBLE_PACE)
    assert stats['no_position_pct'] == 0.0
    assert stats['impossible_speed_pct'] == 0.0
    quality = build_gps_quality(stats, stats['device_distance_km'])
    assert quality['unreliable'] is False
    assert quality['dropped_dist_pct'] == 0.0


def test_build_quality_treadmill_guard():
    """Дорожка/footpod: координат нет вовсе, но device-дистанция правдоподобна
    → НЕ флагуется (гвард GPS_NO_POSITION_TREADMILL_PCT)."""
    tps = build_gps_glitch_trackpoints(glitch_min=0, clean_min=45, clean_pace=6.5)
    for tp in tps:
        tp['lat'] = tp['lon'] = None
    stats = raw_gps_stats(tps, MAX_CREDIBLE_PACE)
    assert stats['no_position_pct'] == 1.0
    quality = build_gps_quality(stats, stats['device_distance_km'])
    assert quality['unreliable'] is False


# --- estimate_distance_by_cadence ---

def test_estimate_case42_calibrated_stride():
    """Чистых 30 мин ≥ STRIDE_CALIB_MIN_CLEAN_S → quality='estimate';
    шаг ≈ дистанция чистой части / шаги в ней; итог — в честном диапазоне."""
    tps = _case42()
    windows = clean_windows(tps, MAX_CREDIBLE_PACE)
    assert windows, "чистая часть должна дать хотя бы одно окно"
    est = estimate_distance_by_cadence(tps, windows, fallback_stride_m=STRIDE_DEFAULT_M)
    assert est is not None
    assert est['source'] == 'cadence_estimate'
    assert est['quality'] == 'estimate'
    assert est['calib_clean_min'] >= STRIDE_CALIB_MIN_CLEAN_S / 60
    # шаг = чистая дистанция / чистые шаги (stride = clean distance / clean steps)
    ws, we = windows[-1]
    clean_dist_m = tps[we]['dist'] - tps[ws]['dist']
    clean_steps = CAD * (tps[we]['time'] - tps[ws]['time']).total_seconds() / 60
    assert est['stride_m'] == pytest.approx(clean_dist_m / clean_steps, rel=0.01)
    assert STRIDE_SANITY_MIN_M <= est['stride_m'] <= STRIDE_SANITY_MAX_M
    # 45 мин × 156 шаг/мин × ~0.93 м ≈ 6.5 км — между мусорными 9.5 и урезанными 4.3
    assert 6.0 <= est['estimated_km'] <= 7.0
    assert est['steps'] == pytest.approx(CAD * 45, rel=0.01)


def test_estimate_too_little_clean_time_falls_back_to_rough():
    """Чистого времени < STRIDE_CALIB_MIN_CLEAN_S → калибровки нет:
    с fallback-шагом quality='rough', без него — None."""
    tps = build_gps_glitch_trackpoints(glitch_min=10, clean_min=4)
    windows = clean_windows(tps, MAX_CREDIBLE_PACE)
    clean_s = sum((tps[we]['time'] - tps[ws]['time']).total_seconds()
                  for ws, we in windows)
    assert clean_s < STRIDE_CALIB_MIN_CLEAN_S
    est = estimate_distance_by_cadence(tps, windows, fallback_stride_m=STRIDE_DEFAULT_M)
    assert est['quality'] == 'rough'
    assert est['stride_m'] == STRIDE_DEFAULT_M
    assert estimate_distance_by_cadence(tps, windows, fallback_stride_m=None) is None


def test_estimate_without_cadence_returns_none():
    """Каденса нет вовсе → шаги не посчитать → честный None (не ложная точность)."""
    tps = build_gps_glitch_trackpoints(cad=None)
    windows = clean_windows(tps, MAX_CREDIBLE_PACE)
    assert estimate_distance_by_cadence(
        tps, windows, fallback_stride_m=STRIDE_DEFAULT_M) is None


def test_clean_windows_exclude_glitch_segment():
    """Окна калибровки не захватывают сбойную часть (кроме граничной точки)."""
    tps = _case42()
    windows = clean_windows(tps, MAX_CREDIBLE_PACE)
    n_glitch = int(GLITCH_MIN * 60)
    for ws, we in windows:
        assert ws >= n_glitch - 1   # граничная точка допустима (boundary point ok)
        assert we == len(tps) - 1 or we >= n_glitch
