# Сервис физиологических метрик тренировки (Workout insights service) — DEV_PLAN §9 D2
#
# Композиция: чистая математика src/analysis/{gap,effort,hr_baseline}.py + БД.
# computed_json считается отложенно (после синка / lazy) из trackpoints_json —
# старые тренировки покрываются get_or_compute без отдельного reanalyze-прогона.
# (Composition layer: pure math + DB; lazy compute covers legacy sessions.)

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from src.analysis import session_metrics as sm
from src.analysis.effort import compute_cardiac_drift, heat_block, hr_stability, pace_cv
from src.analysis.gap import compute_gap, local_grade_factors, smooth_altitudes
from src.analysis.hr_baseline import (
    baseline_deviation,
    fit_hr_pace_baseline,
    hr_at_pace_band,
    km_points,
    pace_at_hr_band,
)
from src.coach.config import (
    CADENCE_LOW_SPM,
    CADENCE_SANITY_MIN_SPM,
    CADENCE_TARGET_SPM,
    EASY_RUN_Z3_TOLERANCE_PCT,
    INTERVAL_MAX_KM,
    INTERVAL_MAX_PCT_WEEK,
    INTERVAL_SEGMENT_MAX_MIN,
    LONG_RUN_MAX_MIN,
    LONG_RUN_MAX_PCT_WEEK,
    PLAN_INTENSITY_TOLERANCE_PCT,
    PLAN_VOLUME_TOLERANCE_PCT,
    POINTS_PER_MIN,
    RPE_BASELINE_Z_MAX,
    RPE_ELEVATED_DELTA,
    RPE_HISTORY_DAYS,
    RPE_MIN_SAMPLES,
    THRESHOLD_MAX_KM,
    THRESHOLD_MAX_PCT_WEEK,
    WARMUP_EASY_SHARE_MIN,
    WARMUP_WINDOW_MIN,
)
from src.coach.util import effective_training_type
from src.config import settings
from src.config.constants import BASELINE_TYPES, BASELINE_WINDOW_DAYS, DRIFT_MAX_PACE_CV
from src.models import TrainingSession, User, UserModel, WorkoutInsight
from src.services.repositories import FeedbackRepository, TrainingRepository
from src.services.repositories_insights import InsightRepository
from src.utils.logger import get_logger

logger = get_logger("services.workout_insights")

