# Граничные тесты классификатора — фиксируют 5-путевое поведение и tempo-catch-all.
# Classifier boundary tests: lock the 5-way behavior incl. the tempo catch-all.
# NB: пороги настроены в Sprint 22 на реальных данных; менять их без размеченной выборки нельзя
# (BACKLOG: тюнинг порогов классификации требует labeled data).

from src.analysis.classify import classify_training


def test_interval():
    t, count = classify_training(
        var_count=6, time_in_zone={4: 20, 2: 20}, total_duration_min=45, max_hr=180,
        z4_plus_segments=[], avg_hr=160, oscillation_count=6, hr_correlated=True, segments_len=6,
    )
    assert t == "interval" and count >= 3


def test_long():
    t, _ = classify_training(
        var_count=0, time_in_zone={2: 85}, total_duration_min=100, max_hr=180,
        z4_plus_segments=[], avg_hr=135, oscillation_count=0, segments_len=1,
    )
    assert t == "long"


def test_recovery():
    t, _ = classify_training(
        var_count=0, time_in_zone={1: 30}, total_duration_min=30, max_hr=180,
        z4_plus_segments=[], avg_hr=118, oscillation_count=0, segments_len=1, avg_pace=7.2,
    )
    assert t == "recovery"


def test_easy():
    # avg_hr_pct > 0.70 (не recovery) но <= 0.75, z2 доминирует, длительность < 90 (не long)
    t, _ = classify_training(
        var_count=0, time_in_zone={2: 32}, total_duration_min=40, max_hr=190,
        z4_plus_segments=[], avg_hr=140, oscillation_count=0, segments_len=1, avg_pace=5.8,
    )
    assert t == "easy"


def test_tempo_catch_all():
    # умеренно-высокая интенсивность, не подходит ни под один спец-тип → tempo
    t, _ = classify_training(
        var_count=0, time_in_zone={3: 30, 4: 5}, total_duration_min=40, max_hr=190,
        z4_plus_segments=[], avg_hr=170, oscillation_count=0, segments_len=1, avg_pace=4.5,
    )
    assert t == "tempo"


def test_interval_guard_few_segments():
    # < 3 финальных сегментов → осцилляции обнуляются, не interval
    t, _ = classify_training(
        var_count=6, time_in_zone={4: 20}, total_duration_min=45, max_hr=180,
        z4_plus_segments=[], avg_hr=160, oscillation_count=6, hr_correlated=True, segments_len=2,
    )
    assert t != "interval"
