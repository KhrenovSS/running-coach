# Тесты метрик сессии M1 (Session metrics tests) — docs/coach/METRICS_GUIDE.md §4
#
# Чистые формулы на синтетических рядах: times_sec/hrs руками (как test_segment),
# сегменты — как в tests/coach/test_workout_detail_v2.SEGMENTS.

from src.analysis.session_metrics import (
    FLAG_QUALITY_VOLUME,
    FLAG_SEGMENT_TOO_LONG,
    cadence_block,
    collect_flags,
    easy_discipline,
    load_points,
    long_run_share,
    quality_volume,
    rpe_block,
    time_in_zones,
    warmup_block,
)

MAX_HR = 177  # zone_ceiling: Z1<118, Z2<141, Z3<153, Z4<165, Z5≥165 (при 177)


def _ramp(minutes: float, hr: int, *, step_sec: float = 10.0):
    """Ровный ряд точек: (times_sec, hrs) с постоянным пульсом."""
    n = int(minutes * 60 / step_sec) + 1
    return [i * step_sec for i in range(n)], [hr] * n


def _concat(*parts):
    """Склеить (times, hrs)-куски со сдвигом времени (concatenate series)."""
    times, hrs = [], []
    offset = 0.0
    for t, h in parts:
        times.extend(x + offset for x in t)
        hrs.extend(h)
        offset = times[-1] + 10.0
    return times, hrs


# --- M1.1: time_in_zones + easy_discipline ---

def test_time_in_zones_exact_minutes():
    times, hrs = _concat(_ramp(30, 130), _ramp(10, 150))  # 30' Z2 + 10' Z3
    z = time_in_zones(times, hrs, MAX_HR)
    assert z["available"] is True
    assert abs(z["minutes"]["z2"] - 30) < 1.0
    assert abs(z["minutes"]["z3"] - 10) < 1.0
    assert 0.72 < z["easy_time_pct"] < 0.78


def test_time_in_zones_no_max_hr_degrades():
    times, hrs = _ramp(20, 130)
    assert time_in_zones(times, hrs, None)["available"] is False


def test_easy_run_sliding_into_z3_flagged():
    """Инцидент по книгам (гайды 00/10): лёгкая «сползла» в Z3 → флаг."""
    times, hrs = _concat(_ramp(40, 130), _ramp(10, 150))  # 20% времени в Z3
    z = time_in_zones(times, hrs, MAX_HR)
    d = easy_discipline(z, "easy", tolerance=0.10)
    assert d["applicable"] is True and d["flag"] is True
    assert d["pct_above_z2"] > 0.15

    clean = easy_discipline(time_in_zones(*_ramp(40, 130), MAX_HR),
                            "easy", tolerance=0.10)
    assert clean["flag"] is False
    # для качественных типов метрика неприменима
    assert easy_discipline(z, "tempo", tolerance=0.10)["applicable"] is False


# --- M1.4: load_points ---

def test_load_points_weighted_by_zone():
    times, hrs = _concat(_ramp(30, 130), _ramp(10, 160))  # 30' Z2 + 10' Z4
    z = time_in_zones(times, hrs, MAX_HR)
    pts = load_points(z, {"z1": 0.2, "z2": 0.25, "z3": 0.5, "z4": 1.0, "z5": 1.5})
    assert pts["available"] is True
    assert abs(pts["points"] - (30 * 0.25 + 10 * 1.0)) < 1.0


# --- M1.5: quality_volume ---

def _per_km(hrs_by_km):
    return [{"pace_min_km": 6.0, "avg_hr": h} for h in hrs_by_km]


def test_quality_volume_caps_and_segment_length():
    # 6 км в Z4+ при неделе 30 км: потолок min(30·8%, 10) = 2.4 км → флаг;
    # плюс непрерывный Z4-отрезок 6 минут (> 5) → второй флаг
    times, hrs = _ramp(6, 160)
    z = time_in_zones(times, hrs, MAX_HR)
    qv = quality_volume(_per_km([160] * 6), z, 30.0, MAX_HR,
                        interval_max_pct=0.08, interval_max_km=10.0,
                        threshold_max_pct=0.10, threshold_max_km=24.0,
                        segment_max_min=5.0)
    assert qv["available"] is True
    assert FLAG_QUALITY_VOLUME in qv["flags"]
    assert FLAG_SEGMENT_TOO_LONG in qv["flags"]
    assert qv["longest_hard_segment_min"] > 5.0


def test_quality_volume_within_caps_no_flags():
    times, hrs = _concat(_ramp(30, 130), _ramp(4, 160))
    z = time_in_zones(times, hrs, MAX_HR)
    qv = quality_volume(_per_km([130] * 5 + [160]), z, 40.0, MAX_HR,
                        interval_max_pct=0.08, interval_max_km=10.0,
                        threshold_max_pct=0.10, threshold_max_km=24.0,
                        segment_max_min=5.0)
    assert qv["available"] is True and qv["flags"] == []


