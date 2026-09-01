# Тесты F3 («M2.1 разбора»): восстановление между интервалами — HRR60,
# структурные лапы, гейты честной деградации, тренд пиков.
# (Interval-recovery / HRR tests: structural laps, honest-degradation gates, trend.)

from src.analysis.intervals import interval_recovery, structural_laps
from src.config.constants import HRR60_LOW_BPM, HRR_MIN_RECOVERY_S
from tests.helpers_intervals import (
    MAX_HR,
    T0,
    build_hr_series,
    build_laps,
    interval_workout,
)


def _run(segs, meta, *, max_hr=MAX_HR, ttype='interval'):
    times, hrs = build_hr_series(segs)
    return interval_recovery(times, hrs, max_hr,
                             laps=build_laps(meta), t0=T0, ttype=ttype)


# --- structural_laps: авто-км vs ручные круги --------------------------------

def test_structural_laps_auto_km_is_none():
    """5×1000 м + хвост 400 м — это авто-км разметка, не структура."""
    laps = [{'distance_m': 1000}] * 5 + [{'distance_m': 400}]
    assert structural_laps(laps) is None


def test_structural_laps_manual_marks_returned():
    """Ручные круги (2000/300/2000/300) возвращаются как есть."""
    laps = [{'distance_m': d} for d in (2000, 300, 2000, 300)]
    assert structural_laps(laps) is laps


def test_structural_laps_too_few_or_absent():
    """<3 лапов или их нет → None (одиночный ручной круг — не структура)."""
    assert structural_laps([{'distance_m': 2000}, {'distance_m': 300}]) is None
    assert structural_laps([]) is None
    assert structural_laps(None) is None


def test_structural_laps_auto_km_range_inclusive():
    """Границы диапазона 900–1100 включительно — всё ещё авто-км."""
    laps = [{'distance_m': 900}, {'distance_m': 1100}, {'distance_m': 250}]
    assert structural_laps(laps) is None


# --- interval_recovery по лапам ----------------------------------------------

def test_recovery_from_laps_good_hrr():
    """4×(180с работа до 162 / 120с отдых, −25 за 60с) → 4 повтора, медиана 25,
    флага нет; каждый повтор несёт пик/зону/мин HR отдыха."""
    res = _run(*interval_workout(drop60=25))
    assert res["available"] is True
    assert res["source"] == "laps"
    assert res["reps"] == 4
    assert res["hard_reps"] == 4              # пик 162 при 180 → Z4
    assert res["hrr60_median"] == 25.0
    assert res["hrr60_hard_median"] == 25.0
    assert res["flag"] is False               # 25 ≥ HRR60_LOW_BPM
    for i, r in enumerate(res["recoveries"], start=1):
        assert r["rep"] == i
        assert r["peak_hr"] == 162 and r["peak_zone"] == 4
        assert r["hrr60"] == 25
        assert r["min_hr"] == 130
        assert r["recovery_s"] == 120


def test_recovery_from_laps_poor_hrr_flags():
    """Падение всего 6 уд за 60с на Z4-повторах → poor_interval_recovery."""
    assert 6 < HRR60_LOW_BPM  # синтетика ниже порога флага
    res = _run(*interval_workout(drop60=6, rest_end=130))
    assert res["available"] is True
    assert res["hard_reps"] >= 2
    assert res["hrr60_hard_median"] == 6.0
    assert res["flag"] is True


def test_flag_boundary_at_threshold_not_raised():
    """Медиана ровно на пороге (12) — флага нет (строгое «ниже»)."""
    res = _run(*interval_workout(drop60=HRR60_LOW_BPM))
    assert res["available"] is True
    assert res["hrr60_hard_median"] == float(HRR60_LOW_BPM)
    assert res["flag"] is False


# --- гейты честной деградации -------------------------------------------------

def test_short_rest_reps_skipped():
    """Отдых 60с < HRR_MIN_RECOVERY_S → HRR60 не измерить, повторы пропущены."""
    assert 60 < HRR_MIN_RECOVERY_S
    res = _run(*interval_workout(rest_s=60))
    assert res == {"available": False, "reason": "few_reps",
                   "source": "laps", "reps_found": 0}


def test_easy_peak_zone_skipped():
    """Пик Z2 (140 при 180) на границе — это не «работа», повторы пропущены."""
    res = _run(*interval_workout(work_peak=140, drop60=10, rest_end=125))
    assert res["available"] is False
    assert res["reason"] == "few_reps"
    assert res["reps_found"] == 0


def test_hr_still_rising_past_boundary_skipped():
    """HR через 60с ВЫШЕ пика (граница неточна — работа кончилась позже):
    повтор не считается, ложного poor recovery нет."""
    segs = [(120, 120, 120)]
    meta = [(120, 400)]
    for _ in range(4):
        # после «конца работы» HR растёт ещё 40с до 170, потом падает
        segs += [(180, 130, 150), (40, 150, 170), (80, 170, 130)]
        meta += [(180, 800), (120, 200)]
    res = _run(segs, meta)
    assert res == {"available": False, "reason": "few_reps",
                   "source": "laps", "reps_found": 0}


