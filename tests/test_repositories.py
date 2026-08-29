# Тесты агрегационных репозиториев под SQLite-харнессом (Repository tests) — Трек 2
#
# Ключевой момент: методы принимают db=... (DI), поэтому запускаются на тестовой SQLite-сессии.
# Ранее weekly_volume использовал Postgres-only date_trunc и падал под SQLite.

from datetime import timedelta

from src.domain.models.base import utcnow
from src.services.repositories import TrainingRepository, HealthRepository, FeedbackRepository
from tests.helpers import (
    make_user, build_training_session, build_daily_metrics, build_training_feedback,
)


_uid = [1000]


def _new_user(db):
    """Уникальный пользователь на тест (in-memory БД разделяется между тестами)."""
    _uid[0] += 1
    n = _uid[0]
    return make_user(db, chat_id=n, email=f"repo{n}@example.com")


def test_weekly_volume_buckets_without_date_trunc(db_session):
    user = _new_user(db_session)
    # 2 тренировки на этой неделе + 1 ~10 дней назад → 2 недельных бакета
    build_training_session(db_session, user.id, total_distance_km=10.0, duration_minutes=50.0)
    build_training_session(db_session, user.id, total_distance_km=8.0, duration_minutes=40.0)
    build_training_session(db_session, user.id, total_distance_km=6.0, duration_minutes=30.0,
                           begin_ts=utcnow() - timedelta(days=10))

    result = TrainingRepository.weekly_volume(user.id, weeks=4, db=db_session)

    assert len(result) == 2
    assert sum(r["session_count"] for r in result) == 3
    assert round(sum(r["total_km"] for r in result), 1) == 24.0
    # отсортировано по возрастанию недели
    assert result[0]["week_start"] <= result[1]["week_start"]


def test_zone_distribution_sums_segment_minutes(db_session):
    user = _new_user(db_session)
    build_training_session(
        db_session, user.id,
        segments_json=[{"avg_hr": 130, "duration_min": 20.0},
                       {"avg_hr": 165, "duration_min": 10.0}],
    )
    zones = TrainingRepository.zone_distribution(user.id, days=28, db=db_session)
    assert set(zones) == {"z1", "z2", "z3", "z4", "z5"}
    assert round(sum(zones.values()), 1) == 30.0  # 20 + 10


def test_training_type_distribution(db_session):
    user = _new_user(db_session)
    build_training_session(db_session, user.id, training_type="tempo")
    build_training_session(db_session, user.id, training_type="tempo")
    build_training_session(db_session, user.id, training_type="interval")
    dist = TrainingRepository.training_type_distribution(user.id, days=28, db=db_session)
    assert dist == {"tempo": 2, "interval": 1}


def test_hrv_and_vo2max_trends(db_session):
    user = _new_user(db_session)
    today = utcnow().date()
    for i, hrv in enumerate([60.0, 62.0, 64.0]):
        build_daily_metrics(db_session, user.id, metric_date=today - timedelta(days=i),
                            avg_sleep_hrv=hrv, vo2max=50.0 + i)
    hrv = HealthRepository.hrv_trend(user.id, days=30, db=db_session)
    vo2 = HealthRepository.vo2max_trend(user.id, days=90, db=db_session)
    assert len(hrv) == 3 and len(vo2) == 3
    assert hrv[0]["date"] <= hrv[-1]["date"]  # отсортировано по дате


def test_feedback_repository(db_session):
    user = _new_user(db_session)
    s1 = build_training_session(db_session, user.id, training_type="interval")
    s2 = build_training_session(db_session, user.id, training_type="easy")
    build_training_feedback(db_session, s1.id, user.id, rating=8)
    build_training_feedback(db_session, s2.id, user.id, rating=3)

    assert FeedbackRepository.avg_rating(user.id, days=28, db=db_session) == 5.5
    assert FeedbackRepository.rating_for_session(s1.id, db=db_session) == 8
    assert FeedbackRepository.rating_for_session(999999, db=db_session) is None

    paired = FeedbackRepository.ratings_with_sessions(user.id, days=28, db=db_session)
    assert len(paired) == 2
    by_type = {p["training_type"]: p["rating"] for p in paired}
    assert by_type == {"interval": 8, "easy": 3}


def test_feedback_avg_empty(db_session):
    user = _new_user(db_session)
    assert FeedbackRepository.avg_rating(user.id, db=db_session) is None


def test_km_in_window_rolling(db_session):
    """km_in_window: окно (end−7д, end] — включает сессию, исключает старое."""
    user = _new_user(db_session)
    now = utcnow()
    build_training_session(db_session, user.id, total_distance_km=10.0,
                           begin_ts=now)
    build_training_session(db_session, user.id, total_distance_km=5.0,
                           begin_ts=now - timedelta(days=3))
    build_training_session(db_session, user.id, total_distance_km=8.0,
                           begin_ts=now - timedelta(days=8))  # вне окна
    km = TrainingRepository.km_in_window(user.id, now, db=db_session)
    assert km == 15.0
