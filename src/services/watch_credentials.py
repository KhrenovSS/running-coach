"""
Сервис управления учётными данными часов (Watch credential management service).

Инкапсулирует шифрование пароля и логику upsert/удаления WatchCredential.
Encapsulates password encryption and upsert/delete logic for WatchCredential.
"""

from sqlalchemy.orm import Session

from src.models import WatchCredential
from src.crypto import encrypt
from src.config.constants import (
    MIN_ACTIVITY_SYNC_INTERVAL_MIN,
    MIN_HEALTH_SYNC_INTERVAL_MIN,
    MAX_SYNC_INTERVAL_MIN,
)
from src.utils.logger import get_logger

logger = get_logger("watch_credentials")


def upsert_watch_credential(
    db: Session,
    user_id: int,
    brand: str,
    email: str = "",
    password: str = "",
    activity_sync_interval: int | None = None,
    health_sync_interval: int | None = None,
) -> bool:
    """
    Создать, обновить или удалить WatchCredential для бренда.
    Create, update, or delete WatchCredential for a brand.

    Возвращает True если credential сохранён, False если удалён.
    Returns True if credential saved, False if deleted.
    """
    cred = db.query(WatchCredential).filter(
        WatchCredential.user_id == user_id,
        WatchCredential.brand == brand,
    ).first()

    if not email:
        # Нет email — удаляем credential если есть (No email — delete credential if exists)
        if cred:
            db.delete(cred)
            logger.info("WatchCredential deleted: user=%s brand=%s", user_id, brand)
        return False

    if not cred:
        cred = WatchCredential(
            user_id=user_id,
            brand=brand,
            encrypted_user=encrypt(email),
        )
        db.add(cred)
        logger.info("WatchCredential created: user=%s brand=%s", user_id, brand)
    else:
        cred.encrypted_user = encrypt(email)

    if password:
        cred.encrypted_password = encrypt(password)

    if activity_sync_interval is not None and activity_sync_interval > 0:
        cred.activity_sync_interval = max(
            MIN_ACTIVITY_SYNC_INTERVAL_MIN,
            min(activity_sync_interval, MAX_SYNC_INTERVAL_MIN),
        )
    if health_sync_interval is not None and health_sync_interval > 0:
        cred.health_sync_interval = max(
            MIN_HEALTH_SYNC_INTERVAL_MIN,
            min(health_sync_interval, MAX_SYNC_INTERVAL_MIN),
        )
    return True