# State Assessor → AthleteState (DEV_PLAN §3)
# Собирает снимок состояния из скиллов и метрик. Интегральные скоры — прозрачные
# взвешенные суммы по весам из config.py (веса перенормируются по присутствующим
# компонентам — отсутствие данных не «награждается» нулевым вкладом).

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.coach.config import (
    CONFIDENCE_MIN_DAYS,
    CONFIDENCE_MIN_SESSIONS,
    FATIGUE_WEIGHTS,
    HRV_SD_FALLBACK_FACTOR,
    INJURY_RISK_THRESHOLDS,
    READINESS_WEIGHTS,
)
from src.coach.contracts import AthleteState, SkillResult
from src.coach.skills import distribution, fatigue, load, progress, recovery
from src.coach.util import clamp_value, effective_training_type, safe_div
from src.services.recovery_view import hrv_status, rhr_anomaly
from src.services.repositories import FeedbackRepository, TrainingRepository
from src.services.repositories_coach import CoachRepository

# Маппинги компонент → скор 0..1 (component score maps; 1.0 = лучший для readiness)
_HRV_SCORE = {"elevated": 1.0, "normal": 1.0, "low": 0.5, "very_low": 0.0}
_RHR_SCORE = {"normal": 1.0, "low": 0.75, "elevated": 0.5, "critical_elevated": 0.0}


def _weighted(components: dict[str, float | None], weights: dict[str, float]) -> float | None:
    """Взвешенная сумма 0..1 с перенормировкой по присутствующим компонентам.

    (Weighted 0..1 sum, weights renormalized over present components.)
    """
    present = {k: v for k, v in components.items() if v is not None}
    if not present:
        return None
    total_w = sum(weights[k] for k in present)
    if total_w == 0:
        return None
    return sum(weights[k] * v for k, v in present.items()) / total_w


def _readiness_score(dm, baseline_rhr: float | None) -> float | None:
    """Готовность 0..100 по READINESS_WEIGHTS (readiness score)."""
    if dm is None:
        return None
    hrv_st, _ = hrv_status(dm.avg_sleep_hrv, dm.sleep_hrv_baseline,
                           dm.sleep_hrv_sd, dm.sleep_hrv_interval_list)
    rhr_st = rhr_anomaly(dm.rhr, baseline_rhr)["status"] if dm.rhr is not None else None
    tired_score = None
    if dm.tired_rate is not None:
        # tired_rate −10..+10: −10 → 1.0 (свеж), +10 → 0.0 (разбит)
        tired_score = clamp_value((10 - dm.tired_rate) / 20, 0.0, 1.0)
    components = {
        "hrv_status": _HRV_SCORE.get(hrv_st) if hrv_st else None,
        "rhr_deviation": _RHR_SCORE.get(rhr_st) if rhr_st and rhr_st != "unknown" else None,
        "tired_rate": tired_score,
        "recovery_pct": dm.recovery_pct / 100 if dm.recovery_pct is not None else None,
    }
    score = _weighted(components, READINESS_WEIGHTS)
    return round(score * 100, 1) if score is not None else None


def _fatigue_score(dm, acwr_ratio: float | None, hard_days: int) -> float | None:
    """Усталость 0..100 по FATIGUE_WEIGHTS (fatigue score; 100 = максимальная)."""
    hrv_dev = None
    if dm is not None and dm.avg_sleep_hrv is not None and dm.sleep_hrv_baseline:
        sd = dm.sleep_hrv_sd or dm.sleep_hrv_baseline * HRV_SD_FALLBACK_FACTOR
        if sd > 0:
            # Отклонение вниз от базы в сигмах: 0σ → 0, ≥2σ → 1
            hrv_dev = clamp_value((dm.sleep_hrv_baseline - dm.avg_sleep_hrv) / (2 * sd), 0.0, 1.0)
    ratio_score = clamp_value(acwr_ratio / 2, 0.0, 1.0) if acwr_ratio is not None else None
    ati_cti = None
    if dm is not None and dm.ati is not None and dm.cti:
        r = safe_div(dm.ati, dm.cti)
        ati_cti = clamp_value(r / 2, 0.0, 1.0) if r is not None else None
    if ratio_score is None and hrv_dev is None and ati_cti is None:
        # Одних «0 тяжёлых дней» мало: при полном отсутствии данных скор — None, не 0
        # (zero hard days alone is not knowledge — no data means no score)
        return None
    components = {
        "training_load_ratio": ratio_score,
        "hrv_deviation": hrv_dev,
        "ati_cti_ratio": ati_cti,
        "consecutive_hard_days": clamp_value(hard_days / 4, 0.0, 1.0),
    }
    score = _weighted(components, FATIGUE_WEIGHTS)
    return round(score * 100, 1) if score is not None else None


def _injury_risk(hrv_very_low_days: int, acwr_ratio: float | None, hard_days: int) -> float:
    """Риск травмы 0..1: доля сработавших условий INJURY_RISK_THRESHOLDS (injury risk)."""
    t = INJURY_RISK_THRESHOLDS
    triggered = [
        hrv_very_low_days >= t["hrv_very_low_days"],
        acwr_ratio is not None and acwr_ratio > t["load_ratio_high"],
        hard_days >= t["consecutive_hard_days"],
    ]
    return round(sum(triggered) / len(triggered), 2)