def test_quality_volume_empty_week_degrades():
    times, hrs = _ramp(10, 160)
    z = time_in_zones(times, hrs, MAX_HR)
    qv = quality_volume(_per_km([160]), z, 0.0, MAX_HR,
                        interval_max_pct=0.08, interval_max_km=10.0,
                        threshold_max_pct=0.10, threshold_max_km=24.0,
                        segment_max_min=5.0)
    assert qv["available"] is False and qv["reason"] == "no_week_volume"


# --- M1.6: long_run_share ---

def test_long_run_share_flags():
    over = long_run_share(12.0, 80.0, 30.0, "long", max_pct=0.30, max_min=150.0)
    assert over["applicable"] is True and over["flag"] is True   # 40% недели
    ok = long_run_share(8.0, 70.0, 30.0, "long", max_pct=0.30, max_min=150.0)
    assert ok["flag"] is False
    too_long = long_run_share(8.0, 160.0, 30.0, "long", max_pct=0.30, max_min=150.0)
    assert too_long["flag"] is True                              # >150 мин
    assert long_run_share(8.0, 70.0, 30.0, "easy",
                          max_pct=0.30, max_min=150.0)["applicable"] is False


# --- M1.7: cadence_block ---

def test_cadence_median_and_flags():
    segs = [{"avg_cadence": c} for c in (168, 170, 172)]
    c = cadence_block(segs, target=180, low=170, sanity_min=120)
    assert c["available"] is True and c["median_spm"] == 170 and c["flag"] is False
    lo = cadence_block([{"avg_cadence": 162}], target=180, low=170, sanity_min=120)
    assert lo["flag"] is True


def test_cadence_single_leg_sanity_gate():
    """Не-Coros источник без workaround: ~85 spm — не флаг, а «нет данных»."""
    c = cadence_block([{"avg_cadence": 85}], target=180, low=170, sanity_min=120)
    assert c["available"] is False
    assert c["reason"] == "cadence_suspect_single_leg"
    assert cadence_block([], target=180, low=170,
                         sanity_min=120)["available"] is False


# --- M1.8: rpe_block ---

def test_rpe_elevated_on_normal_background():
    r = rpe_block(8, [5, 5, 6, 5, 6], 0.3, delta=2, min_samples=5, z_max=1.0)
    assert r["available"] is True and r["flag"] is True
    ok = rpe_block(6, [5, 5, 6, 5, 6], 0.3, delta=2, min_samples=5, z_max=1.0)
    assert ok["flag"] is False


def test_rpe_gates_degrade():
    assert rpe_block(8, [5, 5], 0.3, delta=2, min_samples=5,
                     z_max=1.0)["available"] is False       # мало оценок
    assert rpe_block(8, [5] * 5, 1.5, delta=2, min_samples=5,
                     z_max=1.0)["available"] is False       # фон не в норме
    assert rpe_block(8, [5] * 5, None, delta=2, min_samples=5,
                     z_max=1.0)["available"] is False       # z неизвестен
    assert rpe_block(None, [5] * 5, 0.3, delta=2, min_samples=5,
                     z_max=1.0)["available"] is False       # нет своей оценки


# --- M1.9: warmup_block ---

def test_warmup_missing_flagged_for_quality():
    times, hrs = _ramp(20, 155)                              # темповая сразу в Z4
    w = warmup_block(times, hrs, MAX_HR, "tempo", window_min=10.0,
                     easy_share_min=0.5)
    assert w["applicable"] is True and w["flag"] is True
    times2, hrs2 = _concat(_ramp(10, 125), _ramp(15, 155))   # разминка есть
    w2 = warmup_block(times2, hrs2, MAX_HR, "tempo", window_min=10.0,
                      easy_share_min=0.5)
    assert w2["flag"] is False
    assert warmup_block(times, hrs, MAX_HR, "easy", window_min=10.0,
                        easy_share_min=0.5)["applicable"] is False


# --- §6: collect_flags ---

def test_collect_flags_gathers_all_blocks():
    computed = {
        "drift": {"flag": "high"},
        "heat": {"heat_flag": True},
        "gap": {"hilly": False},
        "hr_vs_baseline": {"available": False},
        "easy_discipline": {"applicable": True, "flag": True},
        "pace_stability": {"available": True, "flag": True},
        "quality_volume": {"available": True,
                           "flags": [FLAG_QUALITY_VOLUME, FLAG_SEGMENT_TOO_LONG]},
        "long_run": {"applicable": True, "flag": True},
        "cadence": {"available": True, "flag": True},
        "rpe": {"available": True, "flag": True},
        "warmup": {"applicable": True, "flag": True},
    }
    flags = collect_flags(computed)
    assert set(flags) == {"decoupling_high", "heat", "easy_run_too_hard",
                          "pace_unstable", FLAG_QUALITY_VOLUME,
                          FLAG_SEGMENT_TOO_LONG, "long_run_share_high",
                          "low_cadence", "rpe_elevated", "no_warmup"}
