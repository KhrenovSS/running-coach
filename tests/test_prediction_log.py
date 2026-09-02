# Продюсер PredictionLog (#246, 02.09.2026, этап «только пишем»): прогноз↔факт.
# (PredictionLog producer tests: residuals, idempotency, never-break-upsert.)

from itertools import count

from src.models import PredictionLog, Recommendation
from src.services.prediction_log import record_prediction_outcome
from src.services.repositories_insights import InsightRepository
from src.services.workout_insights import upsert_workout_insights
from src.utils.timeutils import session_local_dt
from tests.helpers import build_training_session, make_user

_seq = count(87000)

PREDICTED = {"expected_hr": 140, "pace_min_km": 6.0, "distance_km": 7.0}


def _user(db):
    n = next(_seq)
    return make_user(db, chat_id=n, email=f"predlog-{n}@example.com")


def _linked_rec(db, user, session, predicted=PREDICTED,
                volume={"duration_min": 45.0}) -> Recommendation:
    """Recommendation, слинкованный с сессией (как делает _plan_for_session)."""
    rec = Recommendation(user_id=user.id,
                         for_date=session_local_dt(session.begin_ts, session, user).date(),
                         workout_type="easy", target_json={"max_zone": 2},
                         volume_json=volume, predicted_json=predicted,
                         status="proposed", source="llm",
                         linked_session_id=session.id)
    db.add(rec)
    db.commit()
    return rec


def _rows(db, session_id):
    return db.query(PredictionLog).filter_by(session_id=session_id).all()


def test_residuals_and_actual_json(db_session):
    """Прогноз есть → строка с residual_hr = avg_hr − expected_hr,
    residual_load = факт − план, полным actual_json; флагов нет → flagged_hard False."""
    user = _user(db_session)
    s = build_training_session(db_session, user.id, avg_heart_rate=150,
                               duration_minutes=50.0, total_distance_km=10.0)
    _linked_rec(db_session, user, s)
    row = record_prediction_outcome(s, {"flags": []}, db=db_session)
    assert row is not None
    assert row.user_id == user.id
    assert row.residual_hr == 10.0                     # 150 − 140
    assert row.residual_load == 5.0                    # 50 − 45
    assert row.flagged_hard is False
    assert row.predicted_json == PREDICTED
    assert row.actual_json == {"avg_hr": 150, "avg_pace_min_km": 5.0,
                               "distance_km": 10.0, "duration_min": 50.0}
    assert len(_rows(db_session, s.id)) == 1


def test_flagged_hard_on_easy_run_too_hard(db_session):
    """Флаг 'easy_run_too_hard' (или 'poor_interval_recovery') → flagged_hard=True."""
    user = _user(db_session)
    s = build_training_session(db_session, user.id)
    _linked_rec(db_session, user, s)
    row = record_prediction_outcome(
        s, {"flags": ["gps_unreliable", "easy_run_too_hard"]}, db=db_session)
    assert row.flagged_hard is True


def test_residual_effort_from_rpe_block(db_session):
    """rpe-блок computed с медианой того же типа → residual_effort = rpe − медиана."""
    user = _user(db_session)
    s = build_training_session(db_session, user.id)
    _linked_rec(db_session, user, s)
    row = record_prediction_outcome(
        s, {"rpe": {"available": True, "rpe": 7, "median_same_type": 5.0}},
        db=db_session)
    assert row.residual_effort == 2.0


def test_partial_prediction_missing_residuals_are_none(db_session):
    """Прогноз без expected_hr и план без duration_min → строка есть,
    residual_hr/residual_load честно None (не 0)."""
    user = _user(db_session)
    s = build_training_session(db_session, user.id)
    _linked_rec(db_session, user, s, predicted={"pace_min_km": 6.0}, volume={})
    row = record_prediction_outcome(s, {}, db=db_session)
    assert row is not None
    assert row.residual_hr is None
    assert row.residual_load is None
    assert row.residual_effort is None


def test_no_prediction_or_link_no_row(db_session):
    """Нет слинкованного назначения или нет predicted_json → None, строк нет."""
    user = _user(db_session)
    s1 = build_training_session(db_session, user.id)       # вообще без назначения
    assert record_prediction_outcome(s1, {}, db=db_session) is None
    s2 = build_training_session(db_session, user.id)       # линк есть, прогноза нет
    _linked_rec(db_session, user, s2, predicted=None)
    assert record_prediction_outcome(s2, {}, db=db_session) is None
    assert _rows(db_session, s1.id) == [] and _rows(db_session, s2.id) == []


def test_idempotent_upsert_updates_same_row(db_session):
    """Повторный вызов обновляет ту же строку (UNIQUE по session_id), не дублирует."""
    user = _user(db_session)
    s = build_training_session(db_session, user.id, avg_heart_rate=150)
    _linked_rec(db_session, user, s)
    first = record_prediction_outcome(s, {"flags": []}, db=db_session)
    second = record_prediction_outcome(s, {"flags": ["easy_run_too_hard"]},
                                       db=db_session)
    assert second.id == first.id
    assert second.flagged_hard is True                     # строка обновлена
    assert len(_rows(db_session, s.id)) == 1


def test_full_upsert_path_creates_and_reuses_row(db_session):
    """Интеграция: upsert_workout_insights сам линкует назначение по дате
    (_plan_for_session) и пишет PredictionLog; повторный upsert не дублирует."""
    user = _user(db_session)
    s = build_training_session(db_session, user.id, avg_heart_rate=150,
                               duration_minutes=50.0)
    rec = Recommendation(user_id=user.id,
                         for_date=session_local_dt(s.begin_ts, s, user).date(),
                         workout_type="easy", target_json={"max_zone": 2},
                         volume_json={"duration_min": 45.0},
                         predicted_json=PREDICTED, status="proposed", source="llm")
    db_session.add(rec)
    db_session.commit()

    upsert_workout_insights(user.id, s.id, db=db_session)
    db_session.refresh(rec)
    assert rec.linked_session_id == s.id                   # линк проставлен по дате
    rows = _rows(db_session, s.id)
    assert len(rows) == 1
    assert rows[0].residual_hr == 10.0
    assert rows[0].residual_load == 5.0

    upsert_workout_insights(user.id, s.id, db=db_session)  # идемпотентность
    assert len(_rows(db_session, s.id)) == 1


def test_producer_failure_never_breaks_upsert(db_session, monkeypatch):
    """Ошибка продюсера статистики НЕ роняет разбор: upsert возвращает computed,
    строка workout_insights записана."""
    import src.services.prediction_log as pl

    def _boom(*a, **kw):
        raise RuntimeError("stats backend down")

    monkeypatch.setattr(pl, "record_prediction_outcome", _boom)
    user = _user(db_session)
    s = build_training_session(db_session, user.id)
    computed = upsert_workout_insights(user.id, s.id, db=db_session)
    assert computed is not None                             # разбор состоялся
    assert InsightRepository.for_session(user.id, s.id, db=db_session) is not None
    assert _rows(db_session, s.id) == []                    # статистики нет — и ладно
