# Тесты кардиодрейфа (cardiac drift tests) — DEV_PLAN §9 D2

from datetime import timedelta

from src.analysis.effort import compute_cardiac_drift, heat_block
from src.config.constants import DRIFT_HIGH_PCT, HEAT_TEMP_THRESHOLD_C
from tests.helpers import build_trackpoints


def _series(tps):
    t0 = tps[0]['time']
    times = [(tp['time'] - t0).total_seconds() for tp in tps]
    return (times, [tp['dist'] for tp in tps], [tp.get('hr') for tp in tps])


def _drift(tps, ttype='easy'):
    return compute_cardiac_drift(*_series(tps), training_type=ttype)


def test_hr_drift_detected_as_high():
    """Ровный темп 45 мин, HR линейно +20 bpm → drift выше high-порога.

    (+20 на базе 140 даёт ~6% decoupling; +15 дало бы ~4.6% — moderate.)
    """
    tps = build_trackpoints('long', duration_min=45, base_pace=6.0,
                            hr=140, hr_drift_bpm=20)
    d = _drift(tps)
    assert d["applicable"] is True
    assert d["drift_pct"] > DRIFT_HIGH_PCT
    assert d["flag"] == "high"


def test_constant_hr_no_drift():
    """Константный HR при ровном темпе → drift ≈ 0, flag=normal."""
    tps = build_trackpoints('long', duration_min=45, base_pace=6.0, hr=140)
    d = _drift(tps)
    assert d["applicable"] is True
    assert abs(d["drift_pct"]) < 1.0
    assert d["flag"] == "normal"


def test_interval_not_applicable():
    """Интервальная тренировка: дрейф неинформативен."""
    tps = build_trackpoints('interval')
    d = _drift(tps, ttype='interval')
    assert d["applicable"] is False
    assert d["reason"] == "interval"
    assert d["drift_pct"] is None


def test_short_run_not_applicable():
    """15-минутная пробежка короче steady-окна."""
    tps = build_trackpoints('long', duration_min=15, base_pace=6.0)
    d = _drift(tps)
    assert d["applicable"] is False
    assert d["reason"] == "too_short"


def test_no_hr_not_applicable():
    """Без пульса дрейф не считается."""
    tps = build_trackpoints('long', duration_min=45, base_pace=6.0)
    for tp in tps:
        tp['hr'] = None
    d = _drift(tps)
    assert d["applicable"] is False
    assert d["reason"] == "no_hr"


def test_pause_does_not_distort_drift():
    """3-минутная пауза (время идёт, дистанция нет) не искажает drift (±1 п.п.)."""
    clean = build_trackpoints('long', duration_min=45, base_pace=6.0,
                              hr=140, hr_drift_bpm=10)
    paused = build_trackpoints('long', duration_min=45, base_pace=6.0,
                               hr=140, hr_drift_bpm=10)
    mid = len(paused) // 2
    shift = timedelta(minutes=3)
    for tp in paused[mid:]:
        tp['time'] = tp['time'] + shift  # разрыв 3 мин → автопауза
    d_clean, d_paused = _drift(clean), _drift(paused)
    assert d_paused["applicable"] is True
    assert abs(d_paused["drift_pct"] - d_clean["drift_pct"]) <= 1.0


def test_heat_block_threshold():
    """heat_flag по порогу из констант; None-температура → None-флаг."""
    assert heat_block(HEAT_TEMP_THRESHOLD_C)["heat_flag"] is True
    assert heat_block(HEAT_TEMP_THRESHOLD_C - 1)["heat_flag"] is False
    assert heat_block(None) == {"temp_c": None, "heat_flag": None}
