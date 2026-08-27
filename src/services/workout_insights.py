# Сервис физиологических метрик тренировки (Workout insights service) — DEV_PLAN §9 D2
#
# Композиция: чистая математика src/analysis/{gap,effort,hr_baseline}.py + БД.
# computed_json считается отложенно (после синка / lazy) из trackpoints_json —
# старые тренировки покрываются get_or_compute без отдельного reanalyze-прогона.
# (Composition layer: pure math + DB; lazy compute covers legacy sessions.)

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from src.analysis.effort import compute_cardiac_drift, heat_block
from src.analysis.gap import compute_gap, local_grade_factors, smooth_altitudes
from src.analysis.hr_baseline import (
    baseline_deviation,
    deviation_flag,
    fit_hr_pace_baseline,
    hr_at_pace_band,
    km_points,
    pace_at_hr_band,
)
from src.coach.util import effective_training_type
from src.config.constants import BASELINE_TYPES, BASELINE_WINDOW_DAYS
from src.models import TrainingSession, UserModel, WorkoutInsight
from src.services.repositories_insights import InsightRepository
from src.utils.logger import get_logger

logger = get_logger("services.workout_insights")

INSIGHTS_SCHEMA_VERSION = 1  # версия содержимого computed_json (bump при смене схемы)

_EMPTY_DRIFT = {"applicable": False, "reason": "no_trackpoints", "drift_pct": None,
                "first_half_ef": None, "second_half_ef": None, "gap_adjusted": None,
                "window_min": None, "flag": None}


def _parse_trackpoints(raw: list[dict] | None) -> tuple[list, list, list, list]:
    """trackpoints_json → (times_sec, dists, hrs, alts); time ISO/datetime-совместимо."""
    times_sec: list[float] = []
    dists: list[float] = []
    hrs: list[int | None] = []
    alts: list[float | None] = []
    if not raw:
        return times_sec, dists, hrs, alts
    t0: datetime | None = None
    for tp in raw:
        t = tp.get("time")
        d = tp.get("dist")
        if t is None or d is None:
            continue
        if isinstance(t, str):
            t = datetime.fromisoformat(t)
        if t0 is None:
            t0 = t
        times_sec.append((t - t0).total_seconds())
        dists.append(float(d))
        hrs.append(tp.get("hr"))
        alts.append(tp.get("alt"))
    return times_sec, dists, hrs, alts


def compute_workout_metrics(session: TrainingSession, *,
                            baseline: dict | None = None) -> dict:
    """Собрать computed_json одной тренировки (pure assembly, без БД).

    Все ветки деградируют в applicable/available=false — исключений наружу нет.
    """
    times_sec, dists, hrs, alts = _parse_trackpoints(session.trackpoints_json)
    ttype = effective_training_type(session)
    computed: dict = {
        "schema_version": INSIGHTS_SCHEMA_VERSION,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "trackpoint_count": len(times_sec),
            "has_hr": any(h is not None for h in hrs),
            "has_alt": any(a is not None for a in alts),
        },
    }
    if not times_sec:
        computed["drift"] = dict(_EMPTY_DRIFT)
        computed["gap"] = {"available": False}
        computed["hr_vs_baseline"] = {"available": False, "reason": "no_trackpoints"}
        computed["heat"] = heat_block(session.avg_temperature)
        computed["flags"] = _flags(computed)
        return computed

    gap = compute_gap(times_sec, dists, hrs, alts)
    alts_smoothed = smooth_altitudes(alts)
    factors = local_grade_factors(dists, alts_smoothed) if alts_smoothed else None
    drift = compute_cardiac_drift(times_sec, dists, hrs, training_type=ttype,
                                  grade_factors=factors,
                                  per_km=gap.get("per_km"))
    deviation = (baseline_deviation(baseline, gap["per_km"])
                 if gap.get("available") else
                 {"available": False, "reason": "no_gap"})
    computed["gap"] = gap
    computed["drift"] = drift
    computed["hr_vs_baseline"] = deviation
    computed["heat"] = heat_block(session.avg_temperature)
    computed["flags"] = _flags(computed)
    return computed


def _flags(computed: dict) -> list[str]:
    """Плоский список флагов — быстрый вход для LLM (flat flags for the LLM)."""
    flags: list[str] = []
    drift = computed.get("drift", {})
    if drift.get("flag") == "high":
        flags.append("decoupling_high")
    elif drift.get("flag") == "moderate":
        flags.append("decoupling_moderate")
    if computed.get("heat", {}).get("heat_flag"):
        flags.append("heat")
    if computed.get("gap", {}).get("hilly"):
        flags.append("hilly")
    dev_flag = deviation_flag(computed.get("hr_vs_baseline", {}))
    if dev_flag:
        flags.append(dev_flag)
    return flags


def upsert_workout_insights(user_id: int, session_id: int, *, db: Session,
                            status: str = "none") -> dict | None:
    """Вычислить метрики сессии и записать в workout_insights (ownership внутри).

    status применяется только к новой строке (upsert не понижает статус).
    После steady-тренировки пересчитывается персональная базовая линия.
    """
    session = db.query(TrainingSession).filter(
        TrainingSession.id == session_id,
        TrainingSession.user_id == user_id,
    ).first()
    if session is None:
        return None
    baseline = _stored_baseline(user_id, db=db)
    computed = compute_workout_metrics(session, baseline=baseline)
    InsightRepository.upsert(user_id, session_id, db=db, computed=computed,
                             schema_version=INSIGHTS_SCHEMA_VERSION, status=status)
    if effective_training_type(session) in BASELINE_TYPES:
        refresh_hr_pace_baseline(user_id, db=db)
    return computed


def get_or_compute(user_id: int, session_id: int, *, db: Session) -> dict | None:
    """Сохранённые метрики или пересчёт (lazy; покрывает старые тренировки)."""
    row = InsightRepository.for_session(user_id, session_id, db=db)
    if row is not None and row.computed_json is not None \
            and row.schema_version == INSIGHTS_SCHEMA_VERSION:
        return row.computed_json
    return upsert_workout_insights(user_id, session_id, db=db)


def _stored_baseline(user_id: int, *, db: Session) -> dict | None:
    um = db.query(UserModel).filter(UserModel.user_id == user_id).first()
    if um and um.params_json:
        return um.params_json.get("hr_pace_baseline")
    return None


def _bootstrap_window_insights(user_id: int, *, db: Session) -> list[int]:
    """Досчитать insights steady-тренировок окна, у которых их ещё нет.

    (Compute missing insights for steady sessions of the window.) Возвращает
    id досчитанных сессий; повторные вызовы дёшевы (две лёгкие выборки id).
    """
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
    baseline = _stored_baseline(user_id, db=db)
    if baseline is not None:
        return baseline
    if not _bootstrap_window_insights(user_id, db=db):
        return refresh_hr_pace_baseline(user_id, db=db)
    # upsert steady-типа сам вызывает refresh после каждой сессии
    return _stored_baseline(user_id, db=db)


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
