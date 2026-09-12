# Сервис физиологических метрик тренировки (Workout insights service) — DEV_PLAN §9 D2
#
# Композиция: чистая математика src/analysis/{gap,effort,hr_baseline}.py + БД.
# computed_json считается отложенно (после синка / lazy) из trackpoints_json —
# старые тренировки покрываются get_or_compute без отдельного reanalyze-прогона.
# (Composition layer: pure math + DB; lazy compute covers legacy sessions.)
# #329: окружение сессии (план/история/RPE, ярлык по плану) — workout_insights_context.py.

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.analysis import session_metrics as sm
from src.analysis.effort import compute_cardiac_drift, heat_block, hr_stability, pace_cv
from src.analysis.data_checks import device_check, lap_check
from src.analysis.hr_zones import lthr_valid, zone_ceiling_hr
from src.analysis.week_structure import detraining, week_structure
from src.analysis.intervals import interval_recovery
from src.analysis.lthr_test import lthr_from_test
from src.analysis.gap import compute_gap, downhill_block, local_grade_factors, smooth_altitudes
from src.analysis.hr_baseline import baseline_deviation, detraining_hr_shift
from src.coach.config import (
    CADENCE_LOW_SPM,
    CADENCE_SANITY_MIN_SPM,
    CADENCE_TARGET_SPM,
    EASY_RUN_Z3_TOLERANCE_PCT,
    INTERVAL_MAX_KM,
    INTERVAL_MAX_PCT_WEEK,
    INTERVAL_SEGMENT_MAX_MIN,
    LONG_RUN_MAX_MIN,
    LTHR_TEST_DRIFT_MAX_BPM,
    LTHR_TEST_HR_COVERAGE_MIN,
    LTHR_TEST_WINDOW_MIN,
    LTHR_TEST_WORK_MIN,
    long_run_max_pct,
    PLAN_INTENSITY_TOLERANCE_PCT,
    PLAN_VOLUME_TOLERANCE_PCT,
    POINTS_PER_MIN,
    RPE_BASELINE_Z_MAX,
    RPE_ELEVATED_DELTA,
    RPE_MIN_SAMPLES,
    THRESHOLD_MAX_KM,
    THRESHOLD_MAX_PCT_WEEK,
    WARMUP_EASY_SHARE_MIN,
    WARMUP_WINDOW_MIN,
)
from src.coach.util import effective_training_type
from src.config.constants import BASELINE_TYPES, DETRAINING_LOOKBACK_DAYS, DRIFT_MAX_PACE_CV
from src.models import TrainingSession
from src.services.repositories import TrainingRepository
from src.services.insights_baseline import (  # noqa: F401 — реэкспорт для потребителей
    ensure_baseline,
    expected_hr_at_pace,
    expected_pace_at_hr,
    refresh_hr_pace_baseline,
    stored_baseline as _stored_baseline,
)
from src.services.repositories_insights import InsightRepository
# #329 (11.09.2026): контекст сессии (план дня, история, RPE) и ярлык по плану — отдельный модуль;
# apply_type_resolution реэкспортируется (type_resolution_backfill). (Session context split out.)
from src.services.workout_insights_context import (  # noqa: F401 — реэкспорт
    _history_briefs,
    _plan_for_session,
    _rpe_history,
    _session_dates,
    _session_day,
    _user_max_hr,
    apply_type_resolution,
)
from src.services.watch_temp_bias import recent_watch_bias
from src.utils.logger import get_logger

logger = get_logger("services.workout_insights")

INSIGHTS_SCHEMA_VERSION = 11  # версия computed_json (v5 — F0; v6 — F3 HRR; v7 — F5/F6: week_structure/downhill/detraining/session_rpe;
                             # v8 — 07.09.2026: пол GAP-фактора на спусках #298, heat.temp_source #299;
                             # v9 — 08.09.2026: baseline v2 (#259) + detraining_shift_bpm в hr_vs_baseline,
                             # контекст паузы в detraining (#289);
                             # v10 — 08.09.2026 (зима): heat.cold_flag, адаптивная поправка датчика часов,
                             # watch_temp_c/watch_minus_weather_c — история пересчитывается лениво;
                             # v11 — 12.09.2026: блок lthr_test (полевой ПАНО по треку, только для дня-теста плана)

_EMPTY_DRIFT = {"applicable": False, "reason": "no_trackpoints", "drift_pct": None,
                "first_half_ef": None, "second_half_ef": None, "gap_adjusted": None,
                "window_min": None, "flag": None}


