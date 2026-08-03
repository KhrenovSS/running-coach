# Фикстуры для тестов модуля коуча (Coach module test fixtures) — Этап 0
from datetime import timedelta

import pytest

from src.domain.models.base import utcnow
from tests.helpers import make_user, build_daily_metrics, build_training_session


@pytest.fixture
def athlete_with_history(db_session):
    """Пользователь с историей DailyMetrics и TrainingSession — вход для будущих skills.

    (User with a 14-day metrics history and several sessions — input for skills.)
    """
    user = make_user(db_session, chat_id=90001, email="athlete@example.com")
    today = utcnow().date()
    for i in range(14):
        build_daily_metrics(db_session, user.id, metric_date=today - timedelta(days=i),
                            avg_sleep_hrv=65.0 + (i % 3), rhr=54 + (i % 2), vo2max=50.0)
    for i, ttype in enumerate(["easy", "tempo", "long", "interval", "recovery"]):
        build_training_session(db_session, user.id, training_type=ttype,
                               begin_ts=utcnow() - timedelta(days=i * 2))
    return user
