# Детерминированные метрики сессии M1 (Session metrics) — docs/coach/METRICS_GUIDE.md §4
#
# Чистая математика без БД: ряды/пороги приходят параметрами, применяются в
# src/services/workout_insights.py. Каждый блок деградирует в
# {"available": False, "reason": ...} — исключений наружу нет (инвариант D2).
# (Pure math; thresholds are passed in; every block degrades, never raises.)

from __future__ import annotations

from statistics import median

from src.analysis.hr_zones import get_zone
from src.config.constants import RECORDING_GAP_MAX_SEC

# Единый словарь имён детерминированных флагов (METRICS_GUIDE §6).
# Значения обязаны существовать в enum FlagValue (src/coach/llm/schemas.py) либо
# в FLAG_TO_ASSESSMENT ниже. (Single source of deterministic flag names.)
FLAG_EASY_TOO_HARD = "easy_run_too_hard"
FLAG_PACE_UNSTABLE = "pace_unstable"
FLAG_QUALITY_VOLUME = "quality_volume_exceeded"
FLAG_SEGMENT_TOO_LONG = "interval_segment_too_long"
FLAG_LONG_RUN_SHARE = "long_run_share_high"
FLAG_LOW_CADENCE = "low_cadence"
FLAG_RPE_ELEVATED = "rpe_elevated"
FLAG_NO_WARMUP = "no_warmup"
FLAG_PLAN_INTENSITY = "plan_intensity_exceeded"
FLAG_PLAN_VOLUME = "plan_volume_exceeded"
FLAG_GPS_UNRELIABLE = "gps_unreliable"
FLAG_DEVICE_MISMATCH = "device_mismatch"
FLAG_POOR_INTERVAL_RECOVERY = "poor_interval_recovery"  # F3: HRR60 ниже порога
FLAG_HARD_DAYS_TOO_CLOSE = "hard_days_too_close"          # M4.1: качественные слишком часто
FLAG_POST_RACE_RECOVERY = "post_race_recovery_violated"   # M4.1: рано после гонки
FLAG_DOWNHILL_LOAD = "downhill_load_high"                 # M4.2: ударные спуски (колено)
FLAG_DETRAINING = "detraining_expected"                   # M4.3: пауза ≥6 дней

# Маппинг computed-флагов в значения enum assessment (§6.2, зафиксирован кодом:
# enum append-only, переименовывать decoupling_* задним числом нельзя).
FLAG_TO_ASSESSMENT = {
    "decoupling_high": "hr_drift_high",
    "decoupling_moderate": "hr_drift_high",
    FLAG_GPS_UNRELIABLE: "suspect_data",
    FLAG_DEVICE_MISMATCH: "suspect_data",
}

EASY_TYPES_M1 = ("easy", "recovery", "long")      # M1.1: где лёгкость обязательна
QUALITY_TYPES_M1 = ("tempo", "interval", "race")  # M1.9: где нужна разминка


