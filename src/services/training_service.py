"""
Сервис управления тренировками: удаление, оценка (Training service: delete, feedback).

Инкапсулирует бизнес-логику, вынесенную из роутов pages.py (Фаза B / AUDIT-013).
Encapsulates business logic extracted from pages.py routes (Phase B / AUDIT-013).
"""

from datetime import timezone
from typing import Optional

from sqlalchemy.orm import Session

from src.models import (
    TrainingSession,
    TrainingFeedback,
    DeletedTraining,
)
from src.services.audit import AuditService
from src.utils.logger import get_logger

logger = get_logger("training_service")


def delete_training(db: Session, user_id: int, session_id: int) -> bool:
    """
    Удалить тренировку: переместить метаданные в DeletedTraining, удалить сессию.
    Delete training: move metadata to DeletedTraining, remove the session.

    Возвращает True если удалено, False если не найдено.
    Returns True if deleted, False if not found.
    """
    s = db.query(TrainingSession).filter(
        TrainingSession.id == session_id,
        TrainingSession.user_id == user_id,
    ).first()
    audit = AuditService(db)
    if not s:
        audit.log_event(
            event_type="training.delete_failed",
            message=f"Delete training failed: id={session_id} not found",
            severity="warning",
            user_id=user_id,
            metadata={"training_id": session_id},
        )
        return False

    segs = s.segments_json or []
    pace = None
    if segs:
        paces = [seg.get('pace_min_km') for seg in segs if seg.get('pace_min_km')]
        if paces:
            pace = round(sum(paces) / len(paces), 2)
    deleted = DeletedTraining(
        user_id=user_id,
        begin_ts=s.begin_ts,
        total_distance_km=s.total_distance_km,
        avg_heart_rate=s.avg_heart_rate,
        max_heart_rate=s.max_heart_rate,
        training_type=s.training_type,
        duration_minutes=s.duration_minutes,
        avg_temperature=s.avg_temperature,
        elevation_gain=s.elevation_gain,
        avg_cadence=s.avg_cadence,
        training_effect=s.training_effect,
        vo2max=s.vo2max,
        calories=s.calories,
        avg_pace=pace,
    )
    db.add(deleted)
    db.delete(s)
    db.commit()
    logger.info("Тренировка #%s удалена, метаданные сохранены (Session #%s deleted, metadata saved)", session_id, session_id)
    audit.log_training_deleted(
        user_id=user_id,
        training_id=session_id,
        begin_ts=str(s.begin_ts) if s.begin_ts else None,
        distance_km=s.total_distance_km,
        training_type=s.training_type,
    )
    return True


def upsert_feedback(db: Session, user_id: int, session_id: int, rating: int) -> Optional[TrainingFeedback]:
    """
    Создать или обновить оценку тренировки.
    Create or update training feedback rating.

    rating клипится в 0–10. Возвращает TrainingFeedback или None если сессия не найдена.
    rating is clamped to 0–10. Returns TrainingFeedback or None if session not found.
    """
    s = db.query(TrainingSession).filter(
        TrainingSession.id == session_id,
        TrainingSession.user_id == user_id,
    ).first()
    if not s:
        return None

    rating = max(0, min(10, rating))
    audit = AuditService(db)
    fb = db.query(TrainingFeedback).filter(
        TrainingFeedback.session_id == session_id,
        TrainingFeedback.user_id == user_id,
    ).first()

    if fb:
        old_rating = fb.rating
        fb.rating = rating
        db.commit()
        logger.info("Оценка тренировки #%s обновлена: %s → %s (Rating updated)", session_id, old_rating, rating)
        audit.log_event(
            event_type="feedback.updated",
            message=f"Session #{session_id} rating updated: {old_rating} → {rating}",
            severity="info",
            user_id=user_id,
            metadata={"session_id": session_id, "old_rating": old_rating, "new_rating": rating},
        )
    else:
        fb = TrainingFeedback(
            session_id=session_id,
            user_id=user_id,
            rating=rating,
        )
        db.add(fb)
        db.commit()
        logger.info("Оценка тренировки #%s сохранена: %s (Rating created)", session_id, rating)
        audit.log_event(
            event_type="feedback.created",
            message=f"Session #{session_id} rating created: {rating}/10",
            severity="info",
            user_id=user_id,
            metadata={"session_id": session_id, "rating": rating},
        )
    return fb