# Тесты базовой линии HR↔темп (HR↔pace baseline tests) — DEV_PLAN §9 D2

from src.analysis.hr_baseline import (
    baseline_deviation,
    deviation_flag,
    fit_hr_pace_baseline,
    hr_at_pace_band,
    km_points,
    pace_at_hr_band,
)
from src.config.constants import BASELINE_MIN_POINTS, BASELINE_MIN_SESSIONS


def _points_by_law(n: int, a: float = 190.0, b: float = -8.0):
    """Точки по закону HR = a + b·pace с детерминированным «шумом»."""
    points = []
    for i in range(n):
        pace = 5.0 + (i % 20) * 0.1          # 5.0..6.9 мин/км
        noise = ((i * 7) % 5) - 2            # −2..+2 bpm
        points.append((pace, a + b * pace + noise))
    return points


def test_fit_recovers_slope():
    """OLS восстанавливает наклон закона (±15%)."""
    baseline = fit_hr_pace_baseline(_points_by_law(60), n_sessions=8)
    assert baseline is not None
    assert abs(baseline["b"] - (-8.0)) / 8.0 < 0.15
    assert baseline["rmse_bpm"] < 3.0
    assert baseline["n_points"] == 60


def test_too_few_points_or_sessions_no_baseline():
    """Мало точек или сессий → None (никакой ложной точности)."""
    assert fit_hr_pace_baseline(_points_by_law(BASELINE_MIN_POINTS - 1),
                                n_sessions=10) is None
    assert fit_hr_pace_baseline(_points_by_law(60),
                                n_sessions=BASELINE_MIN_SESSIONS - 1) is None


def test_degenerate_positive_slope_rejected():
    """Положительный наклон (быстрее → ниже пульс?!) → вырожденный фит → None."""
    points = [(5.0 + i * 0.05, 120 + i) for i in range(40)]  # HR растёт с pace
    assert fit_hr_pace_baseline(points, n_sessions=10) is None


def test_deviation_measures_delta():
    """Сегодняшний HR +10 к закону → delta_bpm ≈ 10, z положительный."""
    baseline = fit_hr_pace_baseline(_points_by_law(60), n_sessions=8)
    per_km = [{"km": i + 1, "gap_min_km": 6.0, "avg_hr": 190 - 8 * 6.0 + 10}
              for i in range(6)]
    dev = baseline_deviation(baseline, per_km)
    assert dev["available"] is True
    assert abs(dev["delta_bpm"] - 10.0) < 1.5
    assert dev["z"] > 0
    assert deviation_flag(dev) == "hr_above_baseline"


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
