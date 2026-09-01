# Персональная базовая линия HR↔GAP-темп поверх workout_insights (BACKLOG #270:
# резолверы вынесены из workout_insights — дисциплина ~400 строк/файл).
# (Personal HR↔pace baseline service on top of stored workout insights.)
#
# Хранение — UserModel.params_json['hr_pace_baseline']; км-точки — из готовых
# insights steady-тренировок окна; ленивый бутстрап досчитывает недостающие.

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from src.analysis.hr_baseline import (
    fit_hr_pace_baseline,
    hr_at_pace_band,
    km_points,
    pace_at_hr_band,
)
from src.coach.util import effective_training_type
from src.config.constants import BASELINE_TYPES, BASELINE_WINDOW_DAYS
from src.models import TrainingSession, UserModel, WorkoutInsight
from src.utils.logger import get_logger

logger = get_logger("services.insights_baseline")


def stored_baseline(user_id: int, *, db: Session) -> dict | None:
    um = db.query(UserModel).filter(UserModel.user_id == user_id).first()
    if um and um.params_json:
        return um.params_json.get("hr_pace_baseline")
    return None


def _bootstrap_window_insights(user_id: int, *, db: Session) -> list[int]:
    """Досчитать insights steady-тренировок окна, у которых их ещё нет.

    (Compute missing insights for steady sessions of the window.) Возвращает
    id досчитанных сессий; повторные вызовы дёшевы (две лёгкие выборки id).
    """
    # Поздний импорт — разрыв цикла с workout_insights (late import breaks the cycle)
    from src.services.workout_insights import upsert_workout_insights

    cutoff = datetime.now(timezone.utc) - timedelta(days=BASELINE_WINDOW_DAYS)
    # только id/типы — trackpoints_json тяжёлый, тянем его лишь в upsert по одной
    rows = db.query(TrainingSession.id, TrainingSession.training_type,
                    TrainingSession.training_type_override).filter(
        TrainingSession.user_id == user_id,
        TrainingSession.begin_ts >= cutoff,
        TrainingSession.trackpoints_json.isnot(None),
    ).all()
    have = {sid for (sid,) in db.query(WorkoutInsight.session_id).filter(
        WorkoutInsight.user_id == user_id)}
    missing = [r.id for r in rows
               if (r.training_type_override or r.training_type) in BASELINE_TYPES
               and r.id not in have]
    if missing:
        logger.info("Insights bootstrap for user=%s: computing %s sessions",
                    user_id, len(missing))
    for session_id in missing:
        upsert_workout_insights(user_id, session_id, db=db)
    return missing


def ensure_baseline(user_id: int, *, db: Session) -> dict | None:
    """Базовая линия с ленивым бутстрапом (lazy-bootstrap the HR↔pace baseline).

    Сохранённая есть → вернуть. Иначе досчитать недостающие insights окна и
    пересчитать линию. Данных мало → None.
    """
    baseline = stored_baseline(user_id, db=db)
    if baseline is not None:
        return baseline
    if not _bootstrap_window_insights(user_id, db=db):
        return refresh_hr_pace_baseline(user_id, db=db)
    # upsert steady-типа сам вызывает refresh после каждой сессии
    return stored_baseline(user_id, db=db)


def expected_pace_at_hr(user_id: int, hr_ceiling: int, *, db: Session) -> dict | None:
    """Эмпирический темп на пульсе: медиана км-точек insights окна в полосе
    под потолком (+ ленивый бутстрап недостающих insights).

    (Empirical pace at HR from window km-points; lazy insights bootstrap.)
    Мало точек в полосе → None. Возвращает {"pace_min_km", "n_points"}.
    """
    _bootstrap_window_insights(user_id, db=db)
    points, _ = _collect_window_points(user_id, db=db)
    return pace_at_hr_band(points, hr_ceiling)


def expected_hr_at_pace(user_id: int, pace_min_km: float, *, db: Session) -> dict | None:
    """Эмпирический пульс на темпе: медиана HR км-точек insights окна в полосе
    вокруг темпа (+ ленивый бутстрап недостающих insights).

    (Empirical HR at pace from window km-points; lazy insights bootstrap.)
    Мало точек в полосе → None. Возвращает {"hr_bpm", "n_points"}.
    """
    _bootstrap_window_insights(user_id, db=db)
    points, _ = _collect_window_points(user_id, db=db)
    return hr_at_pace_band(points, pace_min_km)


def _collect_window_points(user_id: int, *, db: Session
                           ) -> tuple[list[tuple[float, float]], int]:
    """Км-точки (gap_pace, hr) steady-тренировок окна из готовых insights.

    (Window km-points from stored insights.) Возвращает (points, n_sessions).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=BASELINE_WINDOW_DAYS)
    rows = db.query(WorkoutInsight, TrainingSession).join(
        TrainingSession, WorkoutInsight.session_id == TrainingSession.id,
    ).filter(
        WorkoutInsight.user_id == user_id,
        TrainingSession.begin_ts >= cutoff,
    ).all()
    points: list[tuple[float, float]] = []
    n_sessions = 0
    for insight, session in rows:
        if effective_training_type(session) not in BASELINE_TYPES:
            continue
        gap = (insight.computed_json or {}).get("gap") or {}
        if not gap.get("available"):
            continue
        session_points = km_points(gap.get("per_km") or [])
        if session_points:
            n_sessions += 1
            points.extend(session_points)
    return points, n_sessions


def refresh_hr_pace_baseline(user_id: int, *, db: Session) -> dict | None:
    """Пересчитать базовую линию HR↔GAP-темп по insights steady-тренировок окна.

    Хранение — UserModel.params_json['hr_pace_baseline'] (merge: initiative и
    прочие ключи не затираются). Мало данных → ключ удаляется (нет ложной точности).
    """
    points, n_sessions = _collect_window_points(user_id, db=db)
    baseline = fit_hr_pace_baseline(points, n_sessions)
    if baseline is not None:
        baseline["computed_at"] = datetime.now(timezone.utc).date().isoformat()
        baseline["window_days"] = BASELINE_WINDOW_DAYS

    um = db.query(UserModel).filter(UserModel.user_id == user_id).first()
    if um is None:
        um = UserModel(user_id=user_id, params_json={})
        db.add(um)
    params = dict(um.params_json or {})
    if baseline is not None:
        params["hr_pace_baseline"] = baseline
    else:
        params.pop("hr_pace_baseline", None)
    um.params_json = params
    db.commit()
    return baseline