def time_in_zones(times_sec: list[float], hrs: list[int | None],
                  max_hr: int | None, lthr: int | None = None,
                  pauses_sec: list[tuple[float, float]] | None = None) -> dict:
    """M1.1: точное время в зонах по трекпоинтам (посекундно, минуты).

    Дельта времени относится к зоне ПРЕДЫДУЩЕЙ точки (как build_time_in_zones).
    Возвращает также непрерывные Z4+-отрезки — сырьё для M1.5.
    (Exact per-second time in zones; z4+ continuous segments for M1.5.)
    """
    if max_hr is None:
        return {"available": False, "reason": "no_max_hr"}
    if len(times_sec) < 2 or not any(h is not None for h in hrs):
        return {"available": False, "reason": "no_hr"}
    minutes = {f"z{i}": 0.0 for i in range(1, 6)}
    z4_segments: list[dict] = []
    seg_min, seg_hr_sum = 0.0, 0.0
    from src.analysis.utils import pause_overlap_sec
    for i in range(1, len(times_sec)):
        dt_min = (times_sec[i] - times_sec[i - 1]) / 60.0
        if pauses_sec:
            dt_min -= pause_overlap_sec(times_sec[i - 1], times_sec[i], pauses_sec) / 60.0   # #286
        hr = hrs[i - 1]
        if dt_min <= 0 or hr is None or dt_min * 60 > RECORDING_GAP_MAX_SEC:
            # Разрыв записи или HR-дропаут РАЗРЫВАЕТ Z4-отрезок (#279): иначе
            # дропаут поверх настоящего восстановления склеивал два интервала
            # в один → ложный interval_segment_too_long
            # (gap/HR dropout breaks the Z4 segment — no more merged intervals)
            if seg_min > 0:
                z4_segments.append({"duration_min": round(seg_min, 1),
                                    "avg_hr": round(seg_hr_sum / seg_min)})
                seg_min, seg_hr_sum = 0.0, 0.0
            continue
        zone = get_zone(hr, max_hr, lthr)
        minutes[f"z{zone}"] += dt_min
        if zone >= 4:
            seg_min += dt_min
            seg_hr_sum += hr * dt_min
        elif seg_min > 0:
            z4_segments.append({"duration_min": round(seg_min, 1),
                                "avg_hr": round(seg_hr_sum / seg_min)})
            seg_min, seg_hr_sum = 0.0, 0.0
    if seg_min > 0:
        z4_segments.append({"duration_min": round(seg_min, 1),
                            "avg_hr": round(seg_hr_sum / seg_min)})
    total = sum(minutes.values())
    if total <= 0:
        return {"available": False, "reason": "no_hr"}
    easy_pct = (minutes["z1"] + minutes["z2"]) / total
    return {
        "available": True,
        "minutes": {k: round(v, 1) for k, v in minutes.items()},
        "total_min": round(total, 1),
        "easy_time_pct": round(easy_pct, 3),
        "z4_plus_segments": [s for s in z4_segments if s["duration_min"] >= 0.5],
    }


def easy_discipline(zones: dict, ttype: str | None, *, tolerance: float) -> dict:
    """M1.1: дисциплина лёгкого дня — «лёгкая не была лёгкой» (гайды 00/10)."""
    if ttype not in EASY_TYPES_M1:
        return {"applicable": False, "reason": "not_easy_type"}
    if not zones.get("available"):
        return {"applicable": False, "reason": zones.get("reason", "no_zones")}
    hard_pct = round(1.0 - zones["easy_time_pct"], 3)
    minutes_above = round(zones["total_min"] * hard_pct, 1)
    return {
        "applicable": True,
        "minutes_above_z2": minutes_above,
        "pct_above_z2": hard_pct,
        "flag": hard_pct > tolerance,
    }


def load_points(zones: dict, points_per_min: dict[str, float]) -> dict:
    """M1.4: баллы нагрузки сессии (Дэниелс, гайд 44)."""
    if not zones.get("available"):
        return {"available": False, "reason": zones.get("reason", "no_zones")}
    pts = sum(zones["minutes"].get(z, 0.0) * k for z, k in points_per_min.items())
    return {"available": True, "points": round(pts, 1)}


def quality_volume(per_km: list[dict] | None, zones: dict, week_km: float | None,
                   max_hr: int | None, *, interval_max_pct: float,
                   lthr: int | None = None,
                   interval_max_km: float, threshold_max_pct: float,
                   threshold_max_km: float, segment_max_min: float) -> dict:
    """M1.5: потолки качественного объёма (Дэниелс, гайд 44).

    Км по зонам — из per_km GAP-блока (avg_hr по километрам) — приближение
    до M3/ПАНО. Потолок: min(доля недели, абсолют). (Quality volume caps.)
    """
    if max_hr is None or not per_km:
        return {"available": False, "reason": "no_per_km" if max_hr else "no_max_hr"}
    if week_km is None or week_km <= 0:
        return {"available": False, "reason": "no_week_volume"}
    # Фактическая длина строки (#283): хвост 200–1000 м — не полный км;
    # legacy-строки без km_len_m считаем полным км (обратная совместимость)
    # (actual row length; legacy rows without km_len_m count as a full km)
    def _row_km(r: dict) -> float:
        return (r.get("km_len_m") or 1000.0) / 1000.0

    interval_km = sum(_row_km(r) for r in per_km
                      if r.get("avg_hr") and get_zone(r["avg_hr"], max_hr, lthr) >= 4)
    threshold_km = sum(_row_km(r) for r in per_km
                       if r.get("avg_hr") and get_zone(r["avg_hr"], max_hr, lthr) == 3)
    interval_cap = min(week_km * interval_max_pct, interval_max_km)
    threshold_cap = min(week_km * threshold_max_pct, threshold_max_km)
    longest = max((s["duration_min"] for s in zones.get("z4_plus_segments", [])),
                  default=0.0)
    flags = []
    if interval_km > interval_cap or threshold_km > threshold_cap:
        flags.append(FLAG_QUALITY_VOLUME)
    if longest > segment_max_min:
        flags.append(FLAG_SEGMENT_TOO_LONG)
    return {
        "available": True,
        "interval_km": round(interval_km, 1), "interval_cap_km": round(interval_cap, 1),
        "threshold_km": round(threshold_km, 1), "threshold_cap_km": round(threshold_cap, 1),
        "longest_hard_segment_min": round(longest, 1),
        "week_km": round(week_km, 1),
        "flags": flags,
    }


