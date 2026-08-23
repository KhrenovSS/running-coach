# Тесты скиллов C1: норма + «нет данных» + пороги из config (DEV_PLAN §10)
from datetime import timedelta

from src.coach.config import INJURY_RISK_THRESHOLDS, RHR_BASELINE_MIN_POINTS
from src.coach.contracts import STATUS_UNKNOWN
from src.coach.skills import distribution, fatigue, load, progress, recovery, workout
from src.coach.skills.base import SKILL_KEYS
from src.domain.models.base import utcnow
from tests.coach.conftest import _unique_user
from tests.helpers import (
    build_daily_metrics,
    build_training_feedback,
    build_training_session,
)

STATE_SKILLS = {
    "fatigue": fatigue.evaluate,
    "recovery": recovery.evaluate,
    "load": load.evaluate,
    "distribution": distribution.evaluate,
    "progress": progress.evaluate,
}


def test_skill_keys_match_modules():
    assert set(STATE_SKILLS) == set(SKILL_KEYS)


def test_all_skills_no_data_never_raise(empty_user, db_session):
    """Вырожденный случай: пустая БД → unknown/0.0, без исключений (no-data contract)."""
    for key, fn in STATE_SKILLS.items():
        res = fn(empty_user.id, db=db_session)
        assert res.key == key
        assert res.status == STATUS_UNKNOWN
        assert res.confidence == 0.0
        assert res.value is None


def test_skills_normal_case(athlete_with_history, db_session):
    """На фикстуре с историей скиллы отдают осмысленные результаты."""
    for key, fn in STATE_SKILLS.items():
        res = fn(athlete_with_history.id, db=db_session)
        assert res.key == key
        assert 0.0 <= res.confidence <= 1.0
    # fatigue: HRV 65 при baseline 65 → норма; RHR стабилен → не danger
    assert fatigue.evaluate(athlete_with_history.id, db=db_session).status in ("ok", "warning")


def test_fatigue_danger_on_critical_rhr(db_session):
    """RHR +10 к медианной базе → danger (порог RHR_CRITICAL_DIFF из config)."""
    user = _unique_user(db_session)
    today = utcnow().date()
    # База: стабильный RHR 50 (больше RHR_BASELINE_MIN_POINTS точек)
    for i in range(1, RHR_BASELINE_MIN_POINTS + 3):
        build_daily_metrics(db_session, user.id, metric_date=today - timedelta(days=i),
                            rhr=50, avg_sleep_hrv=65.0)
    # Сегодня: RHR 61 (+11)
    build_daily_metrics(db_session, user.id, metric_date=today, rhr=61, avg_sleep_hrv=65.0)
    res = fatigue.evaluate(user.id, db=db_session)
    assert res.status == "danger"
    assert "critical_elevated" in res.message


def test_recovery_hours_left_after_interval(db_session):
    """Интервальная 10 часов назад → hours_left ≈ 38 (48 − 10), статус warning."""
    user = _unique_user(db_session)
    build_daily_metrics(db_session, user.id, recovery_pct=80)
    build_training_session(db_session, user.id, training_type="interval",
                           begin_ts=utcnow() - timedelta(hours=10))
    res = recovery.evaluate(user.id, db=db_session)
    assert res.unit == "h"
    assert 37 <= res.value <= 39
    assert res.status == "warning"  # recovery_pct ok, но часы не вышли


def test_recovery_override_beats_auto_type(db_session):
    """training_type_override приоритетнее автоклассификации (effective type)."""
    user = _unique_user(db_session)
    build_training_session(db_session, user.id, training_type="easy",
                           training_type_override="interval",
                           begin_ts=utcnow() - timedelta(hours=1))
    res = recovery.evaluate(user.id, db=db_session)
    assert res.value > 40  # 48ч интервальной, а не 18ч лёгкой


def test_load_danger_on_high_acwr(db_session):
    """ACWR > 1.5 → danger (порог INJURY_RISK_THRESHOLDS из config)."""
    user = _unique_user(db_session)
    today = utcnow().date()
    # Хроника: 21 день по 50; острая неделя: 7 дней по 250 → ACWR высокий
    for i in range(7, 28):
        build_daily_metrics(db_session, user.id, metric_date=today - timedelta(days=i),
                            training_load=50.0)
    for i in range(0, 7):
        build_daily_metrics(db_session, user.id, metric_date=today - timedelta(days=i),
                            training_load=250.0)
    res = load.evaluate(user.id, db=db_session)
    assert res.status == "danger"
    assert res.value > INJURY_RISK_THRESHOLDS["load_ratio_high"]


def test_load_insufficient_data_is_unknown(db_session):
    """< ACWR_CHRONIC_MIN_DAYS дней данных и нет ATI/CTI → unknown, а не ratio=0."""
    user = _unique_user(db_session)
    build_daily_metrics(db_session, user.id, training_load=100.0, ati=None, cti=None)
    res = load.evaluate(user.id, db=db_session)
    assert res.status == STATUS_UNKNOWN
    assert res.value is None


def test_distribution_warning_on_hard_bias(db_session):
    """Слишком много Z3+ → warning (баланс 80/20)."""
    user = _unique_user(db_session)
    hard_segments = [{"avg_hr": 165, "duration_min": 30.0}]  # Z4 при max_hr 177
    for i in range(4):
        build_training_session(db_session, user.id, training_type="tempo",
                               segments_json=hard_segments,
                               begin_ts=utcnow() - timedelta(days=i * 3))
    res = distribution.evaluate(user.id, db=db_session)
    assert res.status == "warning"
    assert res.value < 0.5


def test_workout_review(athlete_with_history, db_session):
    """Разбор конкретной сессии: факты + RPE; чужая сессия → unknown."""
    from src.models import TrainingSession
    session = db_session.query(TrainingSession).filter_by(
        user_id=athlete_with_history.id).first()
    build_training_feedback(db_session, session.id, athlete_with_history.id, rating=6)
    res = workout.evaluate_session(athlete_with_history.id, session.id, db=db_session)
    assert res.status == "ok"
    assert "rpe=6" in res.message

    stranger = _unique_user(db_session)
    res2 = workout.evaluate_session(stranger.id, session.id, db=db_session)
    assert res2.status == STATUS_UNKNOWN  # ownership: чужая сессия не читается
