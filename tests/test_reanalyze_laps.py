# #302: кэш-путь reanalyze передаёт сохранённые laps_json в process_trackpoints
from datetime import timedelta

from src.analysis.utils import serialize_trackpoints
from src.services.reanalyze import reanalyze_training
from tests.helpers import build_trackpoints, build_training_session, make_user
from tests.helpers_intervals import T0, build_laps


def test_reanalyze_cache_path_segments_by_stored_laps(db_session):
    user = make_user(db_session, chat_id=93777, email="laps-93777@example.com")
    meta = [(300, 900)] + [(18, 62), (120, 280)] * 5 + [(120, 350)]
    tps = build_trackpoints('long', duration_min=sum(d for d, _ in meta) / 60 + 1,
                            base_pace=6.0, hr=140, start_time=T0)
    s = build_training_session(
        db_session, user.id, training_type='easy', total_distance_km=3.0, duration_minutes=20.0,
        begin_ts=T0, trackpoints_json=serialize_trackpoints(tps), laps_json=build_laps(meta),
        segments_json=[])
    reanalyze_training(db_session, s.id, user.id)
    db_session.refresh(s)
    assert s.segments_count == len(meta)
    assert s.segments_json[0]["source"] == "laps"
