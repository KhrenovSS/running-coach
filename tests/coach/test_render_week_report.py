# Карточка «Итоги недели» (weekly report card) — src/coach/render_week_report.py, C8.1
from src.coach.render_week_report import render_week_report

_THIS = {"week_start": "2026-08-31", "km": 25.4, "minutes": 180, "runs": 4, "quality_runs": 1,
         "long_run_km": 8.5, "long_run_min": 60, "long_run_share": 0.33,
         "easy_time_share": 0.84, "hard_time_share": 0.16, "load_points": 62,
         "efficiency_delta_bpm": -3.0, "efficiency_n": 4, "cadence_median": 156,
         "pain_days": 0, "flags": {}, "monotony": 1.4, "strain": 86.8, "trained_days": 4}
_PREV = dict(_THIS, week_start="2026-08-24", km=25.3, runs=4, easy_time_share=0.71,
             hard_time_share=0.29, load_points=48)


def _report(**over):
    r = {"schema_version": 1, "week_start": "2026-08-31", "week_end": "2026-09-06",
         "week_in_progress": False, "this": _THIS, "prev": _PREV,
         "avg_prev": {"km": 22.0, "weeks": 4},
         "series": [{"week_start": "x", "km": k, "runs": 2} for k in (12, 14, 17, 25, 25, 25.4)],
         "targets": {"target_km": 28.0, "pct_of_target": 0.91, "mesocycle_week": 1,
                     "mesocycle_length": 4, "phase": "build", "hard_days_max": 1},
         "next_week": None, "acwr": 1.1,
         "adherence": {"planned": 4, "done": 3, "missed": 1, "adjusted": 1},
         "highlights": [], "concerns": [], "missing": []}
    r.update(over)
    return r


def test_full_card_layout():
    text = render_week_report(_report())
    assert text.splitlines() == [
        "*Итоги недели 31.08–06.09* · неделя 1/4 мезоцикла (рост)",
        "Объём: 25.4 км · 4 пробежки · 3 ч 00 мин · цель ~28 км (91%)",
        "К прошлой: +0.1 км (25.3) · среднее за 4 нед: 22.0 км",
        "Лёгкое время (Z1–2): 84% · цель ≥80% · прошлая 71% ✓",
        "Качество: 1 из 1 · длительная 8.5 км = 33% недели ⚠ (потолок 30%)",
        "Нагрузка: 62 баллов · прошлая 48 · монотонность 1.4 · острая/хроническая 1.10 (норма)",
        "Экономичность: пульс на своём темпе −3 уд/мин к базе (по 4 пробежкам) ✓",
        "План недели: выполнено 3 · пропущено 1 · скорректировано 1",
        "6 недель: 12 · 14 · 17 · 25 · 25 · 25 км",
    ]


def test_missing_data_lines_are_omitted():
    """Нет зон/базы/плана/цели — строк нет, карточка не врёт нулями."""
    this = dict(_THIS, easy_time_share=None, hard_time_share=None, load_points=None,
                monotony=None, strain=None, trained_days=1,
                efficiency_delta_bpm=None, efficiency_n=0, long_run_share=None, runs=1,
                km=5.0, minutes=30)
    text = render_week_report(_report(this=this, prev=None, avg_prev=None, targets={},
                                      acwr=None, adherence=None, series=[]))
    assert text == ("*Итоги недели 31.08–06.09*\n"
                    "Объём: 5.0 км · 1 пробежка · 30 мин\n"
                    "Качество: 1")


def test_empty_and_in_progress_week():
    empty = dict(_THIS, runs=0, km=0.0, minutes=0)
    text = render_week_report(_report(this=empty, adherence=None))
    assert "Пробежек на этой неделе не было" in text and "Объём" not in text
    text2 = render_week_report(_report(this=empty, week_in_progress=True, adherence=None))
    assert "неделя ещё идёт" in text2 and "Пробежек пока не было" in text2


def test_overload_and_high_acwr_marks():
    this = dict(_THIS, easy_time_share=0.6, hard_time_share=0.4, efficiency_delta_bpm=4.0)
    text = render_week_report(_report(this=this, acwr=1.45))
    assert "Лёгкое время (Z1–2): 60% · цель ≥80% · прошлая 71% ⚠" in text
    assert "острая/хроническая 1.45 (высокая ⚠)" in text
    assert "+4 уд/мин к базе (по 4 пробежкам) ⚠" in text


def test_efficiency_near_zero_reads_as_baseline():
    this = dict(_THIS, efficiency_delta_bpm=-0.3, efficiency_n=1)
    text = render_week_report(_report(this=this))
    assert "Экономичность: пульс на своём темпе на уровне базы (по 1 пробежке)" in text
    assert "−0" not in text
