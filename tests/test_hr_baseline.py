# Тесты базовой линии HR↔темп (HR↔pace baseline tests) — DEV_PLAN §9 D2

from src.analysis.hr_baseline import (
    baseline_deviation,
    deviation_flag,
    fit_hr_pace_baseline,
    hr_at_pace_band,
    km_points,
    pace_at_hr_band,
)
from src.analysis.hr_baseline import BASELINE_VERSION, detraining_hr_shift
from src.config.constants import (
    BASELINE_HR_PACE_SLOPE_DEFAULT,
    BASELINE_MIN_POINTS,
    BASELINE_MIN_SESSIONS,
    BASELINE_Z_FLAG,
    DETRAINING_VDOT_DROP_MAX_PCT,
)


def _points_by_law(n: int, a: float = 190.0, b: float = -8.0):
    """Точки по закону HR = a + b·pace с детерминированным «шумом»."""
    points = []
    for i in range(n):
        pace = 5.0 + (i % 20) * 0.1          # 5.0..6.9 мин/км
        noise = ((i * 7) % 5) - 2            # −2..+2 bpm
        points.append((pace, a + b * pace + noise))
    return points


def _sessions_by_law(n_sessions: int, per_session: int = 8, a: float = 190.0, b: float = -8.0,
                     session_shift: float = 0.0):
    """Сессии по закону HR = a + b·pace: у каждой свой средний темп, свой «день»
    (session_shift·(−1)^i — межсессионный сдвиг условий), внутри — шум ±2."""
    sessions = []
    for i in range(n_sessions):
        base = 5.5 + (i % 6) * 0.25
        day = session_shift * (1 if i % 2 else -1)
        pts = [(base + (k % 4) * 0.1, a + b * (base + (k % 4) * 0.1) + (((i + k) * 7) % 5) - 2 + day)
               for k in range(per_session)]
        sessions.append(pts)
    return sessions


def test_fit_recovers_slope():
    """OLS восстанавливает наклон закона (±15%); σ — сессионная, метод ols, версия 2."""
    baseline = fit_hr_pace_baseline(_sessions_by_law(8))
    assert baseline is not None
    assert abs(baseline["b"] - (-8.0)) / 8.0 < 0.15
    assert baseline["rmse_bpm"] < 3.0
    assert baseline["sigma_bpm"] <= baseline["rmse_bpm"]   # средние сессий шумят меньше км-точек
    assert baseline["n_points"] == 64 and baseline["n_sessions"] == 8
    assert baseline["method"] == "ols" and baseline["version"] == BASELINE_VERSION == 2


def test_fit_temperature_corrected_intercept():
    """#259: HR сессий с вычтенным температурным сдвигом — линия «при опорной температуре»:
    все сессии в жару (+6) → интерсепт как у закона, не +6; deviation в жару даёт delta ≈ 0."""
    sessions = _sessions_by_law(8)
    hot = [[(p, h + 6) for p, h in pts] for pts in sessions]
    plain = fit_hr_pace_baseline(sessions)
    corrected = fit_hr_pace_baseline(hot, temp_shifts=[6] * 8)
    assert abs(corrected["a"] - plain["a"]) < 0.5
    assert abs(corrected["b"] - plain["b"]) < 0.1
    uncorrected = fit_hr_pace_baseline(hot)                   # без сдвигов → линия выше на 6
    assert abs(uncorrected["a"] - plain["a"] - 6) < 0.5
    per_km = [{"km": k, "gap_min_km": 6.0, "avg_hr": 190 - 48 + 6} for k in range(1, 8)]
    dev = baseline_deviation(corrected, per_km, temp_shift_bpm=6)
    assert abs(dev["delta_bpm"]) < 1.5


def test_fit_session_sigma_reflects_day_to_day_spread():
    """σ для z — разброс сессионных средних вокруг линии: межсессионный сдвиг ±4
    (условия дня) даёт σ ≈ 4, хотя внутри сессии шум тот же."""
    calm = fit_hr_pace_baseline(_sessions_by_law(10))
    swingy = fit_hr_pace_baseline(_sessions_by_law(10, session_shift=4.0))
    assert calm["sigma_bpm"] < 2.0
    assert 3.0 <= swingy["sigma_bpm"] <= 5.0


def test_too_few_points_or_sessions_no_baseline():
    """Мало точек или сессий → None (никакой ложной точности)."""
    assert fit_hr_pace_baseline(_sessions_by_law(10, per_session=2)) is None   # 20 < 30 точек
    assert fit_hr_pace_baseline(_sessions_by_law(BASELINE_MIN_SESSIONS - 1, per_session=10)) is None
    assert BASELINE_MIN_POINTS == 30