def test_single_valid_rep_is_few_reps():
    """1 валидный отдых < HRR_MIN_REPS → few_reps с честным reps_found."""
    res = _run(*interval_workout(reps=1))
    assert res == {"available": False, "reason": "few_reps",
                   "source": "laps", "reps_found": 1}


def test_no_hr_degrades():
    """HR весь None или <2 точек → no_hr."""
    times, _ = build_hr_series([(300, 140, 140)])
    res = interval_recovery(times, [None] * len(times), MAX_HR,
                            laps=None, ttype='interval')
    assert res == {"available": False, "reason": "no_hr"}
    assert interval_recovery([0.0], [150], MAX_HR) == \
        {"available": False, "reason": "no_hr"}


def test_no_max_hr_degrades():
    times, hrs = build_hr_series([(300, 140, 160)])
    assert interval_recovery(times, hrs, None) == \
        {"available": False, "reason": "no_max_hr"}


def test_not_interval_without_laps_not_applicable():
    """Не интервальная и без ручной разметки → applicable=False/no_boundaries."""
    segs, _ = interval_workout()
    times, hrs = build_hr_series(segs)
    res = interval_recovery(times, hrs, MAX_HR, dists=[3.0 * t for t in times],
                            laps=None, ttype='easy')
    assert res == {"applicable": False, "reason": "no_boundaries"}
    # interval, но dists удержаны (gps_unreliable) и лапов нет → тоже no_boundaries
    res = interval_recovery(times, hrs, MAX_HR, dists=None,
                            laps=None, ttype='interval')
    assert res == {"applicable": False, "reason": "no_boundaries"}


# --- лаг пика и тренд ----------------------------------------------------------

def test_peak_lag_window_catches_late_peak():
    """Пик через 10с ПОСЛЕ границы лапа (кардиолаг) попадает в окно t+15."""
    segs = [(120, 120, 120)]
    meta = [(120, 400)]
    for _ in range(2):
        segs += [(180, 130, 160), (10, 160, 165), (60, 165, 135), (50, 135, 130)]
        meta += [(180, 800), (120, 200)]
    res = _run(segs, meta)
    assert res["available"] is True
    assert [r["peak_hr"] for r in res["recoveries"]] == [165, 165]
    assert res["hrr60_median"] == 25.0        # 165 − 140 (60с после границы)
    # тренд по 2 повторам не считается (HRR_TREND_MIN_REPS=3)
    assert res["peaks_trend_bpm_per_rep"] is None


def test_peaks_trend_positive_slope():
    """Пики 165→170→175 → тренд +5 уд/повтор (накопление усталости)."""
    segs = [(120, 120, 120)]
    meta = [(120, 400)]
    for peak in (165, 170, 175):
        segs += [(180, 130, peak), (60, peak, peak - 25), (60, peak - 25, 130)]
        meta += [(180, 800), (120, 200)]
    res = _run(segs, meta)
    assert res["available"] is True
    assert res["reps"] == 3
    assert res["peaks_trend_bpm_per_rep"] == 5.0
    assert res["flag"] is False               # падение 25 — восстановление в норме


# --- fallback: детектор осцилляций темпа ---------------------------------------

def test_oscillation_fallback_without_laps():
    """interval без лапов: границы из detect_pace_oscillations; HR с реалистичным
    спадом (высокий хвост после работы) → source='oscillations', повторы валидны."""
    dt = 5.0
    phases = [(6.0, 300, 'easy')] + \
        [(4.0, 180, 'work'), (6.0, 120, 'rec')] * 4 + [(6.5, 120, 'easy')]
    times, dists, hrs = [0.0], [0.0], [125]
    t, d = 0.0, 0.0
    for pace, dur, kind in phases:
        start = t
        while t + dt <= start + dur + 1e-9:
            t += dt
            d += dt / 60.0 / pace * 1000
            x = t - start
            hr = (min(170.0, 140 + 0.5 * x) if kind == 'work' else
                  max(140.0, 170 - 0.5 * x) if kind == 'rec' else 125.0)
            times.append(t)
            dists.append(d)
            hrs.append(round(hr))
    res = interval_recovery(times, hrs, MAX_HR, dists=dists,
                            laps=None, ttype='interval')
    assert res["source"] == "oscillations"
    assert res["available"] is True
    assert res["reps"] >= 2
    assert res["flag"] is False
    # детектор смещает границу на ~30-40с → пик ловится в высоком хвосте HR
    assert all(r["peak_zone"] >= 3 for r in res["recoveries"])
    assert all(r["hrr60"] > 0 for r in res["recoveries"])
