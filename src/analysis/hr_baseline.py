# Персональная базовая линия HR↔GAP-темп (Personal HR↔pace baseline) — DEV_PLAN §9 D2
#
# Чистая математика без БД: OLS-регрессия HR = a + b·gap_pace_min_km по км-точкам
# steady-тренировок. Отвечает на «пульс 149 на 6:10 — это нормально для меня?».
# Малая выборка → None, никакой ложной точности (graceful degradation).
# (Pure math; OLS over km-points of steady runs; small sample → no baseline.)
#
# v2 (#259, 08.09.2026): HR км-точек берётся с вычтенным температурным сдвигом сессии
# (линия — «при опорной температуре», deviation прибавляет сдвиг дня один раз);
# σ для z — разброс СЕССИОННЫХ остатков, а не км-RMSE (deviation сравнивает средние
# сессии); наклон вне санити-границ → прайор BASELINE_HR_PACE_SLOPE_DEFAULT (method=prior).
# Замер на проде (35 сессий): pooled OLS −7.97 при эмпирических −8 — attenuation ушла с #283.

from __future__ import annotations

from src.config.constants import (
    BASELINE_HR_PACE_SLOPE_DEFAULT,
    BASELINE_HR_PACE_SLOPE_MAX,
    BASELINE_HR_PACE_SLOPE_MIN,
    BASELINE_PACE_ADJUST_MAX_BPM,
    BASELINE_PACE_WIDE_BAND_BPM,
    BASELINE_TYPICAL_MIN_SESSIONS,
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
    DETRAINING_VDOT_DROP_MAX_PCT,
)

BASELINE_VERSION = 2   # v1 — pooled OLS без темп. поправки, σ=км-RMSE; читатели v1 пересчитывают


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


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def fit_hr_pace_baseline(sessions: list[list[tuple[float, float]]],
                         temp_shifts: list[int | None] | None = None) -> dict | None:
    """OLS: HR − temp_shift = a + b·pace по км-точкам сессий. None при малой выборке.

    sessions — км-точки (pace, hr) по сессиям; temp_shifts — ожидаемый температурный сдвиг
    пульса каждой сессии (heat.expected_hr_shift_bpm), вычитается из HR перед фитом, чтобы
    линия описывала опорную температуру (deviation прибавляет сдвиг дня один раз, #259).
    Наклон вне [SLOPE_MIN, SLOPE_MAX] (в т.ч. b ≥ 0 — вырожденный фит) → прайор
    BASELINE_HR_PACE_SLOPE_DEFAULT, интерсепт через среднюю точку, method="prior".
    sigma_bpm — СКО сессионных остатков (σ для z в baseline_deviation); rmse_bpm — км-RMSE
    (справочно). (Pooled OLS on temperature-corrected HR; session-level sigma; slope prior
    when the fit fails the sanity gate.)
    """
    shifts = list(temp_shifts or [])
    corrected: list[list[tuple[float, float]]] = []
    for i, pts in enumerate(sessions):
        shift = shifts[i] if i < len(shifts) and shifts[i] else 0
        if pts:
            corrected.append([(p, h - shift) for p, h in pts])
    points = [pt for pts in corrected for pt in pts]
    n, n_sessions = len(points), len(corrected)
    if n < BASELINE_MIN_POINTS or n_sessions < BASELINE_MIN_SESSIONS:
        return None
    mean_x = _mean([p for p, _ in points])
    mean_y = _mean([h for _, h in points])
    sxx = sum((p - mean_x) ** 2 for p, _ in points)
    b = (sum((p - mean_x) * (h - mean_y) for p, h in points) / sxx) if sxx > 0 else 0.0
    method = "ols"
    if not (BASELINE_HR_PACE_SLOPE_MIN <= b <= BASELINE_HR_PACE_SLOPE_MAX):
        b, method = BASELINE_HR_PACE_SLOPE_DEFAULT, "prior"   # санити не пройден → прайор
    a = mean_y - b * mean_x
    rmse = (sum((h - (a + b * p)) ** 2 for p, h in points) / n) ** 0.5
    residuals = [_mean([h for _, h in pts]) - (a + b * _mean([p for p, _ in pts]))
                 for pts in corrected]
    sigma = (sum(r ** 2 for r in residuals) / n_sessions) ** 0.5
    return {"a": round(a, 2), "b": round(b, 3), "sigma_bpm": round(sigma, 1),
            "rmse_bpm": round(rmse, 1), "n_points": n, "n_sessions": n_sessions,
            "method": method, "version": BASELINE_VERSION}


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
    return {"pace_min_km": round(pace, 2), "n_points": len(band), "quality": "band"}