def test_degenerate_or_attenuated_slope_falls_back_to_prior():
    """Наклон вне санити [−15, −4] (положительный или занижённый — ловушка #259) →
    прайор −8 (method=prior), интерсепт через среднюю точку данных; None не возвращаем."""
    rising = [[(5.0 + (i * 8 + k) * 0.05, 120 + i * 8 + k) for k in range(8)] for i in range(5)]
    baseline = fit_hr_pace_baseline(rising)
    assert baseline is not None and baseline["method"] == "prior"
    assert baseline["b"] == BASELINE_HR_PACE_SLOPE_DEFAULT
    flat = fit_hr_pace_baseline(_sessions_by_law(8, a=150.0, b=-2.0))
    assert flat["method"] == "prior" and flat["b"] == -8.0
    mean_pace = sum(p for pts in _sessions_by_law(8) for p, _ in pts) / 64
    assert abs((flat["a"] + flat["b"] * mean_pace) - (150 - 2 * mean_pace)) < 1.0


def test_deviation_measures_delta():
    """Сегодняшний HR +10 к закону → delta_bpm ≈ 10, z по сессионной σ, флаг при |z| ≥ порога."""
    baseline = fit_hr_pace_baseline(_sessions_by_law(8))
    per_km = [{"km": i + 1, "gap_min_km": 6.0, "avg_hr": 190 - 8 * 6.0 + 10}
              for i in range(6)]
    dev = baseline_deviation(baseline, per_km)
    assert dev["available"] is True
    assert abs(dev["delta_bpm"] - 10.0) < 1.5
    assert dev["sigma_bpm"] == baseline["sigma_bpm"]
    assert abs(dev["z"] - dev["delta_bpm"] / baseline["sigma_bpm"]) < 0.5
    assert dev["z"] >= BASELINE_Z_FLAG
    assert deviation_flag(dev) == "hr_above_baseline"


def test_deviation_v1_baseline_uses_rmse_as_sigma():
    """Совместимость: у v1-линии нет sigma_bpm → z по rmse_bpm."""
    v1 = {"a": 190.0, "b": -8.0, "rmse_bpm": 5.0, "n_sessions": 6, "version": 1}
    per_km = [{"km": k, "gap_min_km": 6.0, "avg_hr": 152} for k in range(1, 5)]  # закон 142 → +10
    dev = baseline_deviation(v1, per_km)
    assert dev["sigma_bpm"] == 5.0 and dev["z"] == 2.0


def test_detraining_shift_enters_expectation():
    """#289: после паузы ожидание выше на detraining_shift_bpm — тот же HR не даёт hr_above."""
    baseline = {"a": 190.0, "b": -8.0, "sigma_bpm": 3.0, "n_sessions": 6, "version": 2}
    per_km = [{"km": k, "gap_min_km": 6.0, "avg_hr": 149} for k in range(1, 6)]   # закон 142 → +7
    plain = baseline_deviation(baseline, per_km)
    assert deviation_flag(plain) == "hr_above_baseline"
    after_pause = baseline_deviation(baseline, per_km, detraining_shift_bpm=5)
    assert after_pause["expected_hr"] == 147.0 and after_pause["detraining_shift_bpm"] == 5
    assert deviation_flag(after_pause) is None
    assert plain["detraining_shift_bpm"] == 0


def test_detraining_hr_shift_formula_and_gates():
    """Сдвиг = |b|·темп·drop%·(1 − progress), кап 20 % VDOT; без паузы/линии/точек → None."""
    baseline = {"a": 190.0, "b": -8.0, "sigma_bpm": 3.0}
    per_km = [{"km": k, "gap_min_km": 6.0, "avg_hr": 140} for k in range(1, 6)]
    # 6 недель паузы: (42−5)·0.3 = 11.1 % → 8·6·0.111 ≈ 5.3 → 5
    six_weeks = {"available": True, "days_off": 42, "flag": True,
                 "expected_vdot_drop_pct": 11.1, "return_progress": 0.0}
    assert detraining_hr_shift(six_weeks, per_km, baseline) == 5
    # затухание: половина возврата → половина сдвига
    half = dict(six_weeks, return_progress=0.5)
    assert detraining_hr_shift(half, per_km, baseline) == 3
    assert detraining_hr_shift(dict(six_weeks, return_progress=1.0), per_km, baseline) is None
    # кап: 40 % «потери» считается как 20 %
    capped = dict(six_weeks, expected_vdot_drop_pct=40.0)
    assert detraining_hr_shift(capped, per_km, baseline) == round(8 * 6 * DETRAINING_VDOT_DROP_MAX_PCT / 100)
    # гейты
    assert detraining_hr_shift({"available": True, "days_off": 2, "flag": False}, per_km, baseline) is None
    assert detraining_hr_shift(six_weeks, per_km, None) is None
    assert detraining_hr_shift(six_weeks, [], baseline) is None
    assert detraining_hr_shift(None, per_km, baseline) is None


