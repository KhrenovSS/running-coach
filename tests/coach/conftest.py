# Фикстуры для тестов гибридного коуча (Hybrid coach test fixtures) — DEV_PLAN §10
#
# NB: SQLite in-memory живёт всю pytest-сессию (drop_all запрещён — §6 CLAUDE.md),
# поэтому chat_id/email генерируются уникальными на каждый вызов фикстуры.
# (The in-memory DB persists across tests, so identities must be unique per use.)
from datetime import timedelta
from itertools import count

import pytest

from src.domain.models.base import utcnow
from tests.helpers import build_daily_metrics, build_training_session, make_user

_seq = count(92000)


def _unique_user(db_session):
    n = next(_seq)
    return make_user(db_session, chat_id=n, email=f"coach-{n}@example.com")


@pytest.fixture
def athlete_with_history(db_session):
    """Пользователь с 14 днями метрик и 5 тренировками (same shape as tests/skills)."""
    user = _unique_user(db_session)
    today = utcnow().date()
    for i in range(14):
        build_daily_metrics(db_session, user.id, metric_date=today - timedelta(days=i),
                            avg_sleep_hrv=65.0 + (i % 3), rhr=54 + (i % 2), vo2max=50.0)
    for i, ttype in enumerate(["easy", "tempo", "long", "interval", "recovery"]):
        build_training_session(db_session, user.id, training_type=ttype,
                               begin_ts=utcnow() - timedelta(days=i * 2))
    return user


@pytest.fixture
def empty_user(db_session):
    """Пользователь без единой метрики и тренировки — вырожденный случай (no data at all)."""
    return _unique_user(db_session)
