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
    pace_at_hr_adjusted,
    typical_pace_median,
    fit_hr_pace_baseline,
    hr_at_pace_band,
    km_points,
    pace_at_hr_band,
)
from src.coach.util import effective_training_type
from src.config.constants import BASELINE_POINT_TYPES, BASELINE_TYPES, BASELINE_WINDOW_DAYS
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


def expected_pace_at_hr(user_id: int, hr_ceiling: int, *, db: Session,
                        workout_type: str | None = None,
                        degraded_ok: bool = False) -> dict | None:
    """Темп на пульсе: A — медиана км-точек в узкой полосе под потолком; при degraded_ok
    (#264, ТОЛЬКО справочный ориентир, НЕ safety-clamp) — B (широкая полоса + локальный
    наклон) → C (типичный темп типа по avg_pace). Км-точки — steady + tempo (#263).
    Возвращает {"pace_min_km", "quality": band|adjusted|typical, …} или None.
    (Pace at HR with honest step-wise degradation for the reference estimate only.)
    """
    _bootstrap_window_insights(user_id, db=db)
    points, _ = _collect_window_points(user_id, db=db, include_quality=True)
    estimate = pace_at_hr_band(points, hr_ceiling)
    if estimate is not None or not degraded_ok:
        return estimate
    estimate = pace_at_hr_adjusted(points, hr_ceiling)
    if estimate is not None:
        return estimate
    return _typical_pace(user_id, workout_type, db=db)


def _typical_pace(user_id: int, workout_type: str | None, *, db: Session) -> dict | None:
    """Уровень C (#264): медиана avg_pace прошлых тренировок — сначала того же типа,
    при нехватке — всех steady-типов. Лёгкий запрос без trackpoints_json."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=BASELINE_WINDOW_DAYS)
    rows = db.query(TrainingSession.training_type, TrainingSession.training_type_override,
                    TrainingSession.avg_pace).filter(
        TrainingSession.user_id == user_id,
        TrainingSession.begin_ts >= cutoff,
        TrainingSession.avg_pace.isnot(None),
    ).all()
    def _type(r):
        return r.training_type_override or r.training_type
    if workout_type:
        same = typical_pace_median([r.avg_pace for r in rows if _type(r) == workout_type])
        if same is not None:
            return same
    return typical_pace_median([r.avg_pace for r in rows if _type(r) in BASELINE_TYPES])


def expected_hr_at_pace(user_id: int, pace_min_km: float, *, db: Session) -> dict | None:
    """Эмпирический пульс на темпе: медиана HR км-точек insights окна в полосе
    вокруг темпа (+ ленивый бутстрап недостающих insights).

    (Empirical HR at pace from window km-points; lazy insights bootstrap.)
    Мало точек в полосе → None. Возвращает {"hr_bpm", "n_points"}.
    """
    _bootstrap_window_insights(user_id, db=db)
    points, _ = _collect_window_points(user_id, db=db, include_quality=True)   # #263
    return hr_at_pace_band(points, pace_min_km)


def _collect_window_points(user_id: int, *, db: Session, include_quality: bool = False
                           ) -> tuple[list[tuple[float, float]], int]:
    """Км-точки (gap_pace, hr) тренировок окна из готовых insights.

    По умолчанию — steady-типы (база OLS); include_quality (#263) добавляет темповые —
    для полос «темп на пульсе»/«пульс на темпе» на высоких зонах (интервалы — нет: осцилляции).
    (Window km-points from stored insights.) Возвращает (points, n_sessions).
    """
    allowed = BASELINE_POINT_TYPES if include_quality else BASELINE_TYPES
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
        if effective_training_type(session) not in allowed:
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
