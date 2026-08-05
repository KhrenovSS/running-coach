# Тесты сервиса веса (Weight service tests) — баг-фикс 05.08.2026:
# ввод веса не обновлял профиль (detached User), главная показывала старый вес.

from datetime import timedelta

from src.domain.models import User, WeightMeasurement
from src.domain.models.base import utcnow
from src.services.weight_service import save_weight, current_weight
from tests.helpers import make_user


def _user(db, n: int):
    return make_user(db, chat_id=99000 + n, email=f"weight_{n}@example.com")


def test_save_weight_updates_profile_in_same_transaction(db_session):
    """Регресс: раньше user.weight_kg писался в detached-объект и терялся."""
    user = _user(db_session, 1)  # фабрика ставит weight_kg=75.0
    save_weight(db_session, user.id, 78.4)

    fresh = db_session.query(User).filter(User.id == user.id).first()
    assert fresh.weight_kg == 78.4, "профильный вес должен обновиться той же транзакцией"
    m = db_session.query(WeightMeasurement).filter(
        WeightMeasurement.user_id == user.id).all()
    assert len(m) == 1 and m[0].weight_kg == 78.4


def test_current_weight_prefers_latest_measurement(db_session):
    """Главная должна показывать ПОСЛЕДНЕЕ измерение, а не профильный снапшот."""
    user = _user(db_session, 2)
    old = WeightMeasurement(user_id=user.id, weight_kg=82.9,
                            measured_at=utcnow() - timedelta(days=30))
    new = WeightMeasurement(user_id=user.id, weight_kg=79.1, measured_at=utcnow())
    db_session.add_all([old, new])
    db_session.commit()

    assert current_weight(db_session, user.id, fallback=82.9) == 79.1


def test_current_weight_falls_back_to_profile(db_session):
    """Без измерений — профильный вес (fallback)."""
    user = _user(db_session, 3)
    assert current_weight(db_session, user.id, fallback=75.0) == 75.0
