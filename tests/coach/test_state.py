# Тесты сборки AthleteState (DEV_PLAN §10)
from datetime import timedelta

from src.coach.skills.base import SKILL_KEYS
from src.coach.state import assess_state
from src.domain.models.base import utcnow
from tests.coach.conftest import _unique_user
from tests.helpers import build_daily_metrics


def test_assess_state_full_fixture(athlete_with_history, db_session):
    state = assess_state(athlete_with_history.id, db=db_session)
    assert state.user_id == athlete_with_history.id
    assert set(state.skills) == set(SKILL_KEYS)
    assert state.as_of is not None
    assert state.readiness_score is not None and 0 <= state.readiness_score <= 100
    assert state.fatigue_score is not None and 0 <= state.fatigue_score <= 100
    assert state.injury_risk is not None and 0 <= state.injury_risk <= 1
    assert state.last_workout is not None and state.last_workout["type"] == "easy"
    # Честность: сна/стресса в данных нет — LLM обязан это видеть
    assert "sleep" in state.missing and "stress" in state.missing
    # 4 RPE из 36 в проде; в фикстуре 0 из 5 → rpe тоже missing
    assert "rpe" in state.missing


def test_assess_state_empty_user_never_raises(empty_user, db_session):
    """Пустая БД → None-скоры и unknown-скиллы, без исключений (no-data contract)."""
    state = assess_state(empty_user.id, db=db_session)
    assert state.readiness_score is None
    assert state.fatigue_score is None
    assert state.data_confidence == 0.0
    assert state.as_of is None
    assert state.last_workout is None
    assert all(s.status == "unknown" for s in state.skills.values())


def test_data_confidence_grows_with_history(db_session):
    """data_confidence растёт с историей: 3 дня << CONFIDENCE_MIN_DAYS → низкая."""
    user = _unique_user(db_session)
    today = utcnow().date()
    for i in range(3):
        build_daily_metrics(db_session, user.id, metric_date=today - timedelta(days=i))
    sparse = assess_state(user.id, db=db_session)
    assert 0.0 < sparse.data_confidence < 0.5


def test_zone_balance_shape(athlete_with_history, db_session):
    """zone_balance либо пуст (нет сегментов), либо суммируется к ~1.0."""
    state = assess_state(athlete_with_history.id, db=db_session)
    if state.zone_balance:
        assert abs(state.zone_balance["z1_z2"] + state.zone_balance["z3_plus"] - 1.0) < 0.02