def test_no_baseline_deviation_absent():
    """Нет baseline → available=False с причиной."""
    dev = baseline_deviation(None, [{"km": 2, "gap_min_km": 6.0, "avg_hr": 150}])
    assert dev == {"available": False, "reason": "no_baseline"}


def test_km_points_skip_first_km():
    """Первый км исключается (разогрев + колено), None-строки отбрасываются."""
    per_km = [
        {"km": 1, "gap_min_km": 7.0, "avg_hr": 130},   # разогрев — исключён
        {"km": 2, "gap_min_km": 6.0, "avg_hr": 145},
        {"km": 3, "gap_min_km": None, "pace_min_km": 6.1, "avg_hr": 147},
        {"km": 4, "gap_min_km": 6.2, "avg_hr": None},  # нет HR — отброшен
    ]
    points = km_points(per_km)
    assert (6.0, 145.0) in points
    assert (6.1, 147.0) in points  # fallback на pace_min_km
    assert len(points) == 2


def test_km_points_excludes_short_tail_rows():
    """#283: хвостовой огрызок km_len_m < 500 м — шумная точка полным весом
    в OLS — исключается; legacy-строки без km_len_m считаются полным км."""
    per_km = [
        {"km": 1, "km_len_m": 1000, "gap_min_km": 7.0, "avg_hr": 130},  # первый — skip
        {"km": 2, "km_len_m": 1000, "gap_min_km": 6.0, "avg_hr": 145},
        {"km": 3, "km_len_m": 250, "gap_min_km": 4.5, "avg_hr": 160},   # хвост → вне baseline
        {"km": 4, "gap_min_km": 6.2, "avg_hr": 148},                    # legacy → полный км
        {"km": 5, "km_len_m": 500, "gap_min_km": 6.1, "avg_hr": 147},   # граница → включена
    ]
    points = km_points(per_km)
    assert (4.5, 160.0) not in points
    assert points == [(6.0, 145.0), (6.2, 148.0), (6.1, 147.0)]


def test_pace_at_hr_band_median():
    """Медиана темпа км-точек с HR в полосе [потолок−band, потолок].

    Закон HR = 190 − 8·pace: потолок 142 → полоса HR 132..142 = pace 6.0..7.25,
    медиана точек полосы ≈ середина. Инверсия OLS здесь не используется —
    она занижает наклон и экстраполирует в нереальный темп (смоук 26.08).
    """
    points = [(5.0 + i * 0.25, 190 - 8 * (5.0 + i * 0.25)) for i in range(16)]
    est = pace_at_hr_band(points, 142)
    assert est is not None
    assert 6.0 <= est["pace_min_km"] <= 7.25   # темп внутри полосы, не быстрее
    assert est["n_points"] >= 5


def test_pace_at_hr_band_none_branches():
    """Мало точек в полосе / медиана вне санити-границ → None."""
    assert pace_at_hr_band([], 140) is None
    few = [(6.0, 138.0)] * 4                       # < BASELINE_PACE_BAND_MIN_POINTS
    assert pace_at_hr_band(few, 140) is None
    absurd = [(2.0, 138.0)] * 6                    # 2:00/км — вне санити-границ
    assert pace_at_hr_band(absurd, 140) is None
    outside = [(6.0, 120.0)] * 10                  # весь пульс ниже полосы
    assert pace_at_hr_band(outside, 140) is None


def test_hr_at_pace_band_median():
    """Медиана HR км-точек в полосе темпа ±0.25 мин/км (зеркало pace_at_hr_band).

    Закон HR = 190 − 8·pace: темп 5.5 → полоса 5.25..5.75 → HR 144..148,
    медиана ≈ 146. Точки вне полосы (быстрые/медленные) на медиану не влияют.
    """
    points = [(5.0 + i * 0.1, 190 - 8 * (5.0 + i * 0.1)) for i in range(16)]
    points += [(4.0, 180.0), (8.0, 110.0)]         # вне полосы — не влияют
    est = hr_at_pace_band(points, 5.5)
    assert est is not None
    assert 144 <= est["hr_bpm"] <= 148             # HR внутри полосы темпа
    assert est["n_points"] >= 5


def test_hr_at_pace_band_even_median():
    """Чётное число точек в полосе → среднее двух центральных."""
    band = [(5.5, 140.0), (5.5, 142.0), (5.5, 144.0),
            (5.5, 146.0), (5.5, 148.0), (5.5, 150.0)]
    est = hr_at_pace_band(band, 5.5)
    assert est == {"hr_bpm": 145, "n_points": 6}   # (144+146)/2