INSIGHTS_SCHEMA_VERSION = 4  # версия содержимого computed_json (bump при смене схемы; v4 — gps_quality)

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
                            baseline: dict | None = None,
                            max_hr: int | None = None,
                            week_km: float | None = None,
                            rpe_history: dict | None = None,
                            plan: dict | None = None) -> dict:
    """Собрать computed_json одной тренировки (pure assembly, без БД).

    Все ветки деградируют в applicable/available=false — исключений наружу нет.
    БД-входы (max_hr, week_km, rpe_history={"rpe","peers"}, plan — назначение
    на день сессии) резолвит upsert_workout_insights; None → available=false.
    """
    times_sec, dists, hrs, alts = _parse_trackpoints(session.trackpoints_json)
    ttype = effective_training_type(session)
    # Квалиметрия GPS: количественный ущерб для LLM; unreliable гейтит pace-блоки
    # (GPS quality: quantitative damage for the LLM; unreliable gates pace-derived blocks)
    gps_quality = session.gps_quality if isinstance(session.gps_quality, dict) else None
    gps_unreliable = bool(gps_quality and gps_quality.get("unreliable"))
    computed: dict = {
        "schema_version": INSIGHTS_SCHEMA_VERSION,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "trackpoint_count": len(times_sec),
            "has_hr": any(h is not None for h in hrs),
            "has_alt": any(a is not None for a in alts),
            "gps_quality": gps_quality,
        },
    }
    if not times_sec:
        computed["drift"] = dict(_EMPTY_DRIFT)
        computed["gap"] = {"available": False}
        computed["hr_vs_baseline"] = {"available": False, "reason": "no_trackpoints"}
        computed["heat"] = heat_block(session.avg_temperature)
        computed["time_in_zones"] = {"available": False, "reason": "no_trackpoints"}
        computed["easy_discipline"] = {"applicable": False, "reason": "no_trackpoints"}
        computed["pace_stability"] = {"available": False, "reason": "no_trackpoints"}
        computed["hr_stability"] = {"available": False, "reason": "no_trackpoints"}
        computed["load_points"] = {"available": False, "reason": "no_trackpoints"}
        computed["quality_volume"] = {"available": False, "reason": "no_trackpoints"}
        computed["long_run"] = sm.long_run_share(
            session.total_distance_km, session.duration_minutes, week_km, ttype,
            max_pct=LONG_RUN_MAX_PCT_WEEK, max_min=LONG_RUN_MAX_MIN)
        computed["cadence"] = sm.cadence_block(
            session.segments_json, target=CADENCE_TARGET_SPM,
            low=CADENCE_LOW_SPM, sanity_min=CADENCE_SANITY_MIN_SPM)
        computed["rpe"] = {"available": False, "reason": "no_trackpoints"}
        computed["warmup"] = {"applicable": False, "reason": "no_trackpoints"}
        computed["plan_vs_actual"] = sm.plan_vs_actual(
            plan, ttype, session.total_distance_km, session.duration_minutes,
            {"available": False}, volume_tol=PLAN_VOLUME_TOLERANCE_PCT,
            intensity_tol=PLAN_INTENSITY_TOLERANCE_PCT)
        computed["flags"] = sm.collect_flags(computed)
        return computed

    if gps_unreliable:
        # Дистанции/темпы в trackpoints_json — мусор: pace-производные блоки честно
        # недоступны, а gap.available=false заодно исключает сессию из HR-baseline
        # (pace-derived blocks honestly unavailable; also drops session from HR baseline)
        gap = {"available": False, "reason": "gps_unreliable"}
        drift = {**_EMPTY_DRIFT, "reason": "gps_unreliable"}
        deviation = {"available": False, "reason": "gps_unreliable"}
    else:
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

    # --- M1: детерминированные метрики сессии (METRICS_GUIDE §4) ---
    zones = sm.time_in_zones(times_sec, hrs, max_hr)
    computed["time_in_zones"] = zones
    computed["easy_discipline"] = sm.easy_discipline(
        zones, ttype, tolerance=EASY_RUN_Z3_TOLERANCE_PCT)
    # CV темпа: из drift, если посчитан; иначе (interval/ранний выход) — напрямую
    cv = drift.get("pace_cv")
    if cv is None:
        cv = pace_cv(gap.get("per_km"))
        cv = round(cv, 3) if cv is not None else None
    computed["pace_stability"] = (
        {"available": False, "reason": "gps_unreliable"} if gps_unreliable else
        {"available": True, "cv": cv, "flag": cv > DRIFT_MAX_PACE_CV}
        if cv is not None else {"available": False, "reason": "few_km"})
    computed["hr_stability"] = hr_stability(times_sec, dists, hrs)
    computed["load_points"] = sm.load_points(zones, POINTS_PER_MIN)
    computed["quality_volume"] = (
        {"available": False, "reason": "gps_unreliable"} if gps_unreliable else
        sm.quality_volume(
            gap.get("per_km"), zones, week_km, max_hr,
            interval_max_pct=INTERVAL_MAX_PCT_WEEK, interval_max_km=INTERVAL_MAX_KM,
            threshold_max_pct=THRESHOLD_MAX_PCT_WEEK, threshold_max_km=THRESHOLD_MAX_KM,
            segment_max_min=INTERVAL_SEGMENT_MAX_MIN))
    computed["long_run"] = sm.long_run_share(
        session.total_distance_km, session.duration_minutes, week_km, ttype,
        max_pct=LONG_RUN_MAX_PCT_WEEK, max_min=LONG_RUN_MAX_MIN)
    computed["cadence"] = sm.cadence_block(
        session.segments_json, target=CADENCE_TARGET_SPM,
        low=CADENCE_LOW_SPM, sanity_min=CADENCE_SANITY_MIN_SPM)
    computed["rpe"] = sm.rpe_block(
        (rpe_history or {}).get("rpe"), (rpe_history or {}).get("peers") or [],
        deviation.get("z") if deviation.get("available") else None,
        delta=RPE_ELEVATED_DELTA, min_samples=RPE_MIN_SAMPLES,
        z_max=RPE_BASELINE_Z_MAX)
    computed["warmup"] = sm.warmup_block(
        times_sec, hrs, max_hr, ttype,
        window_min=WARMUP_WINDOW_MIN, easy_share_min=WARMUP_EASY_SHARE_MIN)
    computed["plan_vs_actual"] = sm.plan_vs_actual(
        plan, ttype, session.total_distance_km, session.duration_minutes,
        zones, volume_tol=PLAN_VOLUME_TOLERANCE_PCT,
        intensity_tol=PLAN_INTENSITY_TOLERANCE_PCT,
        distance_quality=((gps_quality.get("distance") or {}).get("quality")
                          if gps_unreliable else None))
    computed["flags"] = sm.collect_flags(computed)
    return computed


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
    computed = compute_workout_metrics(
        session, baseline=baseline,
        max_hr=_user_max_hr(user_id, db=db),
        week_km=(TrainingRepository.km_in_window(user_id, session.begin_ts, db=db)
                 if session.begin_ts else None),
        rpe_history=_rpe_history(user_id, session, db=db),
        plan=_plan_for_session(user_id, session, db=db))
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


