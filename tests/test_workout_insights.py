# Тесты сервиса физио-метрик (workout insights service tests) — DEV_PLAN §9 D2

import json
from datetime import timedelta

from src.analysis.utils import serialize_trackpoints
from src.config.constants import HEAT_TEMP_THRESHOLD_C
from src.domain.models.base import utcnow
from src.models import UserModel
from src.services.repositories_insights import InsightRepository
from src.services.workout_insights import (
    INSIGHTS_SCHEMA_VERSION,
    get_or_compute,
    refresh_hr_pace_baseline,
    upsert_workout_insights,
)
from tests.helpers import build_trackpoints, build_training_session, make_user

_seq = iter(range(93000, 93999))


def _user(db):
    n = next(_seq)
    return make_user(db, chat_id=n, email=f"insights-{n}@example.com")


def _session_with_track(db, user_id, *, duration_min=45.0, hr=140, base_pace=6.0,
                        hr_drift_bpm=0.0, grade_pct=0.0, ttype='easy', **kw):
    tps = build_trackpoints('long', duration_min=duration_min, base_pace=base_pace,
                            hr=hr, hr_drift_bpm=hr_drift_bpm, grade_pct=grade_pct)
    dist_km = tps[-1]['dist'] / 1000.0
    return build_training_session(
        db, user_id, total_distance_km=round(dist_km, 2),
        duration_minutes=duration_min, training_type=ttype,
        trackpoints_json=serialize_trackpoints(tps), **kw)


def test_full_cycle_computed_json_valid(db_session):
    """Полный цикл: сессия с треком → upsert → все секции валидны и JSON-сериализуемы."""
    user = _user(db_session)
    s = _session_with_track(db_session, user.id, hr_drift_bpm=20,
                            avg_temperature=HEAT_TEMP_THRESHOLD_C + 4)
    computed = upsert_workout_insights(user.id, s.id, db=db_session)
    assert computed["schema_version"] == INSIGHTS_SCHEMA_VERSION
    assert computed["drift"]["applicable"] is True
    assert computed["drift"]["flag"] == "high"
    assert computed["gap"]["available"] is True
    assert computed["heat"]["heat_flag"] is True
    assert "decoupling_high" in computed["flags"]
    assert "heat" in computed["flags"]
    json.dumps(computed)  # сериализуемость для JSON-колонки и промпта
    row = InsightRepository.for_session(user.id, s.id, db=db_session)
    assert row.computed_json["drift"]["flag"] == "high"
    assert row.schema_version == INSIGHTS_SCHEMA_VERSION


def test_legacy_session_without_trackpoints(db_session):
    """Legacy-сессия без трекпоинтов → минимальный dict, без исключений."""
    user = _user(db_session)
    s = build_training_session(db_session, user.id, training_type='easy')
    computed = upsert_workout_insights(user.id, s.id, db=db_session)
    assert computed["drift"] == {**computed["drift"], "applicable": False,
                                 "reason": "no_trackpoints"}
    assert computed["gap"]["available"] is False
    assert computed["flags"] == []


def test_get_or_compute_recomputes_stale_schema(db_session):
    """Устаревший schema_version в БД → get_or_compute пересчитывает."""
    user = _user(db_session)
    s = _session_with_track(db_session, user.id)
    InsightRepository.upsert(user.id, s.id, db=db_session,
                             computed={"schema_version": 0}, schema_version=0)
    computed = get_or_compute(user.id, s.id, db=db_session)
    assert computed["schema_version"] == INSIGHTS_SCHEMA_VERSION


def test_get_or_compute_returns_stored(db_session):
    """Актуальная запись возвращается как есть (без пересчёта)."""
    user = _user(db_session)
    s = _session_with_track(db_session, user.id)
    first = upsert_workout_insights(user.id, s.id, db=db_session)
    again = get_or_compute(user.id, s.id, db=db_session)
    assert again == first  # идемпотентно (включая computed_at — не пересчитан)


def test_ownership_enforced(db_session):
    """Чужая сессия → None."""
    user, stranger = _user(db_session), _user(db_session)
    s = _session_with_track(db_session, user.id)
    assert upsert_workout_insights(stranger.id, s.id, db=db_session) is None


def test_baseline_accumulates_and_preserves_initiative(db_session):
    """Baseline появляется после накопления steady-сессий; initiative не затёрт."""
    user = _user(db_session)
    um = UserModel(user_id=user.id, params_json={"initiative": "low"})
    db_session.add(um)
    db_session.commit()
    # 6 длинных easy-сессий с разными темпами (нужна дисперсия по x для OLS)
    # × ~7 км-точек (первый км исключается) > 30 точек; HR по закону 190−8·pace
    for i in range(6):
        pace = 5.5 + i * 0.2
        s = _session_with_track(db_session, user.id, duration_min=50.0,
                                base_pace=pace, hr=round(190 - 8 * pace),
                                ttype='easy',
                                begin_ts=utcnow() - timedelta(days=i * 3))
        upsert_workout_insights(user.id, s.id, db=db_session)
    db_session.expire_all()
    um = db_session.query(UserModel).filter_by(user_id=user.id).first()
    baseline = (um.params_json or {}).get("hr_pace_baseline")
    assert baseline is not None
    assert baseline["b"] < 0
    assert baseline["n_sessions"] >= 5
    assert um.params_json["initiative"] == "low"  # merge, не перезапись


def test_baseline_absent_with_few_sessions(db_session):
    """2 сессии → baseline отсутствует (мало данных, не ложная точность)."""
    user = _user(db_session)
    for i in range(2):
        s = _session_with_track(db_session, user.id, ttype='easy',
                                begin_ts=utcnow() - timedelta(days=i))
        upsert_workout_insights(user.id, s.id, db=db_session)
    baseline = refresh_hr_pace_baseline(user.id, db=db_session)
    assert baseline is None
    um = db_session.query(UserModel).filter_by(user_id=user.id).first()
    assert "hr_pace_baseline" not in (um.params_json or {})