def test_hr_at_pace_band_none_branches():
    """Мало точек в полосе / медиана вне санити-границ → None."""
    assert hr_at_pace_band([], 5.5) is None
    few = [(5.5, 145.0)] * 4                       # < BASELINE_PACE_BAND_MIN_POINTS
    assert hr_at_pace_band(few, 5.5) is None
    absurd = [(5.5, 230.0)] * 6                    # 230 bpm — вне санити-границ
    assert hr_at_pace_band(absurd, 5.5) is None
    outside = [(7.0, 135.0)] * 10                  # весь темп вне полосы ±0.25
    assert hr_at_pace_band(outside, 5.5) is None


def test_deviation_temperature_shift_moves_expectation():
    """Сдвиг от температуры входит в ожидание: жара не должна давать hr_above_baseline
    (temperature shift is added to expected HR; z shrinks accordingly)."""
    baseline = {"a": 200.0, "b": -10.0, "rmse_bpm": 4.0, "n_sessions": 6}
    per_km = [{"km": 1, "gap_min_km": 6.0, "avg_hr": 140},
              {"km": 2, "gap_min_km": 6.0, "avg_hr": 146},
              {"km": 3, "gap_min_km": 6.0, "avg_hr": 146}]
    plain = baseline_deviation(baseline, per_km)
    hot = baseline_deviation(baseline, per_km, temp_shift_bpm=6)
    assert plain["expected_hr"] == 140.0 and plain["delta_bpm"] == 6.0
    assert hot["expected_hr"] == 146.0 and hot["delta_bpm"] == 0.0
    assert hot["temp_shift_bpm"] == 6 and plain["temp_shift_bpm"] == 0
    # None/0 — без поправки (no shift when temperature unknown)
    assert baseline_deviation(baseline, per_km, temp_shift_bpm=None)["expected_hr"] == 140.0


# --- #264: ступени B/C ориентира темпа --------------------------------------------------

def _law_points(paces, a=190.0, b=-8.0):
    return [(p, a + b * p) for p in paces]


def test_band_result_carries_quality():
    from src.analysis.hr_baseline import pace_at_hr_band
    pts = _law_points([6.5 + i * 0.05 for i in range(12)])          # HR 138…133.6
    est = pace_at_hr_band(pts, 138)
    assert est is not None and est["quality"] == "band"


def test_adjusted_interpolates_below_data_with_local_slope():
    """Точки по закону 190 − 8·pace на HR 128–142; потолок 125 ниже массива → темп ≈ инверсии закона."""
    from src.analysis.hr_baseline import pace_at_hr_adjusted
    pts = _law_points([6.0 + i * 0.1 for i in range(18)])            # HR 142 … 128.4
    est = pace_at_hr_adjusted(pts, 125)
    assert est is not None and est["quality"] == "adjusted"
    assert abs(est["pace_min_km"] - (190 - 125) / 8) < 0.15          # 8.125
    assert abs(est["slope_used"] + 8.0) < 0.01


def test_adjusted_uses_default_slope_when_local_is_flat():
    """Занижённый наклон (ловушка #259) не проходит санити → дефолт −8."""
    from src.analysis.hr_baseline import pace_at_hr_adjusted
    from src.config.constants import BASELINE_HR_PACE_SLOPE_DEFAULT
    pts = _law_points([6.0 + i * 0.1 for i in range(18)], a=150.0, b=-2.0)   # HR 138 … 134.6
    est = pace_at_hr_adjusted(pts, 128)                              # Δ ≈ −8 → в пределах 15
    assert est is not None and est["slope_used"] == BASELINE_HR_PACE_SLOPE_DEFAULT


def test_adjusted_gates():
    from src.analysis.hr_baseline import pace_at_hr_adjusted
    pts = _law_points([6.0 + i * 0.1 for i in range(18)])
    assert pace_at_hr_adjusted(pts, 100) is None          # Δ > 15 → уровень C
    assert pace_at_hr_adjusted(pts[:3], 130) is None      # < 5 точек в полосе
    slow = _law_points([11.5, 11.6, 11.7, 11.8, 11.9, 12.0])    # HR ≈ 98…94
    assert pace_at_hr_adjusted(slow, 85) is None          # результат медленнее 12:00 → None, не клэмп


def test_typical_pace_median():
    from src.analysis.hr_baseline import typical_pace_median
    assert typical_pace_median([7.0, 7.4, 7.2, None, 30.0]) == {
        "pace_min_km": 7.2, "n_sessions": 3, "quality": "typical"}
    assert typical_pace_median([7.0, 7.4]) is None
