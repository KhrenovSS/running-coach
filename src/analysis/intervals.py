# M2.1 разбора (F3): восстановление между интервалами — HRR60, min HR отдыха,
# тренд пиковых ЧСС по повторам (METRICS_GUIDE §5; Дэниелс — «полное восстановление
# между повторами, бег не через силу»).
# (Interval recovery analysis: HRR60, recovery min HR, peak-HR trend across reps.)
#
# Чистая математика без БД (инвариант D2): ряды/лапы приходят параметрами из
# workout_insights; каждый исход деградирует в {"available"/"applicable": False, reason}.
#
# Границы «конец работы → отдых» по приоритету источников:
# 1) структурные лапы часов (laps_json, F1) — владелец отбил круги кнопкой;
# 2) фазы detect_pace_oscillations — только для training_type == interval.

from __future__ import annotations

from datetime import datetime

from src.analysis.hr_zones import get_zone
from src.analysis.oscillation import detect_pace_oscillations
from src.analysis.utils import compute_rolling_pace, interpolate_paces, smooth_paces
from src.config.constants import (
    HRR60_LOW_BPM,
    HRR_FLAG_MIN_PEAK_ZONE,
    HRR_MIN_PEAK_ZONE,
    HRR_MIN_RECOVERY_S,
    HRR_MIN_REPS,
    HRR_PEAK_LAG_S,
    HRR_PEAK_WINDOW_S,
    HRR_SEARCH_TOL_S,
    HRR_TREND_MIN_REPS,
    HRR_WINDOW_S,
)

# Авто-км лапы: все непоследние в этом диапазоне → разметки структуры нет
# (auto-km laps: every non-final lap within this range means no manual structure)
AUTO_KM_MIN_M = 900
AUTO_KM_MAX_M = 1100


def structural_laps(laps: list[dict] | None) -> list[dict] | None:
    """Ручные круги часов; None — лапов нет или это авто-км разметка.
    (Manual watch laps; None when absent or the laps are just auto-km marks.)"""
    if not laps or len(laps) < 3:
        return None
    body = laps[:-1]  # последний лап — остаток дистанции и у авто-км
    if all(AUTO_KM_MIN_M <= (l.get('distance_m') or 0) <= AUTO_KM_MAX_M for l in body):
        return None
    return laps


def _lap_boundaries(laps: list[dict], t0: datetime) -> list[dict]:
    """Границы «конец лапа i → отдых = лап i+1» в секундах от старта трека.
    (Lap boundaries as seconds from track start; recovery = the following lap.)"""
    out = []
    for i in range(len(laps) - 1):
        nxt = laps[i + 1]
        st = nxt.get('start_time')
        rec_s = nxt.get('timer_s') or nxt.get('elapsed_s') or 0
        if not st:
            continue
        try:
            t_end = (datetime.fromisoformat(st) - t0).total_seconds()
        except (ValueError, TypeError):
            continue
        if t_end > 0:
            out.append({'t': t_end, 'recovery_s': rec_s})
    return out


def _oscillation_boundaries(times_sec: list[float], dists: list[float]) -> list[dict]:
    """Fallback: границы work→recovery из детектора осцилляций темпа.
    (Fallback boundaries from the pace-oscillation detector.)"""
    if len(times_sec) < 10:
        return []
    raw = compute_rolling_pace(times_sec, dists)
    smoothed = smooth_paces(interpolate_paces(raw))
    _, phases = detect_pace_oscillations(smoothed, times_sec, distances=dists)
    out = []
    for i in range(len(phases) - 1):
        cur, nxt = phases[i], phases[i + 1]
        if cur.get('type') == 'work' and nxt.get('type') == 'recovery':
            idx = min(cur.get('end_idx', 0), len(times_sec) - 1)
            out.append({'t': times_sec[idx],
                        'recovery_s': nxt.get('duration_sec') or 0})
    return out


def _hr_at(times_sec: list[float], hrs: list[int | None], t: float,
           tol_s: float = HRR_SEARCH_TOL_S) -> int | None:
    """HR ближайшей к t точки в пределах допуска (nearest HR sample within tolerance)."""
    best, best_dt = None, tol_s + 1
    for ts, hr in zip(times_sec, hrs):
        if hr is None:
            continue
        dt = abs(ts - t)
        if dt < best_dt:
            best, best_dt = hr, dt
        if ts > t + tol_s:
            break
    return best if best_dt <= tol_s else None


def _window_hrs(times_sec: list[float], hrs: list[int | None],
                t_from: float, t_to: float) -> list[int]:
    return [hr for ts, hr in zip(times_sec, hrs)
            if hr is not None and t_from <= ts <= t_to]


