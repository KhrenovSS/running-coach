# Сегментация по лапам часов (#302, 08.09.2026)
from datetime import timedelta, timezone

from src.analysis import process_trackpoints
from src.analysis.segment_laps import lap_segments, lap_windows
from tests.helpers import build_trackpoints
from tests.helpers_intervals import T0, build_laps


def _track(minutes: float = 20.0, hr: int = 140):
    """Ровный трек с datetime-временами от T0 (как отдаёт FIT-парсер, но aware)."""
    return build_trackpoints('long', duration_min=minutes, base_pace=6.0, hr=hr,
                             start_time=T0)


def test_lap_windows_end_time_next_start_and_duration():
    laps = build_laps([(600, 1600), (18, 62), (120, 280)])
    laps[0]["end_time"] = (T0 + timedelta(seconds=590)).isoformat()   # явный конец главнее
    w = lap_windows(laps, T0)
    assert w[0] == (0.0, 590.0)
    assert w[1] == (600.0, 618.0)                # конец — старт следующего
    assert w[2] == (618.0, 738.0)                # последний — по timer_s
    laps[1].pop("start_time")
    assert lap_windows(laps, T0)[1] is None       # без старта — окна нет


def test_lap_windows_align_naive_and_aware():
    """FIT даёт naive UTC трекпоинты, лапы — aware ISO: окна одинаковые."""
    laps = build_laps([(60, 200), (60, 200), (60, 200)])
    naive_t0 = T0.replace(tzinfo=None)
    assert lap_windows(laps, naive_t0) == lap_windows(laps, T0)


def test_structured_laps_become_segments_with_watch_distance():
    """7×(18 с ускорение / 120 с трусца) после разминки: сегменты = лапы, дистанция и время из лапа
    (даже при мусорном GPS), ускорение 0.06 км с зоной по пульсу."""
    meta = [(300, 900)] + [(18, 62), (120, 280)] * 7 + [(120, 350)]
    laps = build_laps(meta)
    tps = _track(minutes=sum(d for d, _ in meta) / 60 + 1)
    for tp in tps:
        tp["dist"] = 0.0                          # GPS «сломан»: дистанция трека нулевая
    segs = lap_segments(laps, tps, max_hr=180)
    assert segs is not None and len(segs) == len(meta) == 16
    stride = segs[1]
    assert stride["source"] == "laps" and stride["lap"] == 2
    assert stride["distance_km"] == 0.06 and stride["duration_min"] == 0.3
    assert stride["pace_min_km"] == round(0.3 / 0.062, 2)
    assert stride["zone"] in (1, 2, 3, 4, 5) and stride["avg_hr"] == 140
    assert stride["avg_cadence"] is not None      # каденс — из среза точек
    assert segs[0]["distance_km"] == 0.9 and segs[-1]["duration_min"] == 2.0


def test_auto_km_laps_or_few_laps_return_none():
    tps = _track()
    auto = build_laps([(360, 1000), (360, 1000), (360, 1000), (120, 300)])
    assert lap_segments(auto, tps, max_hr=180) is None
    assert lap_segments(build_laps([(60, 200), (60, 200)]), tps, max_hr=180) is None
    assert lap_segments(None, tps, max_hr=180) is None
    assert lap_segments(build_laps([(60, 200)] * 3), [], max_hr=180) is None


def test_process_trackpoints_uses_laps_and_keeps_them_for_easy():
    """Полный пайплайн: структурные лапы → segments_json из лапов, тип easy их не затирает
    км-блоками; авто-км лапы и отсутствие лапов — прежние км-сегменты."""
    meta = [(300, 900)] + [(18, 62), (120, 280)] * 7 + [(120, 350)]
    tps = _track(minutes=sum(d for d, _ in meta) / 60 + 1)
    res = process_trackpoints(tps, tps[0]["time"], max_hr=180, laps=build_laps(meta))
    assert res["training_type"] != "interval"                 # ускорения — часть лёгкого дня
    assert res["segments_count"] == 16
    assert all(s["source"] == "laps" for s in res["segments_json"])
    assert res["segments_json"][1]["distance_km"] == 0.06
    plain = process_trackpoints(tps, tps[0]["time"], max_hr=180)
    assert "source" not in plain["segments_json"][0]
    auto = process_trackpoints(tps, tps[0]["time"], max_hr=180,
                               laps=build_laps([(360, 1000)] * 3 + [(120, 300)]))
    assert "source" not in auto["segments_json"][0]
    assert len(auto["segments_json"]) == len(plain["segments_json"])


def test_lap_row_carries_end_time_and_provenance():
    """#302: _lap_row сохраняет конец лапа и провенанс (trigger/intensity/wkt_step_index); None опущены."""
    from datetime import datetime
    from src.parsers.fit_parser import _lap_row
    row = _lap_row({"start_time": datetime(2026, 9, 1, 12, 39, 56), "timestamp": datetime(2026, 9, 1, 13, 4, 56),
                    "total_distance": 12504.0, "total_timer_time": 1500.0, "total_elapsed_time": 1500.0,
                    "avg_heart_rate": 134, "lap_trigger": "manual", "intensity": "warmup", "wkt_step_index": 0})
    assert row["end_time"].startswith("2026-09-01T13:04:56")
    assert row["trigger"] == "manual" and row["intensity"] == "warmup" and row["wkt_step_index"] == 0
    assert _lap_row({"total_distance": 1000.0}).get("trigger") is None


def test_implausible_lap_pace_drops_distance_but_keeps_time_and_hr():
    """GPS-сбой 01.09: часы насчитали в лапе 12.5 км за 25 мин (2:00/км) — дистанция/темп сегмента
    не выдумываются (None, distance_unreliable), время и пульс остаются; остальные лапы обычные."""
    meta = [(1500, 12504), (18, 62), (120, 280), (18, 62), (120, 280)]
    tps = _track(minutes=sum(d for d, _ in meta) / 60 + 1)
    segs = lap_segments(build_laps(meta), tps, max_hr=180)
    assert segs is not None and len(segs) == 5
    bad = segs[0]
    assert bad["distance_km"] is None and bad["pace"] is None and bad["pace_min_km"] is None
    assert bad["distance_unreliable"] is True and bad["duration_min"] == 25.0 and bad["avg_hr"] == 140
    assert segs[1]["distance_km"] == 0.06 and "distance_unreliable" not in segs[1]