def _user_max_hr(user_id: int, *, db: Session) -> int:
    user = db.query(User).filter(User.id == user_id).first()
    return (user.max_hr if user and user.max_hr else settings.default_max_hr)


def _plan_for_session(user_id: int, session: TrainingSession, *,
                      db: Session) -> dict | None:
    """Назначение на локальную дату сессии — вход plan_vs_actual (M2.2).

    Заодно линкует Recommendation с тренировкой (linked_session_id — колонка
    задумана как связь «план ↔ факт», до M2.2 не писалась никогда).
    """
    from src.models import Recommendation
    from src.utils.timeutils import session_local_dt

    if session.begin_ts is None:
        return None
    user = db.query(User).filter(User.id == user_id).first()
    day = session_local_dt(session.begin_ts, session, user).date()
    rec = db.query(Recommendation).filter(
        Recommendation.user_id == user_id,
        Recommendation.for_date == day,
    ).order_by(Recommendation.id.desc()).first()
    if rec is None:
        return None
    if rec.linked_session_id is None:
        rec.linked_session_id = session.id
        db.commit()
    target, volume = rec.target_json or {}, rec.volume_json or {}
    return {
        "type": rec.workout_type,
        "max_zone": target.get("max_zone"),
        "pace_min_km": target.get("pace_min_km"),
        "duration_min": volume.get("duration_min"),
        "distance_km": volume.get("distance_km"),
        "for_date": rec.for_date.isoformat(),
        "source": rec.source, "clamped": rec.clamped,
    }


def _rpe_history(user_id: int, session: TrainingSession, *,
                 db: Session) -> dict | None:
    """RPE сессии + оценки того же типа за окно — вход для rpe_block (M1.8)."""
    rpe = FeedbackRepository.rating_for_session(session.id, db=db)
    if rpe is None:
        return None
    ttype = effective_training_type(session)
    rows = FeedbackRepository.ratings_with_sessions(
        user_id, days=RPE_HISTORY_DAYS, db=db)
    peers = [r["rating"] for r in rows
             if r.get("rating") is not None and r["session_id"] != session.id
             and (r.get("training_type_override") or r.get("training_type")) == ttype]
    return {"rpe": rpe, "peers": peers}


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