def long_run_share(session_km: float | None, duration_min: float | None,
                   week_km: float | None, ttype: str | None, *,
                   max_pct: float, max_min: float) -> dict:
    """M1.6: доля длительной в неделе (Дэниелс, гайд 45: ≤25–30% или 150 мин)."""
    if ttype != "long":
        return {"applicable": False, "reason": "not_long"}
    if not session_km or week_km is None or week_km <= 0:
        return {"applicable": False, "reason": "no_week_volume"}
    share = session_km / week_km
    over_time = duration_min is not None and duration_min > max_min
    return {
        "applicable": True,
        "share_of_week": round(share, 2),
        "duration_min": duration_min,
        "flag": share > max_pct or over_time,
    }


def cadence_block(segments: list[dict] | None, *, target: int, low: int,
                  sanity_min: int) -> dict:
    """M1.7: медианный каденс сегментов против цели ~180 (Дэниелс, гайд 46).

    Санити-гейт: медиана ниже sanity_min — вероятно «одна нога» (не-Coros
    источник без workaround) → нет данных, не ложный флаг.
    """
    cads = [s.get("avg_cadence") for s in (segments or [])
            if s.get("avg_cadence")]
    if not cads:
        return {"available": False, "reason": "no_cadence"}
    med = median(cads)
    if med < sanity_min:
        return {"available": False, "reason": "cadence_suspect_single_leg"}
    return {
        "available": True,
        "median_spm": round(med),
        "target_spm": target,
        "flag": med < low,
    }


def rpe_block(session_rpe: int | None, peer_rpes: list[int], hr_z: float | None, *,
              delta: int, min_samples: int, z_max: float) -> dict:
    """M1.8: «плохой день» — RPE выше нормы при обычных цифрах (гайд 40).

    Гейты: достаточно оценок того же типа; объективный фон в норме (|z| < z_max).
    """
    if session_rpe is None:
        return {"available": False, "reason": "no_rpe"}
    if len(peer_rpes) < min_samples:
        return {"available": False, "reason": "few_samples", "n": len(peer_rpes)}
    if hr_z is None:
        return {"available": False, "reason": "no_baseline_z"}
    if abs(hr_z) >= z_max:
        return {"available": False, "reason": "objective_background_off"}
    med = median(peer_rpes)
    return {
        "available": True,
        "rpe": session_rpe,
        "median_same_type": med,
        "n": len(peer_rpes),
        "flag": session_rpe - med >= delta,
    }


def warmup_block(times_sec: list[float], hrs: list[int | None],
                 max_hr: int | None, ttype: str | None, *,
                 window_min: float, easy_share_min: float,
                 lthr: int | None = None) -> dict:
    """M1.9: разминка перед качественной — доля Z1–2 в первом окне (гайд 41)."""
    if ttype not in QUALITY_TYPES_M1:
        return {"applicable": False, "reason": "not_quality_type"}
    if max_hr is None or len(times_sec) < 2:
        return {"applicable": False, "reason": "no_data"}
    window_sec = window_min * 60.0
    easy, total = 0.0, 0.0
    for i in range(1, len(times_sec)):
        if times_sec[i - 1] >= window_sec:
            break
        dt = min(times_sec[i], window_sec) - times_sec[i - 1]
        hr = hrs[i - 1]
        if dt <= 0 or hr is None:
            continue
        total += dt
        if get_zone(hr, max_hr, lthr) <= 2:
            easy += dt
    if total <= 0:
        return {"applicable": False, "reason": "no_hr"}
    share = easy / total
    return {
        "applicable": True,
        "easy_share_first_window": round(share, 2),
        "window_min": window_min,
        "flag": share < easy_share_min,
    }


