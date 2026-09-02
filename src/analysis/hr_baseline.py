# Персональная базовая линия HR↔GAP-темп (Personal HR↔pace baseline) — DEV_PLAN §9 D2
#
# Чистая математика без БД: OLS-регрессия HR = a + b·gap_pace_min_km по км-точкам
# steady-тренировок. Отвечает на «пульс 149 на 6:10 — это нормально для меня?».
# Малая выборка → None, никакой ложной точности (graceful degradation).
# (Pure math; OLS over km-points of steady runs; small sample → no baseline.)

from __future__ import annotations

from src.config.constants import (
    BASELINE_HR_AT_PACE_BAND_MIN_KM,
    BASELINE_HR_PREDICT_MAX,
    BASELINE_HR_PREDICT_MIN,
    BASELINE_MIN_KM_LEN_M,
    BASELINE_MIN_POINTS,
    BASELINE_MIN_SESSIONS,
    BASELINE_PACE_BAND_MIN_POINTS,
    BASELINE_PACE_HR_BAND_BPM,
    BASELINE_PACE_PREDICT_MAX,
    BASELINE_PACE_PREDICT_MIN,
    BASELINE_SKIP_FIRST_KM,
    BASELINE_Z_FLAG,
)

BASELINE_VERSION = 1


def km_points(per_km: list[dict]) -> list[tuple[float, float]]:
    """Км-точки (gap_pace, hr) одной тренировки; первый км исключён (разогрев/колено).

    Хвостовой огрызок < BASELINE_MIN_KM_LEN_M — шумная точка полным весом в OLS
    (вклад в занижённый наклон #259) — исключается (#283); legacy-строки без
    km_len_m считаются полным км. (Short tail rows are excluded from the baseline.)
    """
    points = []
    for row in per_km[BASELINE_SKIP_FIRST_KM:]:
        if (row.get("km_len_m") or 1000.0) < BASELINE_MIN_KM_LEN_M:
            continue
        pace = row.get("gap_min_km") or row.get("pace_min_km")
        hr = row.get("avg_hr")
        if pace is not None and hr is not None:
            points.append((float(pace), float(hr)))
    return points


def fit_hr_pace_baseline(points: list[tuple[float, float]],
                         n_sessions: int) -> dict | None:
    """OLS: HR = a + b·pace. None при малой выборке или вырожденном фите.

    Санити-гейт: b < 0 обязателен (медленнее темп в мин/км → ниже пульс);
    b >= 0 = вырожденный фит, baseline отсутствует.
    """
    n = len(points)
    if n < BASELINE_MIN_POINTS or n_sessions < BASELINE_MIN_SESSIONS:
        return None
    mean_x = sum(p for p, _ in points) / n
    mean_y = sum(h for _, h in points) / n
    sxx = sum((p - mean_x) ** 2 for p, _ in points)
    if sxx <= 0:
        return None
    b = sum((p - mean_x) * (h - mean_y) for p, h in points) / sxx
    if b >= 0:
        return None  # degenerate_fit: быстрее должен быть выше пульс
    a = mean_y - b * mean_x
    rmse = (sum((h - (a + b * p)) ** 2 for p, h in points) / n) ** 0.5
    return {"a": round(a, 2), "b": round(b, 3), "rmse_bpm": round(rmse, 1),
            "n_points": n, "n_sessions": n_sessions, "version": BASELINE_VERSION}


def pace_at_hr_band(points: list[tuple[float, float]],
                    hr_ceiling: int) -> dict | None:
    """Эмпирический темп на пульсе: медиана км-точек с HR в полосе под потолком.

    (Empirical pace at HR: median pace of km-points whose HR falls in
    [ceiling − band, ceiling].) Без экстраполяции — инверсия OLS-линии занижает
    наклон (шум км-точек, межсессионные условия) и на потолке зоны даёт
    нереальный темп (инцидент смоука 26.08.2026). Мало точек в полосе или
    медиана вне санити-границ → None (нет ложной точности).
    """
    band = sorted(p for p, h in points
                  if hr_ceiling - BASELINE_PACE_HR_BAND_BPM <= h <= hr_ceiling)
    if len(band) < BASELINE_PACE_BAND_MIN_POINTS:
        return None
    mid = len(band) // 2
    pace = band[mid] if len(band) % 2 else (band[mid - 1] + band[mid]) / 2
    if not (BASELINE_PACE_PREDICT_MIN <= pace <= BASELINE_PACE_PREDICT_MAX):
        return None
    return {"pace_min_km": round(pace, 2), "n_points": len(band)}


def hr_at_pace_band(points: list[tuple[float, float]],
                    pace_min_km: float) -> dict | None:
    """Эмпирический пульс на темпе: медиана HR км-точек в полосе вокруг темпа.

    (Empirical HR at pace: median HR of km-points whose pace falls within
    ±band of the target.) Зеркало pace_at_hr_band — та же эмпирика вместо
    OLS-линии: её наклон занижен (BACKLOG #259), «ожидаемый пульс» по линии
    был бы смещён. Мало точек в полосе или медиана вне санити-границ → None.
    """
    band = sorted(h for p, h in points
                  if abs(p - pace_min_km) <= BASELINE_HR_AT_PACE_BAND_MIN_KM)
    if len(band) < BASELINE_PACE_BAND_MIN_POINTS:
        return None
    mid = len(band) // 2
    hr = band[mid] if len(band) % 2 else (band[mid - 1] + band[mid]) / 2
    if not (BASELINE_HR_PREDICT_MIN <= hr <= BASELINE_HR_PREDICT_MAX):
        return None
    return {"hr_bpm": int(round(hr)), "n_points": len(band)}


def baseline_deviation(baseline: dict | None, per_km: list[dict],
                       temp_shift_bpm: int | None = None) -> dict:
    """Отклонение сегодняшней тренировки от базовой линии (today vs baseline).

    temp_shift_bpm — ожидаемый сдвиг пульса от температуры (heat.expected_hr_shift_bpm):
    прибавляется к ожиданию, чтобы жара/прохлада не превращались в hr_above/below_baseline
    (исследование 02.09.2026: ~7 уд/мин между прохладным и тёплым днём на равном GAP-темпе).
    (Temperature shift is added to the expectation so weather does not masquerade as form.)
    """
    if not baseline:
        return {"available": False, "reason": "no_baseline"}
    points = km_points(per_km)
    if not points:
        return {"available": False, "reason": "no_km_points"}
    expected = sum(baseline["a"] + baseline["b"] * p for p, _ in points) / len(points)
    if temp_shift_bpm:
        expected += temp_shift_bpm
    actual = sum(h for _, h in points) / len(points)
    delta = actual - expected
    rmse = baseline.get("rmse_bpm") or 0.0
    z = round(delta / rmse, 1) if rmse > 0 else None
    return {
        "available": True, "reason": None,
        "expected_hr": round(expected, 1), "actual_hr": round(actual, 1),
        "delta_bpm": round(delta, 1), "z": z,
        "baseline_rmse_bpm": rmse,
        "temp_shift_bpm": temp_shift_bpm if temp_shift_bpm else 0,
        "baseline_n_sessions": baseline.get("n_sessions"),
        "baseline_computed_at": baseline.get("computed_at"),
    }


def deviation_flag(deviation: dict) -> str | None:
    """hr_above/below_baseline при |z| ≥ BASELINE_Z_FLAG (flag for LLM)."""
    z = deviation.get("z")
    if z is None:
        return None
    if z >= BASELINE_Z_FLAG:
        return "hr_above_baseline"
    if z <= -BASELINE_Z_FLAG:
        return "hr_below_baseline"
    return None
