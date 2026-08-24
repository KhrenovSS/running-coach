# Тесты D4: обогащённый контекст разбора (workout_detail v2 + workout_computed)
# (D4 tests: enriched review context) — DEV_PLAN §9 D-серия

import json
from datetime import timedelta

from src.coach import orchestrator
from src.coach.tools.registry import run_tool
from src.domain.models.base import utcnow
from tests.helpers import build_daily_metrics, build_training_session

SEGMENTS = [
    {"duration_min": 6.0, "distance_km": 1.0, "avg_hr": 135, "pace_min_km": 6.0,
     "avg_cadence": 168, "zone": 2, "band": "easy",
     "elevation_gain": 4, "elevation_loss": 2, "temperature": 18, "weather_code": 1},
    {"duration_min": 6.2, "distance_km": 1.0, "avg_hr": 142, "pace_min_km": 6.2,
     "avg_cadence": 170, "zone": 2, "band": "easy",
     "elevation_gain": 40, "elevation_loss": 1, "temperature": 18, "weather_code": 1},
    {"duration_min": 5.8, "distance_km": 1.0, "avg_hr": 139, "pace_min_km": 5.8,
     "avg_cadence": 172, "zone": 2, "band": "easy",
     "elevation_gain": 0, "elevation_loss": 35, "temperature": 21, "weather_code": 3},
]


def _rich_session(db, user_id):
    begin = utcnow() - timedelta(hours=3)
    build_daily_metrics(db, user_id, metric_date=begin.date(),
                        avg_sleep_hrv=62.0, rhr=56, recovery_pct=44, tired_rate=2)
    return build_training_session(
        db, user_id, total_distance_km=3.0, duration_minutes=18.0,
        training_type='easy', segments_json=SEGMENTS, begin_ts=begin,
        avg_temperature=18, weather_code=1, elevation_gain=44,
        elevation_loss=38, avg_cadence=170)


def test_segments_carry_terrain_and_cadence(empty_user, db_session):
    """Сегменты v2: рельеф/каденс/длительность доезжают до LLM."""
    s = _rich_session(db_session, empty_user.id)
    detail = run_tool("get_workout_detail", {"session_id": s.id},
                      user_id=empty_user.id, db=db_session)
    seg2 = detail["segments"][1]
    assert seg2["elevation_gain"] == 40      # «пульс 142 на 2-м км из-за +40 м»
    assert seg2["avg_cadence"] == 170
    assert seg2["duration_min"] == 6.2
    assert detail["elevation_loss"] == 38
    assert detail["avg_cadence"] == 170
    assert detail["weather"] == {"temp_c": 18, "weather_code": 1}
    json.dumps(detail)


def test_segment_weather_delta_encoded(empty_user, db_session):
    """Погода в сегментах — дельтой: только при изменении против предыдущего."""
    s = _rich_session(db_session, empty_user.id)
    detail = run_tool("get_workout_detail", {"session_id": s.id},
                      user_id=empty_user.id, db=db_session)
    seg1, seg2, seg3 = detail["segments"]
    assert seg1["temperature"] == 18         # первый — всегда
    assert "temperature" not in seg2         # не изменилась — опущена
    assert seg3["temperature"] == 21         # изменилась — присутствует
    assert seg3["weather_code"] == 3


def test_daily_metrics_morning_of_workout_day(empty_user, db_session):
    """Блок метрик утра дня тренировки (не «сегодня»)."""
    s = _rich_session(db_session, empty_user.id)
    detail = run_tool("get_workout_detail", {"session_id": s.id},
                      user_id=empty_user.id, db=db_session)
    dm = detail["daily_metrics_morning"]
    assert dm == {"hrv": 62.0, "hrv_baseline": 65.0, "rhr": 56,
                  "recovery_pct": 44, "tired_rate": 2}


def test_no_metrics_day_graceful(empty_user, db_session):
    """Нет метрик на дату тренировки → None, без исключений."""
    begin = utcnow() - timedelta(days=400)   # заведомо без DailyMetrics
    s = build_training_session(db_session, empty_user.id, training_type='easy',
                               begin_ts=begin)
    detail = run_tool("get_workout_detail", {"session_id": s.id},
                      user_id=empty_user.id, db=db_session)
    assert detail["daily_metrics_morning"] is None


def test_review_extras_include_workout_computed(empty_user, db_session):
    """extras разбора содержат workout_computed (физио-метрики, lazy)."""
    s = _rich_session(db_session, empty_user.id)
    extras = orchestrator._build_extras(empty_user.id, db=db_session,
                                        session_id=s.id)
    computed = extras["workout_computed (workout_insights)"]
    assert computed["schema_version"] >= 1
    assert "drift" in computed and "gap" in computed and "flags" in computed
    json.dumps(extras["workout_detail (get_workout_detail)"])
    json.dumps(computed)
