# Сервис пересчёта тренировок (Training reanalysis service)

from sqlalchemy.orm import Session
from src.models import TrainingSession, User, get_settings
from src.analysis import process_trackpoints
from src.utils.logger import get_logger

logger = get_logger("analysis.reanalyze")


def reanalyze_training(db: Session, session_id: int, user_id: int,
                        training_type_override: str | None = None) -> dict | None:
    """
    Пересчитать тренировку из сохранённых трекпоинтов.
    Reanalyze training from stored trackpoints.

    Args:
        db: сессия БД
        session_id: ID тренировки
        user_id: ID пользователя (для проверки прав)
        training_type_override: ручная установка типа (None = авто)

    Returns:
        dict с результатами или None при ошибке
    """
    session = db.query(TrainingSession).filter(
        TrainingSession.id == session_id,
        TrainingSession.user_id == user_id,
    ).first()
    if not session:
        logger.warning("Reanalyze: тренировка %d не найдена ( Training %d not found)", session_id, session_id)
        return None

    if not session.trackpoints_json:
        logger.warning("Reanalyze: нет трекпоинтов для %d (No trackpoints for %d)", session_id, session_id)
        return None

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return None

    # Восстановить трекпоинты (Restore trackpoints)
    trackpoints = _restore_trackpoints(session.trackpoints_json)
    if not trackpoints:
        return None

    # Получить пороги из настроек пользователя (Get thresholds from user settings)
    pace_gap = user.interval_pace_threshold or 1.0
    phase = user.interval_min_phase_duration or 15
    lag = user.interval_hr_lag_sec or 5
    min_osc = user.interval_min_oscillations or 3

    try:
        result = process_trackpoints(
            trackpoints, session.begin_ts,
            max_hr=user.max_hr or 177,
            max_credible_pace=user.max_credible_pace or 3.0,
            max_gps_jump_m=user.max_gps_jump_m or 100.0,
            min_hr_for_fast_pace=user.min_hr_for_fast_pace or 130,
            pace_gap=pace_gap,
            interval_min_phase_duration=phase,
            interval_hr_lag_sec=lag,
            interval_min_oscillations=min_osc,
        )
    except Exception as e:
        logger.error("Reanalyze: ошибка анализа %d: %s (Analysis error for %d: %s)", session_id, e, session_id, e)
        return None

    if result is None:
        return None

    # Применить override (Apply override)
    if training_type_override and training_type_override in ('interval', 'tempo', 'long', 'recovery'):
        result['training_type'] = training_type_override
        session.training_type_override = training_type_override
    elif training_type_override == '':
        # Сброс override — вернуть к автоопределению (Reset override — back to auto)
        session.training_type_override = None

    # Обновить сессию (Update session)
    session.training_type = result['training_type']
    session.segments_count = result['segments_count']
    session.segments_json = result['segments_json']
    session.hr_pace_series = result['hr_pace_series']
    session.avg_heart_rate = result['avg_heart_rate']
    session.max_heart_rate = result['max_heart_rate']
    session.duration_minutes = result['duration_minutes']
    session.avg_cadence = result.get('avg_cadence')
    session.elevation_gain = result.get('elevation_gain')
    session.elevation_loss = result.get('elevation_loss')
    session.avg_temperature = result.get('avg_temperature')
    session.weather_code = result.get('weather_code')

    db.commit()
    logger.info("Reanalyze: тренировка %d пересчитана → %s, %d сегментов (Training %d reanalyzed → %s, %d segments)",
                session_id, result['training_type'], result['segments_count'],
                session_id, result['training_type'], result['segments_count'])
    return result


def _restore_trackpoints(trackpoints_json: list[dict]) -> list[dict] | None:
    """
    Восстановить трекпоинты из JSON (Restore trackpoints from JSON)
    Конвертирует строковые времена обратно в datetime объекты
    """
    try:
        for tp in trackpoints_json:
            if tp.get('time') and isinstance(tp['time'], str):
                from datetime import datetime, timezone
                tp['time'] = datetime.fromisoformat(tp['time'].replace('Z', '+00:00'))
        return trackpoints_json
    except Exception as e:
        logger.error("Reanalyze: ошибка восстановления трекпоинтов: %s (Trackpoint restore error: %s)", e, e)
        return None
