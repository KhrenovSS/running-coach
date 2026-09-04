# Резолвер ярлыка «план — назначение, факт — интенсивность» (plan-aware type) — 04.09.2026
import pytest

from src.analysis.type_resolution import resolve_training_type

LTHR, MAX = 156, 180          # порог качества по пульсу: 0.95·156 = 148.2


def _r(auto, plan, hr, dur=40, plan_dur=None):
    return resolve_training_type(auto, plan, avg_hr=hr, max_hr=MAX, lthr=LTHR,
                                 duration_min=dur, plan_duration_min=plan_dur)


@pytest.mark.parametrize("auto, plan, hr, dur, plan_dur, expected", [
    # без плана: catch-all tempo при спокойном пульсе — easy; час — long; интервалы держатся
    ("tempo", None, 138, 40, None, ("easy", "auto")),
    ("tempo", None, 150, 40, None, ("tempo", "auto")),
    ("easy", None, 130, 62, None, ("long", "auto")),
    ("interval", None, 150, 40, None, ("interval", "auto")),
    ("recovery", None, 120, 30, None, ("recovery", "auto")),
    ("tempo", "rest", 138, 40, None, ("easy", "auto")),
    # план — назначение
    ("easy", "long", 130, 60, 60, ("long", "plan")),
    ("easy", "long", 130, 48, 60, ("long", "plan")),          # ≥ 0.8 плановой
    ("easy", "long", 130, 40, 60, ("easy", "plan")),
    ("tempo", "easy", 138, 40, 35, ("easy", "plan")),          # инцидент #290
    ("tempo", "recovery", 125, 30, 30, ("recovery", "plan")),
    ("tempo", "recovery", 137, 30, 30, ("easy", "plan")),      # пульс выше восстановительного
    # факт — интенсивность
    ("tempo", "easy", 150, 40, 35, ("tempo", "auto")),
    ("interval", "easy", 150, 40, 35, ("interval", "auto")),
    ("tempo", "tempo", 150, 45, 45, ("tempo", "plan")),
    ("tempo", "interval", 152, 40, 40, ("interval", "plan")),
    ("tempo", "race", 160, 50, 50, ("race", "plan")),
    ("tempo", "tempo", 138, 45, 45, ("easy", "auto")),         # план темповая, пробежал спокойно
    # без пульса: назначение по плану, интенсивность неизвестна
    ("easy", "long", None, 60, 60, ("long", "plan")),
    ("tempo", "tempo", None, 45, 45, ("tempo", "auto")),
    ("tempo", None, None, 45, None, ("easy", "auto")),
])
def test_resolution_matrix(auto, plan, hr, dur, plan_dur, expected):
    assert _r(auto, plan, hr, dur, plan_dur) == expected


def test_quality_gate_falls_back_to_max_hr_without_lthr():
    assert resolve_training_type("tempo", "easy", avg_hr=155, max_hr=180, lthr=None,
                                 duration_min=40) == ("tempo", "auto")     # 0.85·180 = 153
    assert resolve_training_type("tempo", "easy", avg_hr=150, max_hr=180, lthr=None,
                                 duration_min=40) == ("easy", "plan")
