# Переразметка ярлыков истории по резолверу «план — назначение, факт — интенсивность»
# (relabel stored sessions) — одноразовый запуск после деплоя 04.09.2026, повторяемо и обратимо:
# сырой ярлык лежит в training_type_auto, откат — training_type = training_type_auto.

from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from src.models import TrainingSession
from src.services.repositories_insights import InsightRepository
from src.services.workout_insights import apply_type_resolution, upsert_workout_insights
from src.utils.logger import get_logger

logger = get_logger("services.type_resolution_backfill")


def relabel_sessions(db: Session, *, user_id: int | None = None,
                     since: datetime | None = None) -> dict:
    """Прогнать резолвер по сессиям без ручного override; изменённым пересчитать разбор.

    Возврат: {"checked", "changed", "changes": [{session_id, date, auto, before, after, source}]}.
    (Relabel sessions; recompute insights for the changed ones.)"""
    q = db.query(TrainingSession).filter(or_(
        TrainingSession.training_type_override.is_(None),
        TrainingSession.training_type_override == ""))
    if user_id is not None:
        q = q.filter(TrainingSession.user_id == user_id)
    if since is not None:
        q = q.filter(TrainingSession.begin_ts >= since)
    changes: list[dict] = []
    errors: list[dict] = []
    sessions = q.order_by(TrainingSession.begin_ts.asc()).all()
    for s in sessions:
        # Одна кривая legacy-строка не должна ронять прогон и оставлять рассинхрон
        # «тип обновлён, разбор старый» (db-safety ревью 04.09.2026): per-session try/rollback,
        # разбор пересчитывается для ВСЕХ проверенных (44 строки — секунды), не только изменённых
        try:
            before = s.training_type
            new_type, source, plan_type = apply_type_resolution(s.user_id, s, db=db)
            if new_type != before:
                changes.append({"session_id": s.id,
                                "date": s.begin_ts.date().isoformat() if s.begin_ts else None,
                                "auto": s.training_type_auto, "plan": plan_type,
                                "before": before, "after": new_type, "source": source})
            row = InsightRepository.for_session(s.user_id, s.id, db=db)
            status = row.status if row is not None else "none"
            upsert_workout_insights(s.user_id, s.id, db=db, status=status)
        except Exception as e:  # noqa: BLE001 — лог + rollback, идём дальше
            db.rollback()
            logger.error("Relabel failed for session=%s: %s", s.id, e, exc_info=True)
            errors.append({"session_id": s.id, "error": str(e)})
    logger.info("Relabel: checked=%d changed=%d errors=%d", len(sessions), len(changes), len(errors))
    return {"checked": len(sessions), "changed": len(changes), "changes": changes, "errors": errors}
