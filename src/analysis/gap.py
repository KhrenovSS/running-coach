# Grade-adjusted pace и рельеф (GAP & terrain) — DEV_PLAN §9 D2
#
# Чистая математика без БД: сглаживание высоты, энергостоимость уклона по
# Minetti et al. 2002 (J Appl Physiol 93:1039-1046, полином C(i) Дж/кг/м),
# GAP по километрам, сглаженный набор/спуск с гистерезисом.
# Существующий calc_elevation (naive-сумма дельт) сознательно не трогаем —
# BACKLOG #253. (Pure math, no DB; legacy calc_elevation left as is.)

from __future__ import annotations

from statistics import median

from src.config.constants import (
    ALT_SMOOTH_MEAN_WINDOW,
    ALT_SMOOTH_MEDIAN_WINDOW,
    ELEV_MIN_DELTA_M,
    GAP_MAX_GRADE,
    GAP_GRADE_WINDOW_M,
    GAP_MIN_ALT_COVERAGE,
    HILLY_GAIN_M_PER_KM,
)

# Коэффициенты полинома Minetti 2002: C(i) = 155.4i⁵ − 30.4i⁴ − 43.3i³ + 46.3i² + 19.5i + 3.6
_MINETTI = (155.4, -30.4, -43.3, 46.3, 19.5, 3.6)
_LEVEL_COST = 3.6  # C(0) — стоимость бега по плоскости (level running cost)


def minetti_cost(grade: float) -> float:
    """Энергостоимость бега при уклоне grade (доля, не %) — Minetti 2002."""
    i = max(-GAP_MAX_GRADE, min(GAP_MAX_GRADE, grade))
    c5, c4, c3, c2, c1, c0 = _MINETTI
    return c5 * i**5 + c4 * i**4 + c3 * i**3 + c2 * i**2 + c1 * i + c0


def gap_factor(grade: float) -> float:
    """Фактор поправки темпа: >1 в подъём (эквивалентный плоский темп быстрее)."""
    return max(0.1, minetti_cost(grade) / _LEVEL_COST)


def smooth_altitudes(alts: list[float | None]) -> list[float] | None:
    """Сглаживание высоты: forward-fill → медиана → среднее (median+mean smoothing).

    None при покрытии высотой ниже GAP_MIN_ALT_COVERAGE — GAP недоступен.
    """
    n = len(alts)
    if n == 0:
        return None
    known = sum(1 for a in alts if a is not None)
    if known / n < GAP_MIN_ALT_COVERAGE:
        return None
    filled: list[float] = []
    prev = next(a for a in alts if a is not None)
    for a in alts:
        prev = a if a is not None else prev
        filled.append(float(prev))

    def _roll(vals: list[float], window: int, fn) -> list[float]:
        half = window // 2
        return [fn(vals[max(0, i - half):i + half + 1]) for i in range(len(vals))]

    smoothed = _roll(filled, ALT_SMOOTH_MEDIAN_WINDOW, median)
    return _roll(smoothed, ALT_SMOOTH_MEAN_WINDOW, lambda w: sum(w) / len(w))


def smoothed_gain_loss(alts_smoothed: list[float]) -> tuple[float, float]:
    """Набор/спуск по сглаженной высоте с гистерезисом ELEV_MIN_DELTA_M."""
    gain = loss = 0.0
    if not alts_smoothed:
        return gain, loss
    ref = alts_smoothed[0]
    for a in alts_smoothed[1:]:
        delta = a - ref
        if delta >= ELEV_MIN_DELTA_M:
            gain += delta
            ref = a
        elif delta <= -ELEV_MIN_DELTA_M:
            loss += -delta
            ref = a
    return gain, loss


def local_grade_factors(dists: list[float],
                        alts_smoothed: list[float] | None) -> list[float]:
    """Посэмпловый gap_factor по локальному уклону (окно GAP_GRADE_WINDOW_M).

    Без высоты — единичные факторы (no altitude → neutral factors).
    """
    n = len(dists)
    if alts_smoothed is None or n == 0:
        return [1.0] * n
    factors: list[float] = []
    j0 = 0
    for i in range(n):
        # окно назад по дистанции (backward distance window)
        while dists[i] - dists[j0] > GAP_GRADE_WINDOW_M and j0 < i:
            j0 += 1
        d = dists[i] - dists[j0]
        if d <= 0:
            factors.append(1.0)
            continue
        grade = (alts_smoothed[i] - alts_smoothed[j0]) / d
        factors.append(gap_factor(grade))
    return factors


def compute_gap(times_sec: list[float], dists: list[float],
                hrs: list[int | None],
                alts: list[float | None]) -> dict:
    """GAP-блок computed_json: по-км уклон/темп/GAP/пульс + сводка.

    times_sec — секунды от старта; dists — кумулятивные метры.
    """
    alts_smoothed = smooth_altitudes(alts) if alts else None
    if alts_smoothed is None or len(dists) < 2:
        return {"available": False}

    gain, loss = smoothed_gain_loss(alts_smoothed)
    total_km = dists[-1] / 1000.0
    per_km: list[dict] = []
    km_start_idx = 0
    km_n = 1
    for i in range(1, len(dists)):
        if dists[i] >= km_n * 1000.0 or i == len(dists) - 1:
            seg_dist = dists[i] - dists[km_start_idx]
            seg_time = times_sec[i] - times_sec[km_start_idx]
            if seg_dist < 200 or seg_time <= 0:  # огрызок < 200 м не информативен
                break
            pace = (seg_time / 60.0) / (seg_dist / 1000.0)
            grade = (alts_smoothed[i] - alts_smoothed[km_start_idx]) / seg_dist
            seg_hrs = [h for h in hrs[km_start_idx:i + 1] if h is not None]
            per_km.append({
                "km": km_n,
                # фактическая длина строки: хвост 200–1000 м — не полный км (#283)
                # (actual row length: the tail row is shorter than a full km)
                "km_len_m": round(seg_dist),
                "grade_pct": round(grade * 100, 1),
                "pace_min_km": round(pace, 2),
                "gap_min_km": round(pace / gap_factor(grade), 2),
                "avg_hr": round(sum(seg_hrs) / len(seg_hrs)) if seg_hrs else None,
            })
            km_start_idx = i
            km_n += 1

    if not per_km:
        return {"available": False}
    # Средний темп/GAP — взвешены ДИСТАНЦИЕЙ строки: Σ(pace·d)/Σd = общее время/дистанция.
    # Прежнее взвешивание темпа самим темпом давало Σp²/Σp — смещение вверх (#278:
    # км 4:00+6:00 → 5.2 вместо 5:00). (distance-weighted mean = total time / total distance)
    weights = [r["km_len_m"] for r in per_km]
    gap_avg = sum(r["gap_min_km"] * w for r, w in zip(per_km, weights)) / sum(weights)
    pace_avg = sum(r["pace_min_km"] * w for r, w in zip(per_km, weights)) / sum(weights)
    gain_per_km = gain / total_km if total_km > 0 else 0.0
    return {
        "available": True,
        "gap_avg_min_km": round(gap_avg, 2),
        "avg_pace_min_km": round(pace_avg, 2),
        "elevation_gain_smoothed_m": round(gain),
        "elevation_loss_smoothed_m": round(loss),
        "gain_per_km_m": round(gain_per_km, 1),
        "hilly": gain_per_km >= HILLY_GAIN_M_PER_KM,
        "per_km": per_km,
    }
