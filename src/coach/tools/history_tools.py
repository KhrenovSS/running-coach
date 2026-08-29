# Tools истории (History tools): тренировки, ряды метрик, недельная сводка — DEV_PLAN §5

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.analysis.hr_zones import get_band, get_zone
from src.coach.config import DISTRIBUTION_80_20, EASY_TYPES, LOAD_PROGRESSION
from src.coach.skills.pain import recent_pain_by_day
from src.coach.tools.context import ToolContext
from src.coach.util import effective_training_type
from src.config import settings
from src.exceptions import NotFoundError
from src.models import TrainingSession, User
from src.services.analytics_helpers import compute_slope, compute_trend_direction
from src.services.repositories import FeedbackRepository, TrainingRepository
from src.services.repositories_coach import CoachRepository
from src.utils.timeutils import WEEKDAYS_RU, session_local_dt, user_now

MAX_SEGMENTS = 20   # больше — только агрегат (above this, aggregate only)
MAX_POINTS = 60     # даунсэмпл рядов (series downsampling cap)


def _session_brief(s: TrainingSession, rpe: int | None, pain: int | None,
                   user: User | None = None) -> dict:
    # Локальное время: пояс тренировки → пояс пользователя → settings
    # (local time: workout zone → user zone → settings)
    local = session_local_dt(s.begin_ts, s, user) if s.begin_ts else None
    today = user_now(user).date()
    return {
        "session_id": s.id,
        "date": local.date().isoformat() if local else None,
        # Относительные даты и время суток LLM берёт ТОЛЬКО отсюда
        # (0 = сегодня, 1 = вчера; started_at_local — единственный источник времени суток)
        "days_ago": (today - local.date()).days if local else None,
        "started_at_local": local.strftime("%Y-%m-%d %H:%M") if local else None,
        "weekday": WEEKDAYS_RU[local.weekday()] if local else None,
        "tz": local.tzinfo.key if local else None,
        "type": effective_training_type(s),
        "km": s.total_distance_km,
        "duration_min": s.duration_minutes,
        "avg_pace": s.avg_pace,
        "avg_hr": s.avg_heart_rate,
        "max_hr": s.max_heart_rate,
        "training_effect": s.training_effect,
        "rpe": rpe,
        "pain_level": pain,
        "suspect": bool(s.suspect_flags),
    }


def get_recent_workouts(ctx: ToolContext, args: dict) -> dict:
    """Последние тренировки с RPE и болью (recent workouts with RPE and pain)."""
    limit = int(args.get("limit", 5))
    sessions = CoachRepository.last_sessions(ctx.user_id, n=limit, db=ctx.db)
    user = ctx.db.query(User).filter(User.id == ctx.user_id).first()
    out = []
    for s in sessions:
        _, fb = CoachRepository.session_with_feedback(ctx.user_id, s.id, db=ctx.db)
        out.append(_session_brief(s, fb.rating if fb else None,
                                  fb.pain_level if fb else None, user=user))
    return {"workouts": out}


def get_workout_detail(ctx: ToolContext, args: dict) -> dict:
    """Детали одной тренировки: зоны, сегменты, боль (single workout detail).

    Ownership проверяется внутри — чужая сессия не читается (raises NotFoundError).
    """
    session_id = int(args["session_id"])
    session, fb = CoachRepository.session_with_feedback(ctx.user_id, session_id, db=ctx.db)
    if session is None:
        raise NotFoundError("training", session_id)

    user = ctx.db.query(User).filter(User.id == ctx.user_id).first()
    max_hr = user.max_hr if user else settings.default_max_hr
    zone_minutes = {f"z{i}": 0.0 for i in range(1, 6)}
    band_minutes = {"easy": 0.0, "moderate": 0.0, "hard": 0.0}
    segments = []
    prev_temp = prev_code = None
    for i, seg in enumerate(session.segments_json or [], 1):
        avg_hr = seg.get("avg_hr") or 0
        dur = seg.get("duration_min", 0) or 0
        zone_minutes[f"z{get_zone(avg_hr, max_hr)}"] += dur
        band_minutes[get_band(avg_hr, max_hr)] += dur
        if len(segments) < MAX_SEGMENTS:
            # D4: полный сегмент — рельеф/каденс/длительность; погода дельтой
            # (full segment; weather delta-encoded — it rarely changes mid-run)
            row = {"n": i, "km": seg.get("distance_km"),
                   "duration_min": dur or None,
                   "pace": seg.get("pace_min_km") or seg.get("pace"),
                   "avg_hr": avg_hr or None,
                   "zone": seg.get("zone"), "band": seg.get("band"),
                   "elevation_gain": seg.get("elevation_gain"),
                   "elevation_loss": seg.get("elevation_loss"),
                   "avg_cadence": seg.get("avg_cadence")}
            temp, code = seg.get("temperature"), seg.get("weather_code")
            if temp is not None and temp != prev_temp:
                row["temperature"] = temp
                prev_temp = temp
            if code is not None and code != prev_code:
                row["weather_code"] = code
                prev_code = code
            segments.append({k: v for k, v in row.items() if v is not None})

    brief = _session_brief(session, fb.rating if fb else None,
                           fb.pain_level if fb else None, user=user)
    # D4: метрики утра дня тренировки — состояние «на тот день», не «сегодня».
    # Дата — локальная (#265: вечерняя пробежка после 00:00 UTC подтягивала
    # утро не того дня). (Day-of-workout morning metrics by LOCAL date.)
    dm = (CoachRepository.metrics_for_date(
              ctx.user_id, session_local_dt(session.begin_ts, session, user).date(),
              db=ctx.db)
          if session.begin_ts else None)
    brief.update({
        "zone_minutes": zone_minutes,
        "band_minutes": band_minutes,
        "segments": segments,
        "segments_total": len(session.segments_json or []),
        "pain_location": fb.pain_location if fb else None,
        "pain_phase": fb.pain_phase if fb else None,
        "notes": fb.notes if fb else None,
        "weather": {"temp_c": session.avg_temperature,
                    "weather_code": session.weather_code},
        "elevation_gain": session.elevation_gain,
        "elevation_loss": session.elevation_loss,
        "avg_cadence": session.avg_cadence,
        "daily_metrics_morning": ({
            "hrv": dm.avg_sleep_hrv, "hrv_baseline": dm.sleep_hrv_baseline,
            "rhr": dm.rhr, "recovery_pct": dm.recovery_pct,
            "tired_rate": dm.tired_rate,
        } if dm else None),
        "suspect_flags": session.suspect_flags or [],
    })
    return brief


