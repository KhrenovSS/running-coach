# Базовые тесты моделей БД (Basic database model tests)
from src.models import User, TrainingSession, DailyMetrics


def test_create_user(db_session):
    """Создание пользователя и проверка полей (Create user and verify fields)"""
    user = User(
        telegram_chat_id=123456789,
        name="Test Runner",
        max_hr=180,
        weight_kg=75.0,
    )
    db_session.add(user)
    db_session.commit()

    saved = db_session.query(User).filter(User.telegram_chat_id == 123456789).first()
    assert saved is not None
    assert saved.name == "Test Runner"
    assert saved.max_hr == 180
    assert saved.weight_kg == 75.0


def test_create_training_session(db_session):
    """Создание тренировки и связь с пользователем (Create session and link to user)"""
    user = User(telegram_chat_id=999, name="Runner")
    db_session.add(user)
    db_session.commit()

    session = TrainingSession(
        user_id=user.id,
        total_distance_km=10.5,
        training_type="tempo",
        duration_minutes=55.0,
    )
    db_session.add(session)
    db_session.commit()

    saved = db_session.query(TrainingSession).filter(TrainingSession.user_id == user.id).first()
    assert saved is not None
    assert saved.total_distance_km == 10.5
    assert saved.training_type == "tempo"


def test_create_daily_metrics(db_session):
    """Создание дневных метрик здоровья (Create daily health metrics)"""
    from datetime import date
    user = User(telegram_chat_id=111)
    db_session.add(user)
    db_session.commit()

    metrics = DailyMetrics(
        user_id=user.id,
        date=date(2026, 6, 1),
        avg_sleep_hrv=45.0,
        rhr=58,
    )
    db_session.add(metrics)
    db_session.commit()

    saved = db_session.query(DailyMetrics).filter(DailyMetrics.user_id == user.id).first()
    assert saved is not None
    assert saved.avg_sleep_hrv == 45.0
    assert saved.rhr == 58