def _median(values: list[float]) -> float:
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def pace_at_hr_adjusted(points: list[tuple[float, float]], hr_ceiling: int) -> dict | None:
    """Уровень B (#264): широкая двусторонняя полоса + локальная поправка наклоном.

    Для низких зон полезные точки лежат ВЫШЕ потолка: медиана полосы сдвигается к потолку
    по локальному наклону HR~pace (санити-гейт; занижённый глобальный наклон #259 гейт
    закономерно не проходит → дефолт −8 bpm за мин/км). Δ пульса больше предохранителя
    или результат вне санити → None (не клэмп к границе — честнее упасть на уровень C).
    (Level B: wide band + local slope adjustment; no fabricated numbers.)
    """
    sample = [(p, h) for p, h in points if abs(h - hr_ceiling) <= BASELINE_PACE_WIDE_BAND_BPM]
    if len(sample) < BASELINE_PACE_BAND_MIN_POINTS:
        return None
    med_hr = _median([h for _, h in sample])
    med_pace = _median([p for p, _ in sample])
    delta = hr_ceiling - med_hr
    if abs(delta) > BASELINE_PACE_ADJUST_MAX_BPM:
        return None
    n = len(sample)
    mean_p = sum(p for p, _ in sample) / n
    mean_h = sum(h for _, h in sample) / n
    sxx = sum((p - mean_p) ** 2 for p, _ in sample)
    slope = BASELINE_HR_PACE_SLOPE_DEFAULT
    if sxx > 0:
        b = sum((p - mean_p) * (h - mean_h) for p, h in sample) / sxx
        if BASELINE_HR_PACE_SLOPE_MIN <= b <= BASELINE_HR_PACE_SLOPE_MAX:
            slope = b
    pace = med_pace + delta / slope
    if not (BASELINE_PACE_PREDICT_MIN <= pace <= BASELINE_PACE_PREDICT_MAX):
        return None
    return {"pace_min_km": round(pace, 2), "n_points": n, "quality": "adjusted",
            "hr_delta_bpm": round(delta, 1), "slope_used": round(slope, 2)}


def typical_pace_median(paces: list[float | None]) -> dict | None:
    """Уровень C (#264): медиана среднего темпа прошлых тренировок типа (без привязки к пульсу)."""
    clean = [p for p in paces if p is not None
             and BASELINE_PACE_PREDICT_MIN <= p <= BASELINE_PACE_PREDICT_MAX]
    if len(clean) < BASELINE_TYPICAL_MIN_SESSIONS:
        return None
    return {"pace_min_km": round(_median(clean), 2), "n_sessions": len(clean),
            "quality": "typical"}


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
                       temp_shift_bpm: int | None = None,
                       detraining_shift_bpm: int | None = None) -> dict:
    """Отклонение сегодняшней тренировки от базовой линии (today vs baseline).

    temp_shift_bpm — ожидаемый сдвиг пульса от температуры (heat.expected_hr_shift_bpm):
    прибавляется к ожиданию, чтобы жара/прохлада не превращались в hr_above/below_baseline
    (исследование 02.09.2026: ~7 уд/мин между прохладным и тёплым днём на равном GAP-темпе).
    detraining_shift_bpm — ожидаемый сдвиг после паузы (#289, detraining_hr_shift): форма
    ещё не вернулась — это не «пульс выше нормы». σ для z — sigma_bpm (v2, сессионная),
    у v1-линий — rmse_bpm. (Temperature and layoff shifts are added to the expectation so
    weather and detraining do not masquerade as form.)
    """
    if not baseline:
        return {"available": False, "reason": "no_baseline"}
    points = km_points(per_km)
    if not points:
        return {"available": False, "reason": "no_km_points"}
    expected = sum(baseline["a"] + baseline["b"] * p for p, _ in points) / len(points)
    if temp_shift_bpm:
        expected += temp_shift_bpm
    if detraining_shift_bpm:
        expected += detraining_shift_bpm
    actual = sum(h for _, h in points) / len(points)
    delta = actual - expected
    sigma = baseline.get("sigma_bpm") or baseline.get("rmse_bpm") or 0.0
    z = round(delta / sigma, 1) if sigma > 0 else None
    return {
        "available": True, "reason": None,
        "expected_hr": round(expected, 1), "actual_hr": round(actual, 1),
        "delta_bpm": round(delta, 1), "z": z,
        "sigma_bpm": sigma,
        "baseline_rmse_bpm": baseline.get("rmse_bpm"),
        "temp_shift_bpm": temp_shift_bpm if temp_shift_bpm else 0,
        "detraining_shift_bpm": detraining_shift_bpm if detraining_shift_bpm else 0,
        "baseline_n_sessions": baseline.get("n_sessions"),
        "baseline_computed_at": baseline.get("computed_at"),
    }


def detraining_hr_shift(detraining: dict | None, per_km: list[dict],
                        baseline: dict | None) -> int | None:
    """#289: ожидаемый сдвиг пульса на равном темпе после паузы (bpm, ≥ 0) или None.

    Потеря формы expected_vdot_drop_pct (VDOT-декай Дэниелса, гайд 46) переводится в
    эквивалент темпа (drop % от среднего GAP-темпа сессии) и далее в пульс наклоном линии
    |b|; гаснет линейно по return_progress (доля длины паузы, прошедшая после возврата —
    восстановление ≈ длине паузы, гайд 61). Кап DETRAINING_VDOT_DROP_MAX_PCT.
    Нет паузы/линии/точек → None. (Expected HR shift at equal pace after a layoff,
    fading over the return window; None when not applicable.)
    """
    if not detraining or not detraining.get("available") or not baseline:
        return None
    drop = detraining.get("expected_vdot_drop_pct")
    if not drop or drop <= 0:
        return None
    points = km_points(per_km)
    if not points:
        return None
    progress = float(detraining.get("return_progress") or 0.0)
    if progress >= 1.0:
        return None
    drop = min(float(drop), DETRAINING_VDOT_DROP_MAX_PCT)
    mean_pace = _mean([p for p, _ in points])
    shift = abs(baseline["b"]) * mean_pace * drop / 100.0 * (1.0 - progress)
    return int(round(shift))


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
