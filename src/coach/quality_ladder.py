# Лестница качественных дней (Quality-days ladder) — решение владельца 12.09.2026.
#
# Сколько темповых/интервальных допускать в плане недели — не константа, а факт переносимости:
# «если хорошо переношу — можно до 3 (гайд 41), если трудно или только начинаю — по одной».
# Переносимость качественной тренировки читается из данных, которые уже собирает система:
# тап тяжести (RPE 0–10) и боли, пульс относительно базовой линии (hr_vs_baseline.z, флаг
# hr_above_baseline), флаги разбора (poor_interval_recovery, hard_days_too_close), восстановление
# и HRV на следующее утро. Safety-гейты (правила 12/16/17) остаются главнее — они режут hard_days_max
# в planning_safety.apply_safety_to_targets. (Data-driven quality-day allowance, 1→3.)

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy.orm import Session

from src.coach.config import (
    HARD_TYPES,
    HRV_SD_FALLBACK_FACTOR,
    PLAN_QUALITY_DAYS_CAP,
    PLAN_QUALITY_DAYS_MIN,
    QUALITY_HR_Z_HIGH,
    QUALITY_LADDER_MIN_SESSIONS,
    QUALITY_LADDER_RUN_DAYS_GAP,
    QUALITY_LADDER_TOLERATED_SHARE,
    QUALITY_LADDER_WEEKS,
    QUALITY_RPE_HARD,
    RECOVERY_PCT_READY,
)
from src.coach.planning_window import monday_of
from src.coach.training_status import PHASE_STABLE
from src.coach.util import effective_training_type
from src.models import TrainingFeedback, TrainingSession, User
from src.services.repositories_coach import CoachRepository
from src.services.repositories_insights import InsightRepository
from src.utils.timeutils import session_local_dt

BAD_FLAGS = ("hr_above_baseline", "poor_interval_recovery", "hard_days_too_close")


# ---------- чистая часть (pure) ----------

def tolerance_of(*, rating: int | None, pain_level: int | None, flags: list[str] | None,
                 hr_z: float | None, next_recovery_pct: int | None,
                 next_hrv_very_low: bool | None) -> tuple[bool | None, list[str]]:
    """Перенесена ли качественная хорошо: None — сигналов нет вовсе; иначе False при любом
    плохом сигнале. Возвращает (tolerated, причины плохого). (Per-session tolerance.)"""
    bad: list[str] = []
    seen = False
    if rating is not None:
        seen = True
        if rating >= QUALITY_RPE_HARD:
            bad.append(f"rpe {rating}")
    if pain_level is not None:
        seen = True
        if pain_level > 0:
            bad.append(f"pain {pain_level}")
    if flags is not None:
        seen = True
        bad += [f for f in flags if f in BAD_FLAGS]
    if hr_z is not None:
        seen = True
        if hr_z >= QUALITY_HR_Z_HIGH:
            bad.append(f"hr z {hr_z:.1f}")
    if next_recovery_pct is not None:
        seen = True
        if next_recovery_pct < RECOVERY_PCT_READY:
            bad.append(f"recovery {next_recovery_pct}%")
    if next_hrv_very_low:
        seen = True
        bad.append("hrv very_low")
    if not seen:
        return None, []
    return not bad, bad


