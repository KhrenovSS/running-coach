# Адаптивная поправка датчика температуры часов (Adaptive watch-temperature bias) — зима 08.09.2026.
#
# Часы показывают температуру у запястья: летом на солнце +0…2 °C к воздуху, в прохладу +5…7,
# под куркой зимой — на десятки градусов выше улицы. Константа WATCH_TEMP_BIAS_C годится только
# как дефолт; здесь — медиана (часы − погода) по последним тренировкам пользователя, у которых
# есть оба значения. Используется ТОЛЬКО когда погоды нет (heat_block, temp_source=watch).
# (Median of (watch − weather) over the athlete's recent sessions; used only as the fallback bias.)

from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median

from sqlalchemy.orm import Session

from src.config.constants import (
    WATCH_BIAS_MAX_SESSIONS,
    WATCH_BIAS_MIN_SESSIONS,
    WATCH_BIAS_WINDOW_DAYS,
)
from src.models import TrainingSession


def recent_watch_bias(user_id: int, before_ts: datetime | None, *, db: Session) -> dict | None:
    """Медиана расхождения датчика с погодой и медиана самой погоды по последним парам.

    Возвращает {"bias_c", "weather_median_c", "n"} или None при < WATCH_BIAS_MIN_SESSIONS пар
    в окне WATCH_BIAS_WINDOW_DAYS до before_ts (None → сейчас не ограничиваем сверху).
    Лёгкий запрос: две колонки, без trackpoints_json.
    """
    q = db.query(TrainingSession.avg_temperature, TrainingSession.device_summary).filter(
        TrainingSession.user_id == user_id,
        TrainingSession.avg_temperature.isnot(None),
        TrainingSession.device_summary.isnot(None),
    )
    if before_ts is not None:
        q = q.filter(TrainingSession.begin_ts < before_ts,
                     TrainingSession.begin_ts >= before_ts - timedelta(days=WATCH_BIAS_WINDOW_DAYS))
    rows = q.order_by(TrainingSession.begin_ts.desc()).limit(WATCH_BIAS_MAX_SESSIONS * 3).all()
    pairs: list[tuple[float, float]] = []
    for weather_c, ds in rows:
        watch_c = ds.get("avg_temperature_c") if isinstance(ds, dict) else None
        if watch_c is None:
            continue
        pairs.append((float(watch_c), float(weather_c)))
        if len(pairs) >= WATCH_BIAS_MAX_SESSIONS:
            break
    if len(pairs) < WATCH_BIAS_MIN_SESSIONS:
        return None
    return {"bias_c": round(median(w - a for w, a in pairs), 1),
            "weather_median_c": round(median(a for _, a in pairs), 1),
            "n": len(pairs)}
