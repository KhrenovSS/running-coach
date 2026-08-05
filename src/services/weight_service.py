# Сервис учёта веса (Weight tracking service)
#
# Баг-фикс 05.08.2026: telegram-хендлер писал `user.weight_kg = weight` в DETACHED-объект
# (get_user возвращает пользователя из уже закрытой сессии) → измерение сохранялось,
# а профильный вес — нет, и главная страница показывала устаревшее значение.
# (Bug fix: the handler mutated a detached User — the profile weight was never persisted.)

from sqlalchemy.orm import Session

from src.domain.models import User, WeightMeasurement
from src.domain.models.base import utcnow


def save_weight(db: Session, user_id: int, weight_kg: float) -> WeightMeasurement:
    """Сохранить измерение веса И обновить профиль в ОДНОЙ сессии/транзакции.
    (Save the measurement AND update the profile weight in one session/transaction.)
    """
    measurement = WeightMeasurement(
        user_id=user_id,
        weight_kg=weight_kg,
        measured_at=utcnow(),
    )
    db.add(measurement)
    # Пользователь берётся из ЭТОЙ сессии — иначе присваивание не персистится
    # (fetch the user from THIS session — assignment on a detached object is lost)
    db_user = db.query(User).filter(User.id == user_id).first()
    if db_user:
        db_user.weight_kg = weight_kg
    db.commit()
    db.refresh(measurement)
    return measurement


def current_weight(db: Session, user_id: int, fallback: float | None = None) -> float | None:
    """Текущий вес = последнее измерение; fallback — профильный weight_kg.
    (Current weight = the latest measurement; falls back to the profile value.)"""
    last = db.query(WeightMeasurement.weight_kg).filter(
        WeightMeasurement.user_id == user_id,
    ).order_by(WeightMeasurement.measured_at.desc()).first()
    return float(last[0]) if last else fallback
