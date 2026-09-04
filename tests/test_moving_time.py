# #286 Moving-time: паузы часов вычитаются из длительности, темпа, зон и км-точек (04.09.2026)
from datetime import timedelta

from src.analysis import process_trackpoints
from src.analysis.utils import pause_overlap_sec, pauses_to_offsets
from tests.helpers import build_trackpoints


def _iso(dt):
    return dt.isoformat()


def _track_with_stop(stop_after_idx=120, stop_sec=20):
    """Ровный трек, после точки k все времена сдвинуты на stop_sec (остановка часов)."""
    tps = build_trackpoints('long', duration_min=30, base_pace=6.5, hr=135)
    for tp in tps[stop_after_idx + 1:]:
        tp['time'] = tp['time'] + timedelta(seconds=stop_sec)
    pause = {"start": _iso(tps[stop_after_idx]['time']),
             "end": _iso(tps[stop_after_idx]['time'] + timedelta(seconds=stop_sec)),
             "duration_s": stop_sec}
    return tps, pause


def test_pause_helpers():
    assert pause_overlap_sec(0, 10, [(5, 8)]) == 3
    assert pause_overlap_sec(0, 10, [(-5, 2), (8, 20)]) == 4
    assert pause_overlap_sec(0, 10, [(20, 30)]) == 0
    assert pause_overlap_sec(0, 10, None) == 0
    tps = build_trackpoints('long', duration_min=5, base_pace=6.5, hr=135)
    t0 = tps[0]['time']
    offs = pauses_to_offsets([{"start": _iso(t0 + timedelta(seconds=30)),
                               "end": _iso(t0 + timedelta(seconds=50))},
                              {"start": None, "end": None}], t0)
    assert offs == [(30.0, 50.0)]


def test_short_stop_excluded_only_with_pause_list():
    """Остановка 20 с (< RECORDING_GAP_MAX_SEC): без списка пауз входит в длительность и темп,
    со списком — вычитается (moving-time), дистанция не меняется."""
    tps, pause = _track_with_stop()
    plain = process_trackpoints([dict(tp) for tp in tps], tps[0]['time'])
    moving = process_trackpoints([dict(tp) for tp in tps], tps[0]['time'], pauses=[pause])
    assert plain['total_distance_km'] == moving['total_distance_km']
    assert abs(plain['duration_minutes'] - moving['duration_minutes'] - 20 / 60) <= 0.1   # шаг округления 0.1 мин
    assert moving['avg_pace'] < plain['avg_pace']
    assert abs((plain['avg_pace'] - moving['avg_pace']) * moving['total_distance_km'] - 20 / 60) < 0.06   # округление темпа 0.01
    assert any(e.get('stage') == 'pauses' and e.get('pause_sec') == 20
               for e in moving.get('cleaning_log', []))


def test_long_gap_excluded_without_pause_list():
    """Разрыв 90 с (> 30 с) выпадает и без списка пауз — прежняя эвристика жива."""
    tps, _ = _track_with_stop(stop_sec=90)
    plain = process_trackpoints([dict(tp) for tp in tps], tps[0]['time'])
    ref = process_trackpoints(build_trackpoints('long', duration_min=30, base_pace=6.5, hr=135),
                              tps[0]['time'])
    assert abs(plain['duration_minutes'] - ref['duration_minutes']) < 0.15