def ladder_level(sessions: list[dict], *, phase: str, active_injury: bool,
                 run_days_max: int | None, week_start: date) -> tuple[int, list[str]]:
    """Уровень лестницы по качественным сессиям окна (pure).

    sessions — [{"date": date, "tolerated": bool | None}], любой порядок. week_start — понедельник
    планируемой недели: «последние две недели» = две полные недели перед ней.
    """
    reasons: list[str] = []
    level = PLAN_QUALITY_DAYS_MIN
    n = len(sessions)
    judged = [s for s in sessions if s.get("tolerated") is not None]
    good = sum(1 for s in judged if s["tolerated"])
    share = good / len(judged) if judged else None
    if phase != PHASE_STABLE:
        reasons.append(f"статус {phase} — один качественный день")
    elif active_injury:
        reasons.append("активная травма — один качественный день")
    elif n < QUALITY_LADDER_MIN_SESSIONS:
        reasons.append(f"качественных за {QUALITY_LADDER_WEEKS} нед: {n} < "
                       f"{QUALITY_LADDER_MIN_SESSIONS} — только начинаем")
    elif share is not None and share < QUALITY_LADDER_TOLERATED_SHARE:
        reasons.append(f"хорошо перенесено {good} из {len(judged)} — держим один день")
    else:
        w1, w2 = week_start - timedelta(days=7), week_start - timedelta(days=14)
        in_w1 = [s for s in sessions if w1 <= s["date"] < week_start]
        in_w2 = [s for s in sessions if w2 <= s["date"] < w1]
        if in_w1 and in_w2:
            level = 2
            reasons.append(f"переносимость хорошая ({good} из {len(judged)}), качественные две "
                           "недели подряд — два дня")
            both_two = len(in_w1) >= 2 and len(in_w2) >= 2
            all_good = all(s.get("tolerated") for s in in_w1 + in_w2)
            if both_two and all_good:
                level = 3
                reasons.append("две недели по два качественных без сбоев — три дня (гайд 41)")
        else:
            reasons.append("качественные не каждую неделю — один день")
    last = max(sessions, key=lambda s: s["date"]) if sessions else None
    if last is not None and last.get("tolerated") is False and level > PLAN_QUALITY_DAYS_MIN:
        level -= 1
        reasons.append("последняя качественная перенесена тяжело — ступень ниже")
    if run_days_max:
        cap = max(PLAN_QUALITY_DAYS_MIN, run_days_max - QUALITY_LADDER_RUN_DAYS_GAP)
        if level > cap:
            level = cap
            reasons.append(f"беговых дней {run_days_max} — лёгкие между качественными (гайд 45)")
    return min(level, PLAN_QUALITY_DAYS_CAP), reasons


# ---------- сборка из БД (read-only) ----------

def _hrv_very_low(dm) -> bool | None:
    if dm is None or dm.avg_sleep_hrv is None or dm.sleep_hrv_baseline is None:
        return None
    sd = dm.sleep_hrv_sd or dm.sleep_hrv_baseline * HRV_SD_FALLBACK_FACTOR
    return dm.avg_sleep_hrv < dm.sleep_hrv_baseline - 2 * sd


def quality_sessions(user_id: int, *, db: Session, today: date,
                     weeks: int = QUALITY_LADDER_WEEKS) -> list[dict]:
    """Качественные сессии окна с оценкой переносимости — сырьё для ladder_level."""
    user = db.query(User).filter(User.id == user_id).first()
    since_d = monday_of(today) - timedelta(weeks=weeks)
    since = datetime.combine(since_d - timedelta(days=1), time.min, tzinfo=timezone.utc)
    rows = db.query(TrainingSession).filter(
        TrainingSession.user_id == user_id, TrainingSession.begin_ts >= since).all()
    out: list[dict] = []
    for s in rows:
        if s.begin_ts is None or effective_training_type(s) not in HARD_TYPES:
            continue
        d = session_local_dt(s.begin_ts, s, user).date()
        if d < since_d:
            continue
        fb = db.query(TrainingFeedback).filter(TrainingFeedback.session_id == s.id).first()
        ins = InsightRepository.for_session(user_id, s.id, db=db)
        computed = (ins.computed_json or {}) if ins else None
        hr_z = ((computed.get("hr_vs_baseline") or {}).get("z")
                if computed and (computed.get("hr_vs_baseline") or {}).get("available") else None)
        dm = CoachRepository.metrics_for_date(user_id, d + timedelta(days=1), db=db)
        tolerated, bad = tolerance_of(
            rating=fb.rating if fb else None,
            pain_level=fb.pain_level if fb else None,
            flags=(computed.get("flags") if computed is not None else None),
            hr_z=hr_z,
            next_recovery_pct=dm.recovery_pct if dm else None,
            next_hrv_very_low=_hrv_very_low(dm))
        out.append({"date": d, "session_id": s.id, "type": effective_training_type(s),
                    "tolerated": tolerated, "bad": bad})
    out.sort(key=lambda x: x["date"])
    return out


def quality_ladder(user_id: int, *, db: Session, today: date, phase: str,
                   active_injury: bool, run_days_max: int | None,
                   week_start: date | None = None) -> dict:
    """Лестница качественных дней для week_targets (уровень + почему)."""
    sessions = quality_sessions(user_id, db=db, today=today)
    level, reasons = ladder_level(sessions, phase=phase, active_injury=active_injury,
                                  run_days_max=run_days_max,
                                  week_start=week_start or monday_of(today))
    judged = [s for s in sessions if s["tolerated"] is not None]
    last_bad = [s for s in sessions if s["tolerated"] is False]
    return {
        "level": level,
        "sessions_considered": len(sessions),
        "tolerated": sum(1 for s in judged if s["tolerated"]),
        "judged": len(judged),
        "last_bad_days_ago": (today - last_bad[-1]["date"]).days if last_bad else None,
        "reasons": reasons,
    }