def plan_vs_actual(plan: dict | None, ttype: str | None,
                   session_km: float | None, duration_min: float | None,
                   zones: dict, *, volume_tol: float,
                   intensity_tol: float,
                   distance_quality: str | None = None) -> dict:
    """M2.2: соответствие факта назначению (METRICS_GUIDE §5).

    Интенсивность — минуты выше плановой max_zone из точных зон; объём —
    превышение план+tol (недобор — не флаг, только volume_ratio).
    distance_quality — пометка «объём по оценке» при недостоверном GPS
    (estimate/rough/unknown из gps_quality.distance.quality).
    (Plan adherence: intensity above planned zone + volume overshoot.)
    """
    if not plan:
        return {"available": False, "reason": "no_plan"}
    out: dict = {
        "available": True,
        "planned": {k: plan.get(k) for k in
                    ("type", "max_zone", "duration_min", "distance_km",
                     "pace_min_km")},
        "type_match": plan.get("type") == ttype,
    }
    if distance_quality:
        out["distance_quality"] = distance_quality
    flags: list[str] = []

    max_zone = plan.get("max_zone")
    if max_zone and zones.get("available"):
        above = sum(v for z, v in zones["minutes"].items()
                    if int(z[1]) > max_zone)
        pct = above / zones["total_min"] if zones["total_min"] > 0 else 0.0
        out["minutes_above_planned_zone"] = round(above, 1)
        out["pct_above_planned_zone"] = round(pct, 3)
        if pct > intensity_tol:
            flags.append(FLAG_PLAN_INTENSITY)

    planned_min = plan.get("duration_min")
    planned_km = plan.get("distance_km")
    ratio = None
    if planned_min and duration_min:
        ratio = duration_min / planned_min
    elif planned_km and session_km:
        ratio = session_km / planned_km
    if ratio is not None:
        out["volume_ratio"] = round(ratio, 2)
        if ratio > 1.0 + volume_tol:
            flags.append(FLAG_PLAN_VOLUME)

    out["flags"] = flags
    return out


def collect_flags(computed: dict) -> list[str]:
    """Плоский список флагов из всех блоков computed_json (METRICS_GUIDE §6).

    Единственный источник детерминированных флагов для LLM и assessment.
    (The single flat flag list the LLM is allowed to use.)
    """
    from src.analysis.hr_baseline import deviation_flag

    flags: list[str] = []
    # GPS недостоверен — первым: разбор обязан начинаться с честности о данных
    # (GPS unreliable goes first: the review must lead with data honesty)
    if (computed.get("inputs", {}).get("gps_quality") or {}).get("unreliable"):
        flags.append(FLAG_GPS_UNRELIABLE)
    if (computed.get("inputs", {}).get("device_check") or {}).get("mismatch"):
        flags.append(FLAG_DEVICE_MISMATCH)
    drift = computed.get("drift", {})
    if drift.get("flag") == "high":
        flags.append("decoupling_high")
    elif drift.get("flag") == "moderate":
        flags.append("decoupling_moderate")
    if computed.get("heat", {}).get("heat_flag"):
        flags.append("heat")
    if computed.get("gap", {}).get("hilly"):
        flags.append("hilly")
    dev_flag = deviation_flag(computed.get("hr_vs_baseline", {}))
    if dev_flag:
        flags.append(dev_flag)
    if computed.get("easy_discipline", {}).get("flag"):
        flags.append(FLAG_EASY_TOO_HARD)
    if computed.get("pace_stability", {}).get("flag"):
        flags.append(FLAG_PACE_UNSTABLE)
    flags.extend(computed.get("quality_volume", {}).get("flags") or [])
    flags.extend(computed.get("plan_vs_actual", {}).get("flags") or [])
    if computed.get("long_run", {}).get("flag"):
        flags.append(FLAG_LONG_RUN_SHARE)
    if computed.get("cadence", {}).get("flag"):
        flags.append(FLAG_LOW_CADENCE)
    if computed.get("rpe", {}).get("flag"):
        flags.append(FLAG_RPE_ELEVATED)
    if computed.get("warmup", {}).get("flag"):
        flags.append(FLAG_NO_WARMUP)
    if computed.get("interval_recovery", {}).get("flag"):
        flags.append(FLAG_POOR_INTERVAL_RECOVERY)
    flags.extend(computed.get("week_structure", {}).get("flags") or [])
    if computed.get("downhill", {}).get("flag"):
        flags.append(FLAG_DOWNHILL_LOAD)
    if computed.get("detraining", {}).get("flag"):
        flags.append(FLAG_DETRAINING)
    return flags