def _hrv_very_low_days(user_id: int, *, db: Session) -> int:
    """Подряд идущих дней с HRV very_low, начиная со свежайшего (consecutive very-low days)."""
    series = CoachRepository.metrics_series(user_id, "hrv", 7, db=db)
    dm = CoachRepository.latest_metrics(user_id, db=db)
    if dm is None or dm.sleep_hrv_baseline is None:
        return 0
    baseline = dm.sleep_hrv_baseline
    sd = dm.sleep_hrv_sd or baseline * HRV_SD_FALLBACK_FACTOR
    count = 0
    for _, value in reversed(series):
        if value is not None and value < baseline - 2 * sd:
            count += 1
        else:
            break
    return count


def _missing(dm, rpe_coverage: float | None) -> list[str]:
    """Чего система не знает — честность для LLM (what the system does not know)."""
    missing = ["sleep", "stress", "per_session_tss", "pain"]  # pain — до миграции C3
    if dm is None or dm.avg_sleep_hrv is None:
        missing.append("hrv")
    if rpe_coverage is None or rpe_coverage < 0.5:
        missing.append("rpe")
    return missing


def assess_state(user_id: int, *, db: Session) -> AthleteState:
    """Собрать AthleteState из скиллов и метрик (assemble AthleteState).

    Никогда не бросает исключение из-за отсутствия данных: пустая БД → скоры None,
    skills со статусом unknown, data_confidence 0.0.
    """
    dm = CoachRepository.latest_metrics(user_id, db=db)
    baseline_rhr = CoachRepository.baseline_rhr(user_id, db=db)
    acwr = CoachRepository.acwr(user_id, db=db)
    hard_days = CoachRepository.consecutive_hard_days(user_id, db=db)

    skills: dict[str, SkillResult] = {
        "fatigue": fatigue.evaluate(user_id, db=db),
        "recovery": recovery.evaluate(user_id, db=db),
        "load": load.evaluate(user_id, db=db),
        "distribution": distribution.evaluate(user_id, db=db),
        "progress": progress.evaluate(user_id, db=db),
    }

    hrv_st = None
    if dm is not None:
        hrv_st, _ = hrv_status(dm.avg_sleep_hrv, dm.sleep_hrv_baseline,
                               dm.sleep_hrv_sd, dm.sleep_hrv_interval_list)

    zones = TrainingRepository.zone_distribution(user_id, days=28, db=db)
    total_z = sum(zones.values())
    zone_balance = {}
    if total_z > 0:
        zone_balance = {
            "z1_z2": round((zones["z1"] + zones["z2"]) / total_z, 2),
            "z3_plus": round((zones["z3"] + zones["z4"] + zones["z5"]) / total_z, 2),
        }

    last_workout = None
    sessions = CoachRepository.last_sessions(user_id, n=1, db=db)
    if sessions:
        s = sessions[0]
        last_workout = {
            "session_id": s.id,
            "date": s.begin_ts.date().isoformat() if s.begin_ts else None,
            "type": effective_training_type(s),
            "km": s.total_distance_km,
            "duration_min": s.duration_minutes,
            "avg_pace": s.avg_pace,
            "avg_hr": s.avg_heart_rate,
            "training_effect": s.training_effect,
            "rpe": FeedbackRepository.rating_for_session(s.id, db=db),
        }

    # data_confidence: половина — дни с метриками, половина — количество тренировок
    days = CoachRepository.metric_days_count(user_id, days=90, db=db)
    n_sessions = CoachRepository.sessions_count(user_id, days=90, db=db)
    data_confidence = round(
        0.5 * min(days / CONFIDENCE_MIN_DAYS, 1.0)
        + 0.5 * min(n_sessions / CONFIDENCE_MIN_SESSIONS, 1.0), 2)

    rpe_coverage = None
    if n_sessions > 0:
        ratings = FeedbackRepository.ratings_with_sessions(user_id, days=90, db=db)
        rpe_coverage = len(ratings) / n_sessions

    # Сырьё для evaluate_safety(state) — чистая функция без db (DEV_PLAN §4).
    # pain_level/pain_days появятся в C4 (после миграции C3) — до тех пор None/0.
    signals = {
        "hrv_status": hrv_st,
        "rhr_status": (rhr_anomaly(dm.rhr, baseline_rhr)["status"]
                       if dm is not None and dm.rhr is not None else None),
        "recovery_pct": dm.recovery_pct if dm else None,
        "ati_cti_ratio": safe_div(dm.ati, dm.cti) if dm else None,
        "acwr_ratio": acwr["ratio"],
        "consecutive_hard_days": hard_days,
        "pain_level": None,
        "pain_days": 0,
    }

    return AthleteState(
        user_id=user_id,
        as_of=dm.date if dm else None,
        readiness_score=_readiness_score(dm, baseline_rhr),
        fatigue_score=_fatigue_score(dm, acwr["ratio"], hard_days),
        injury_risk=_injury_risk(_hrv_very_low_days(user_id, db=db), acwr["ratio"], hard_days),
        recovery_hours_left=skills["recovery"].value if skills["recovery"].unit == "h" else 0.0,
        hrv_status=hrv_st,
        ati_cti_ratio=safe_div(dm.ati, dm.cti) if dm else None,
        zone_balance=zone_balance,
        last_workout=last_workout,
        progress={"message": skills["progress"].message} if skills["progress"].value is not None else {},
        skills=skills,
        data_confidence=data_confidence,
        missing=_missing(dm, rpe_coverage),
        signals=signals,
    )
