# Продюсер PredictionLog (#246, этап «только пишем» — 02.09.2026): прогноз↔факт.
# (PredictionLog producer: prediction vs actual residuals; write-only stage.)
#
# Пишет остатки прогноза назначения против факта тренировки. СОЗНАТЕЛЬНО никто
# не читает: копим статистику калибровки; потребитель (EWMA-коррекция прогнозов,
# CALIBRATION_* в coach/config.py) включается после M3.2 — валидации LTHR полевым
# тестом, иначе residuals «до» и «после» смены якоря зон несравнимы.

from __future__ import annotations

from sqlalchemy.orm import Session

from src.models import PredictionLog, Recommendation, TrainingSession
from src.utils.logger import get_logger

logger = get_logger("services.prediction_log")


def record_prediction_outcome(session: TrainingSession, computed: dict, *,
                              db: Session) -> PredictionLog | None:
    """Записать прогноз↔факт для сессии; None — прогноза не было.

    Идемпотентно по session_id (UNIQUE): повторный разбор обновляет строку.
    Прогноз — `Recommendation.predicted_json` назначения, слинкованного с сессией
    (`linked_session_id` заполняет `workout_insights._plan_for_session`).
    (Idempotent by session_id; prediction comes from the linked recommendation.)
    """
    rec = db.query(Recommendation).filter(
        Recommendation.linked_session_id == session.id,
    ).order_by(Recommendation.id.desc()).first()
    if rec is None or not rec.predicted_json:
        return None

    predicted = rec.predicted_json
    actual = {
        "avg_hr": session.avg_heart_rate,
        "avg_pace_min_km": session.avg_pace,
        "distance_km": session.total_distance_km,
        "duration_min": session.duration_minutes,
    }

    residual_hr = None
    if predicted.get("expected_hr") is not None and session.avg_heart_rate:
        residual_hr = round(session.avg_heart_rate - predicted["expected_hr"], 1)

    # residual_effort: RPE против медианы того же типа (из rpe-блока computed)
    residual_effort = None
    rpe_block = (computed or {}).get("rpe") or {}
    if rpe_block.get("available") and rpe_block.get("median_same_type") is not None:
        residual_effort = round(rpe_block["rpe"] - rpe_block["median_same_type"], 1)

    residual_load = None
    planned_min = (rec.volume_json or {}).get("duration_min")
    if planned_min and session.duration_minutes:
        residual_load = round(session.duration_minutes - planned_min, 1)

    flags = (computed or {}).get("flags") or []
    flagged_hard = any(f in flags for f in
                       ("poor_interval_recovery", "easy_run_too_hard"))

    row = db.query(PredictionLog).filter(
        PredictionLog.session_id == session.id).first()
    if row is None:
        row = PredictionLog(user_id=session.user_id, session_id=session.id)
        db.add(row)
    row.predicted_json = predicted
    row.actual_json = actual
    row.residual_hr = residual_hr
    row.residual_effort = residual_effort
    row.residual_load = residual_load
    row.flagged_hard = flagged_hard
    db.commit()
    logger.info("PredictionLog session=%s residual_hr=%s residual_load=%s",
                session.id, residual_hr, residual_load)
    return row
