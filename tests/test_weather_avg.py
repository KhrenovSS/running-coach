# #300 (07.09.2026): температура длинной пробежки — среднее часовых значений за интервал бега
from datetime import datetime

from src.parsers.weather import get_avg_temp_between, get_temp_at_time

_W = {"times": [f"2026-09-07T{h:02d}:00" for h in range(6, 14)],
      "temps": [10, 12, 14, 16, 18, 20, 22, 24], "precip": [None] * 8, "codes": [0] * 8}


def test_avg_over_run_window_vs_start_value():
    start = datetime(2026, 9, 7, 8, 0)
    end = datetime(2026, 9, 7, 10, 0)
    assert get_temp_at_time(_W, start) == 14                       # значение на старте
    assert get_avg_temp_between(_W, start, end) == 16              # (14+16+18)/3 за 08–10 ч


def test_avg_falls_back_to_start_when_no_points_in_window():
    start = datetime(2026, 9, 7, 20, 0)      # данных после 13:00 нет
    assert get_avg_temp_between(_W, start, start) == get_temp_at_time(_W, start)
    assert get_avg_temp_between(None, start, start) is None
