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


def test_drift_v2_reports_bpm_and_pace_cv():
    """M1.2/M1.3: в drift-блоке есть чистый дрейф в bpm и CV темпа."""
    tps = build_trackpoints('long', duration_min=45, base_pace=6.0,
                            hr=140, hr_drift_bpm=20)
    per_km = [{"pace_min_km": 6.0}] * 7    # ровный темп — CV ≈ 0
    d = compute_cardiac_drift(*_series(tps), training_type='easy', per_km=per_km)
    assert d["applicable"] is True
    # линейный +20 bpm за 45' → между половинами рабочего окна ~9 bpm
    assert d["drift_bpm"] is not None and 5 < d["drift_bpm"] < 15
    assert d["hr_second_half"] > d["hr_first_half"]
    assert d["pace_cv"] is not None and d["pace_cv"] < 0.05


def test_hr_stability_flat_vs_drifting():
    """M1.2: SD/CV пульса растут при дрейфе, на ровном HR почти нулевые."""
    from src.analysis.effort import hr_stability
    flat = build_trackpoints('long', duration_min=40, base_pace=6.0, hr=140)
    drift = build_trackpoints('long', duration_min=40, base_pace=6.0,
                              hr=140, hr_drift_bpm=25)
    hs_flat = hr_stability(*_series(flat))
    hs_drift = hr_stability(*_series(drift))
    assert hs_flat["available"] and hs_drift["available"]
    assert hs_flat["sd"] < hs_drift["sd"]
    assert hs_drift["cv"] > 0


def test_pace_cv_public_works_without_drift():
    """M1.2: pace_cv доступен и когда drift неприменим (interval)."""
    from src.analysis.effort import pace_cv
    per_km = [{"pace_min_km": 6.0}, {"pace_min_km": 5.0}, {"pace_min_km": 7.0},
              {"pace_min_km": 5.2}, {"pace_min_km": 6.8}]
    cv = pace_cv(per_km)
    assert cv is not None and cv > 0.1