def _trend_slope(values: list[float]) -> float | None:
    """OLS-наклон по индексу повтора (bpm/повтор); None при <2 точках."""
    n = len(values)
    if n < 2:
        return None
    mx = (n - 1) / 2
    my = sum(values) / n
    den = sum((i - mx) ** 2 for i in range(n))
    if den == 0:
        return None
    return sum((i - mx) * (v - my) for i, v in enumerate(values)) / den


def interval_recovery(times_sec: list[float], hrs: list[int | None],
                      max_hr: int | None, *,
                      dists: list[float] | None = None,
                      laps: list[dict] | None = None,
                      t0: datetime | None = None,
                      ttype: str | None = None,
                      lthr: int | None = None) -> dict:
    """Блок computed_json «interval_recovery» (M2.1 разбора).

    HRR60 на каждой границе работа→отдых: пик = max HR последних
    HRR_PEAK_WINDOW_S работы, падение — за HRR_WINDOW_S отдыха. Гейты честной
    деградации: отдых ≥ HRR_MIN_RECOVERY_S, пик в зоне ≥ HRR_MIN_PEAK_ZONE,
    ≥ HRR_MIN_REPS валидных отдыхов.
    (HRR60 per work→rest boundary with honest degradation gates.)
    """
    if max_hr is None:
        return {"available": False, "reason": "no_max_hr"}
    if len(times_sec) < 2 or not any(h is not None for h in hrs):
        return {"available": False, "reason": "no_hr"}

    laps_s = structural_laps(laps)
    if laps_s and t0 is not None:
        boundaries = _lap_boundaries(laps_s, t0)
        source = "laps"
    elif ttype == "interval" and dists:
        boundaries = _oscillation_boundaries(times_sec, dists)
        source = "oscillations"
    else:
        # Не интервальная и без ручной разметки — блок неприменим
        # (not an interval workout and no manual lap marks)
        return {"applicable": False, "reason": "no_boundaries"}

    recoveries = []
    for b in boundaries:
        if b['recovery_s'] < HRR_MIN_RECOVERY_S:
            continue
        # Пик — с допуском ВПЕРЁД: пульс пикует через 10–30 c после конца работы
        # (cardiac lag: HR peaks shortly AFTER the work bout ends)
        peak_window = _window_hrs(times_sec, hrs,
                                  b['t'] - HRR_PEAK_WINDOW_S, b['t'] + HRR_PEAK_LAG_S)
        peak = max(peak_window) if peak_window else None
        if peak is None or get_zone(peak, max_hr, lthr) < HRR_MIN_PEAK_ZONE:
            continue  # граница easy-лапов (разминка/заминка) — не «работа»
        hr60 = _hr_at(times_sec, hrs, b['t'] + HRR_WINDOW_S)
        if hr60 is None:
            continue  # HR-дропаут в окне — честно пропускаем повтор
        if hr60 > peak:
            # Пульс через 60 c ВЫШЕ пика — граница неточна (работа кончилась позже,
            # чем решил детектор): повтор не считаем, иначе ложный «poor recovery»
            # (HR still rising past the boundary → unreliable phase edge, skip rep)
            continue
        rec_hrs = _window_hrs(times_sec, hrs, b['t'], b['t'] + b['recovery_s'])
        recoveries.append({
            "rep": len(recoveries) + 1,
            "peak_hr": peak,
            "peak_zone": get_zone(peak, max_hr, lthr),
            "hrr60": peak - hr60,
            "min_hr": min(rec_hrs) if rec_hrs else None,
            "recovery_s": round(b['recovery_s']),
        })

    if len(recoveries) < HRR_MIN_REPS:
        return {"available": False, "reason": "few_reps", "source": source,
                "reps_found": len(recoveries)}

    def _median(vals: list[float]) -> float:
        s = sorted(vals)
        n = len(s)
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2

    hrr60_median = _median([r["hrr60"] for r in recoveries])
    peaks = [float(r["peak_hr"]) for r in recoveries]
    trend = _trend_slope(peaks) if len(peaks) >= HRR_TREND_MIN_REPS else None

    # Флаг — только по повторам с пиком Z4+: после коротких Z3-стрид падение
    # пульса естественно мало, «плохим восстановлением» это не является
    # (flag only from hard reps: small drop after Z3 strides is physiological)
    hard = [r["hrr60"] for r in recoveries
            if r["peak_zone"] >= HRR_FLAG_MIN_PEAK_ZONE]
    flag = len(hard) >= HRR_MIN_REPS and _median(hard) < HRR60_LOW_BPM

    return {
        "available": True,
        "source": source,
        "reps": len(recoveries),
        "hard_reps": len(hard),
        "recoveries": recoveries,
        "hrr60_median": round(hrr60_median, 1),
        "hrr60_hard_median": round(_median(hard), 1) if hard else None,
        # Пики растут при повторах → накопление усталости (rising peaks → accumulating fatigue)
        "peaks_trend_bpm_per_rep": round(trend, 2) if trend is not None else None,
        "flag": flag,
    }