def _downsample(points: list[dict]) -> list[dict]:
    if len(points) <= MAX_POINTS:
        return points
    step = len(points) / MAX_POINTS
    return [points[int(i * step)] for i in range(MAX_POINTS)]


def get_metrics_series(ctx: ToolContext, args: dict) -> dict:
    """Ряд метрики + тренд (metric series with slope and direction)."""
    metric = args["metric"]
    days = int(args.get("days", 30))
    if metric == "weight":
        raw = CoachRepository.weight_series(ctx.user_id, days=days, db=ctx.db)
    elif metric == "pain":
        by_day = recent_pain_by_day(ctx.user_id, days=days, db=ctx.db)
        raw = sorted(by_day.items())
    else:
        raw = CoachRepository.metrics_series(ctx.user_id, metric, days, db=ctx.db)

    points = [{"date": d.isoformat(), "value": v} for d, v in raw]
    values = [v for _, v in raw]
    present = [v for v in values if v is not None]
    baseline = None
    if metric == "hrv":
        dm = CoachRepository.latest_metrics(ctx.user_id, db=ctx.db)
        baseline = dm.sleep_hrv_baseline if dm else None
    return {
        "metric": metric,
        "days": days,
        "points": _downsample(points),
        "mean": round(sum(present) / len(present), 2) if present else None,
        "slope": compute_slope(values),
        "direction": compute_trend_direction(values),
        "baseline": baseline,
        "n_missing": len(values) - len(present),
    }


def get_weekly_summary(ctx: ToolContext, args: dict) -> dict:
    """Недельные объёмы + 80/20 + правило прогрессии (weekly volumes, 80/20, progression).

    Здесь живут числа бывшего правила P3 — вывод «что с этим делать» за LLM.
    """
    weeks = int(args.get("weeks", 4))
    volumes = TrainingRepository.weekly_volume(ctx.user_id, weeks=weeks, db=ctx.db)

    since = datetime.now(timezone.utc) - timedelta(weeks=weeks)
    sessions = ctx.db.query(TrainingSession).filter(
        TrainingSession.user_id == ctx.user_id,
        TrainingSession.begin_ts >= since,
    ).all()
    types_by_week: dict = {}
    easy_min_by_week: dict = {}
    total_min_by_week: dict = {}
    for s in sessions:
        if s.begin_ts is None:
            continue
        d = s.begin_ts.date()
        ws = (d - timedelta(days=d.weekday())).isoformat()
        ttype = effective_training_type(s) or "unknown"
        types_by_week.setdefault(ws, {}).setdefault(ttype, 0)
        types_by_week[ws][ttype] += 1
        total_min_by_week[ws] = total_min_by_week.get(ws, 0) + (s.duration_minutes or 0)
        if ttype in EASY_TYPES:
            easy_min_by_week[ws] = easy_min_by_week.get(ws, 0) + (s.duration_minutes or 0)

    out_weeks = []
    for v in volumes:
        ws = v["week_start"].isoformat()
        total = total_min_by_week.get(ws, 0)
        easy = easy_min_by_week.get(ws, 0)
        out_weeks.append({
            "week_start": ws,
            "km": round(v["total_km"], 1),
            "minutes": round(v["total_minutes"], 0),
            "sessions": v["session_count"],
            "types": types_by_week.get(ws, {}),
            "easy_share": round(easy / total, 2) if total > 0 else None,
        })

    wow = None
    if len(out_weeks) >= 2 and out_weeks[-2]["km"] > 0:
        wow = round((out_weeks[-1]["km"] - out_weeks[-2]["km"])
                    / out_weeks[-2]["km"] * 100, 1)
    avg_rpe = FeedbackRepository.avg_rating(ctx.user_id, days=weeks * 7, db=ctx.db)
    return {
        "weeks": out_weeks,
        "target_easy_share": DISTRIBUTION_80_20["easy_share_target"],
        "tolerance": DISTRIBUTION_80_20["tolerance"],
        "wow_change_pct": wow,
        "max_allowed_increase_pct": LOAD_PROGRESSION["max_weekly_increase_pct"],
        "avg_rpe": avg_rpe,
    }
