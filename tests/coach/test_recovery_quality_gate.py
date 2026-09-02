# Гейт качества для residual-tempo (фикс 02.09.2026):
# recovery.hours_left — «tempo» без подтверждения интенсивности пульсом
# восстанавливается как easy (18 ч), подтверждённая — 36 ч, interval — 48 ч;
# repositories_coach.consecutive_hard_days — residual-tempo не входит в hard-серию.
# (Quality gate for residual tempo: recovery hours + hard-day streak.)

from datetime import timedelta
from itertools import count

from src.coach.skills import recovery
from src.domain.models.base import utcnow
from src.services.repositories_coach import CoachRepository
from tests.helpers import build_daily_metrics, build_training_session, make_user

_seq = count(86000)


def _user(db):
    n = next(_seq)
    return make_user(db, chat_id=n, email=f"quality-gate-{n}@example.com")


# --- recovery.hours_left: часы восстановления по типу с гейтом качества ----------

def test_residual_tempo_recovers_as_easy(db_session):
    """Tempo с avg_hr 150 < 0.95·LTHR(170)=161.5 → окно easy: 18 − 10 ≈ 8 ч,
    а не 36 − 10 = 26 ч (residual tempo uses the easy window)."""
    user = _user(db_session)
    build_daily_metrics(db_session, user.id)                 # lthr=170 по умолчанию
    build_training_session(db_session, user.id, training_type="tempo",
                           avg_heart_rate=150,
                           begin_ts=utcnow() - timedelta(hours=10))
    left = recovery.hours_left(user.id, db=db_session)
    assert 7.0 <= left <= 9.0


def test_confirmed_tempo_keeps_full_window(db_session):
    """Tempo с avg_hr 165 ≥ 0.95·LTHR(170) → полное окно tempo: 36 − 10 ≈ 26 ч."""
    user = _user(db_session)
    build_daily_metrics(db_session, user.id)
    build_training_session(db_session, user.id, training_type="tempo",
                           avg_heart_rate=165,
                           begin_ts=utcnow() - timedelta(hours=10))
    left = recovery.hours_left(user.id, db=db_session)
    assert 25.0 <= left <= 27.0


def test_tempo_without_hr_treated_as_quality(db_session):
    """Незнание = осторожность: tempo без пульса → полное окно 36 ч."""
    user = _user(db_session)
    build_daily_metrics(db_session, user.id)
    build_training_session(db_session, user.id, training_type="tempo",
                           avg_heart_rate=None,
                           begin_ts=utcnow() - timedelta(hours=10))
    left = recovery.hours_left(user.id, db=db_session)
    assert 25.0 <= left <= 27.0


def test_interval_window_unchanged(db_session):
    """Гейт не трогает interval: 48 − 10 ≈ 38 ч независимо от avg_hr."""
    user = _user(db_session)
    build_daily_metrics(db_session, user.id)
    build_training_session(db_session, user.id, training_type="interval",
                           avg_heart_rate=150,                  # ниже порога tempo
                           begin_ts=utcnow() - timedelta(hours=10))
    left = recovery.hours_left(user.id, db=db_session)
    assert 37.0 <= left <= 39.0


def test_residual_tempo_maxhr_fallback_without_lthr(db_session):
    """Без LTHR гейт падает на %max_hr: 150 < 0.85·177 ≈ 150.5 → окно easy."""
    user = _user(db_session)                                 # max_hr=177, метрик нет
    build_training_session(db_session, user.id, training_type="tempo",
                           avg_heart_rate=150,
                           begin_ts=utcnow() - timedelta(hours=10))
    left = recovery.hours_left(user.id, db=db_session)
    assert 7.0 <= left <= 9.0


# --- consecutive_hard_days: residual-tempo не входит в hard-серию ----------------

def test_residual_tempo_day_not_in_hard_streak(db_session):
    """Residual-tempo сегодня (150 < 0.95·170) → серия тяжёлых дней = 0."""
    user = _user(db_session)
    build_daily_metrics(db_session, user.id)
    build_training_session(db_session, user.id, training_type="tempo",
                           avg_heart_rate=150, begin_ts=utcnow())
    assert CoachRepository.consecutive_hard_days(user.id, db=db_session) == 0


def test_confirmed_tempo_and_interval_count_in_streak(db_session):
    """Подтверждённая tempo сегодня + interval вчера → серия = 2."""
    user = _user(db_session)
    build_daily_metrics(db_session, user.id)
    build_training_session(db_session, user.id, training_type="tempo",
                           avg_heart_rate=165, begin_ts=utcnow())
    build_training_session(db_session, user.id, training_type="interval",
                           begin_ts=utcnow() - timedelta(days=1))
    assert CoachRepository.consecutive_hard_days(user.id, db=db_session) == 2


def test_residual_tempo_today_breaks_streak_from_today(db_session):
    """Interval вчера + residual-tempo сегодня → отсчёт с сегодня обрывается (0):
    residual-день не тяжёлый, значит «подряд с сегодня» не набирается."""
    user = _user(db_session)
    build_daily_metrics(db_session, user.id)
    build_training_session(db_session, user.id, training_type="interval",
                           begin_ts=utcnow() - timedelta(days=1))
    build_training_session(db_session, user.id, training_type="tempo",
                           avg_heart_rate=150, begin_ts=utcnow())
    assert CoachRepository.consecutive_hard_days(user.id, db=db_session) == 0