def _parse_trackpoints(raw: list[dict] | None) -> tuple[list, list, list, list, datetime | None]:
    """trackpoints_json → (times_sec, dists, hrs, alts, t0); time ISO/datetime-совместимо.
    t0 — datetime первой точки: нужен для сопоставления lap-границ (F3)."""
    times_sec: list[float] = []
    dists: list[float] = []
    hrs: list[int | None] = []
    alts: list[float | None] = []
    t0: datetime | None = None
    if not raw:
        return times_sec, dists, hrs, alts, t0
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
    return times_sec, dists, hrs, alts, t0


def compute_workout_metrics(session: TrainingSession, *,
                            baseline: dict | None = None,
                            max_hr: int | None = None,
                            lthr: int | None = None,
                            week_km: float | None = None,
                            rpe_history: dict | None = None,
                            plan: dict | None = None,
                            history_briefs: list[dict] | None = None,
                            session_dates: list[dict] | None = None,
                            watch_bias: dict | None = None) -> dict:
    """Собрать computed_json одной тренировки (pure assembly, без БД).

    session_dates — даты тренировок за DETRAINING_LOOKBACK_DAYS (#289); None → detraining
    считается по history_briefs (15 дней), как раньше. watch_bias — `recent_watch_bias`
    (поправка датчика часов при отсутствии погоды; None → константа).

    Все ветки деградируют в applicable/available=false — исключений наружу нет.
    БД-входы (max_hr, week_km, rpe_history={"rpe","peers"}, plan — назначение
    на день сессии) резолвит upsert_workout_insights; None → available=false.
    """
    times_sec, dists, hrs, alts, tp_t0 = _parse_trackpoints(session.trackpoints_json)
    ttype = effective_training_type(session)
    # #286: паузы часов → зоны и темп км-точек без стоячего времени (moving-time)
    from src.analysis.utils import pauses_to_offsets
    ds = session.device_summary if isinstance(session.device_summary, dict) else {}
    pauses_sec = pauses_to_offsets(ds.get("pauses"), tp_t0)
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
            # Якорь зон: наблюдаемость тихого fallback LTHR→%max_hr (1d, 02.09.2026)
            # (zone anchor visibility: catches a silent LTHR→%max_hr fallback)
            "zone_anchor": "lthr" if lthr_valid(max_hr or 0, lthr) else "max_hr",
            # #302: откуда сегменты — laps (структурные лапы часов) | pace/km (эвристика)
            "segmentation_source": (
                (session.segments_json[0].get("source") or "pace")
                if isinstance(session.segments_json, list) and session.segments_json
                and isinstance(session.segments_json[0], dict) else None),
            # F2 (#286): кросс-чек пайплайна с эталоном часов; при gps_unreliable
            # эталон часов сам мусорный — не считаем
            # (pipeline vs watch cross-check; skipped when the watch data is garbage)
            "device_check": (device_check(session.device_summary, session.total_distance_km,
                             session.duration_minutes, session.elevation_gain)
                 if not gps_unreliable else None),
        },
    }
    if not times_sec:
        computed["drift"] = dict(_EMPTY_DRIFT)
        computed["gap"] = {"available": False}
        computed["hr_vs_baseline"] = {"available": False, "reason": "no_trackpoints"}
        computed["heat"] = heat_block(session.avg_temperature, ds.get("avg_temperature_c"),
                                      watch_bias_c=(watch_bias or {}).get("bias_c"),
                                      recent_weather_c=(watch_bias or {}).get("weather_median_c"))
        computed["time_in_zones"] = {"available": False, "reason": "no_trackpoints"}
        computed["easy_discipline"] = {"applicable": False, "reason": "no_trackpoints"}
        computed["pace_stability"] = {"available": False, "reason": "no_trackpoints"}
        computed["hr_stability"] = {"available": False, "reason": "no_trackpoints"}
        computed["load_points"] = {"available": False, "reason": "no_trackpoints"}
        computed["quality_volume"] = {"available": False, "reason": "no_trackpoints"}
        computed["long_run"] = sm.long_run_share(
            session.total_distance_km, session.duration_minutes, week_km, ttype,
            max_pct=long_run_max_pct(week_km), max_min=LONG_RUN_MAX_MIN)
        computed["cadence"] = sm.cadence_block(
            session.segments_json, target=CADENCE_TARGET_SPM,
            low=CADENCE_LOW_SPM, sanity_min=CADENCE_SANITY_MIN_SPM)
        computed["rpe"] = {"available": False, "reason": "no_trackpoints"}
        computed["warmup"] = {"applicable": False, "reason": "no_trackpoints"}
        computed["plan_vs_actual"] = sm.plan_vs_actual(
            plan, ttype, session.total_distance_km, session.duration_minutes,
            {"available": False}, volume_tol=PLAN_VOLUME_TOLERANCE_PCT,
            intensity_tol=PLAN_INTENSITY_TOLERANCE_PCT)
        computed["interval_recovery"] = {"available": False, "reason": "no_trackpoints"}
        computed["lthr_test"] = {"available": False, "reason": "no_trackpoints"}
        computed["week_structure"] = week_structure(
            history_briefs or [], _session_day(session), ttype)
        computed["detraining"] = detraining(
            session_dates if session_dates is not None else (history_briefs or []),
            _session_day(session))
        computed["downhill"] = {"available": False, "reason": "no_trackpoints"}
        computed["session_rpe"] = {"available": False, "reason": "no_rpe"}
        computed["flags"] = sm.collect_flags(computed)
        return computed

    # Жара и пауза — до отклонения от базовой линии: их ожидаемые сдвиги пульса входят в
    # ожидание (heat and layoff first: their expected HR shifts feed the baseline expectation)
    heat = heat_block(session.avg_temperature, ds.get("avg_temperature_c"),
                      watch_bias_c=(watch_bias or {}).get("bias_c"),
                      recent_weather_c=(watch_bias or {}).get("weather_median_c"))
    detrain = detraining(
        session_dates if session_dates is not None else (history_briefs or []),
        _session_day(session))
    if gps_unreliable:
        # Дистанции/темпы в trackpoints_json — мусор: pace-производные блоки честно
        # недоступны, а gap.available=false заодно исключает сессию из HR-baseline
        # (pace-derived blocks honestly unavailable; also drops session from HR baseline)
        gap = {"available": False, "reason": "gps_unreliable"}
        drift = {**_EMPTY_DRIFT, "reason": "gps_unreliable"}
        deviation = {"available": False, "reason": "gps_unreliable"}
    else:
        gap = compute_gap(times_sec, dists, hrs, alts, pauses_sec=pauses_sec or None)
        alts_smoothed = smooth_altitudes(alts)
        factors = local_grade_factors(dists, alts_smoothed) if alts_smoothed else None
        drift = compute_cardiac_drift(times_sec, dists, hrs, training_type=ttype,
                                      grade_factors=factors,
                                      per_km=gap.get("per_km"))
        deviation = (baseline_deviation(
                        baseline, gap["per_km"],
                        temp_shift_bpm=heat.get("expected_hr_shift_bpm"),
                        detraining_shift_bpm=detraining_hr_shift(detrain, gap["per_km"], baseline))
                     if gap.get("available") else
                     {"available": False, "reason": "no_gap"})
    computed["gap"] = gap
    computed["drift"] = drift
    computed["hr_vs_baseline"] = deviation
    # F7: телеметрия-сверка per_km с авто-лапами часов (без флагов)
    computed["inputs"]["lap_check"] = lap_check(
        session.laps_json if isinstance(session.laps_json, list) else None,
        gap.get("per_km"))
    computed["heat"] = heat

    # --- M1: детерминированные метрики сессии (METRICS_GUIDE §4) ---
    zones = sm.time_in_zones(times_sec, hrs, max_hr, lthr, pauses_sec=pauses_sec or None)
    computed["time_in_zones"] = zones
    computed["easy_discipline"] = sm.easy_discipline(
        zones, ttype, tolerance=EASY_RUN_Z3_TOLERANCE_PCT,
        avg_hr=session.avg_heart_rate,
        easy_ceiling_hr=zone_ceiling_hr(2, max_hr or 0, lthr))
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
            gap.get("per_km"), zones, week_km, max_hr, lthr=lthr,
            interval_max_pct=INTERVAL_MAX_PCT_WEEK, interval_max_km=INTERVAL_MAX_KM,
            threshold_max_pct=THRESHOLD_MAX_PCT_WEEK, threshold_max_km=THRESHOLD_MAX_KM,
            segment_max_min=INTERVAL_SEGMENT_MAX_MIN))
    computed["long_run"] = sm.long_run_share(
        session.total_distance_km, session.duration_minutes, week_km, ttype,
        max_pct=long_run_max_pct(week_km), max_min=LONG_RUN_MAX_MIN)
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
        window_min=WARMUP_WINDOW_MIN, easy_share_min=WARMUP_EASY_SHARE_MIN,
        lthr=lthr)
    computed["plan_vs_actual"] = sm.plan_vs_actual(
        plan, ttype, session.total_distance_km, session.duration_minutes,
        zones, volume_tol=PLAN_VOLUME_TOLERANCE_PCT,
        intensity_tol=PLAN_INTENSITY_TOLERANCE_PCT,
        distance_quality=((gps_quality.get("distance") or {}).get("quality")
                          if gps_unreliable else None))
    # F3 (M2.1 разбора): восстановление между интервалами — HRR по времени и пульсу,
    # поэтому работает и при gps_unreliable; мусорные dists при этом не передаём,
    # чтобы fallback-осцилляции не строились по фейковому темпу
    # (HRR uses time+HR so it survives bad GPS; garbage dists are withheld from the fallback)
    computed["interval_recovery"] = interval_recovery(
        times_sec, hrs, max_hr, lthr=lthr,
        dists=None if gps_unreliable else dists,
        laps=session.laps_json if isinstance(session.laps_json, list) else None,
        t0=tp_t0, ttype=ttype)
    # M3.2 (12.09.2026): полевой тест ПАНО — только когда план дня был тестом (маркер lthr_test);
    # число считает код, подтверждение — кнопкой (coach/lthr_field). (Field LTHR only on a test day.)
    computed["lthr_test"] = (
        lthr_from_test(times_sec, hrs, dists=None if gps_unreliable else dists,
                       pauses_sec=pauses_sec, max_hr=max_hr,
                       work_min=LTHR_TEST_WORK_MIN, window_min=LTHR_TEST_WINDOW_MIN,
                       drift_max_bpm=LTHR_TEST_DRIFT_MAX_BPM, coverage_min=LTHR_TEST_HR_COVERAGE_MIN)
        if (plan or {}).get("lthr_test") else {"available": False, "reason": "not_a_test_day"})
    # M4 (F5/F6): структура недели, детренированность, downhill, session-RPE
    computed["week_structure"] = week_structure(
        history_briefs or [], _session_day(session), ttype,
        session_avg_hr=session.avg_heart_rate, max_hr=max_hr, lthr=lthr)
    computed["detraining"] = detrain
    computed["downhill"] = (
        {"available": False, "reason": "gps_unreliable"} if gps_unreliable
        else downhill_block(dists, smooth_altitudes(alts)))
    rpe_val = (rpe_history or {}).get("rpe")
    computed["session_rpe"] = (
        {"available": True, "rpe": rpe_val,
         # Foster session-RPE: усилие × минуты — шкала нагрузки, независимая от Coros
         "load_au": round(rpe_val * (session.duration_minutes or 0))}
        if rpe_val is not None else {"available": False, "reason": "no_rpe"})
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
    from src.services.repositories import latest_lthr
    max_hr, lthr = _user_max_hr(user_id, db=db), latest_lthr(user_id, db=db)
    plan = _plan_for_session(user_id, session, db=db)
    # Ярлык с учётом плана — ДО метрик, чтобы plan_vs_actual/long_run/peers видели честный тип
    apply_type_resolution(user_id, session, db=db, plan=plan, max_hr=max_hr, lthr=lthr)
    computed = compute_workout_metrics(
        session, baseline=baseline,
        max_hr=max_hr, lthr=lthr,
        week_km=(TrainingRepository.km_in_window(user_id, session.begin_ts, db=db)
                 if session.begin_ts else None),
        rpe_history=_rpe_history(user_id, session, db=db),
        plan=plan,
        history_briefs=_history_briefs(user_id, session, db=db),
        session_dates=_session_dates(user_id, session, db=db),
        watch_bias=(recent_watch_bias(user_id, session.begin_ts, db=db)
                    if session.avg_temperature is None else None))
    # #246 (02.09.2026): статистика прогноз↔факт — только пишем, потребитель после M3.2
    try:
        from src.services.prediction_log import record_prediction_outcome
        record_prediction_outcome(session, computed, db=db)
    except Exception:  # статистика не должна ронять разбор (never break the review)
        logger.warning("PredictionLog failed for session=%s", session_id, exc_info=True)
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
