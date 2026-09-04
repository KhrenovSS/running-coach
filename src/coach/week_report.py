# Недельный отчёт: детерминированные числа недели (weekly report numbers) — C8.1, 03.09.2026
#
# Решение владельца: отчёт должен мотивировать, показывать прогресс, называть слабое место и
# направление подготовки — не «писать ради письма». Поэтому все числа и предвыбор сигналов
# (highlights/concerns) считает код, а LLM только интерпретирует (инвариант §1 DEV_PLAN).
# Корзины недель — по ЛОКАЛЬНОЙ дате тренировки (как planning_window.week_done), полные
# недели пн–вс; TrainingRepository.weekly_volume (UTC, обрезанная первая корзина, #220)
# здесь сознательно не используется. Метрики здоровья (HRV/RHR/сон) в отчёт не входят
# (решение владельца 03.09.2026) — они остаются в утреннем вердикте.
# (Deterministic weekly numbers; LLM interprets, code selects the signals.)

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from statistics import mean, median

from sqlalchemy.orm import Session

from src.analysis.hr_zones import get_zone
from src.analysis.week_structure import is_quality_session
from src.coach.config import (
    DISTRIBUTION_80_20,
    EASY_TOO_HARD_WEEK_FLAGS,
    EFFICIENCY_GAIN_BPM,
    EFFICIENCY_LOSS_BPM,
    HARD_SHARE_OVERLOAD,
    LOAD_PROGRESSION,
    LONG_RUN_MAX_MIN,
    LONG_RUN_MAX_PCT_WEEK,
    MONOTONY_HIGH,
    MONOTONY_MIN_TRAIN_DAYS,
    POINTS_PER_MIN,
    WEEK_REPORT_ACWR_HIGH,
    WEEK_REPORT_AVG_WEEKS,
    WEEK_REPORT_SERIES_WEEKS,
)
from src.coach.skills.pain import recent_pain_by_day
from src.coach.util import effective_training_type
from src.coach.week_view import week_targets_stored
from src.models import DailyMetrics, TrainingSession, User, WorkoutInsight
from src.services.repositories import latest_lthr
from src.services.repositories_coach import CoachRepository
from src.utils.logger import get_logger
from src.utils.timeutils import session_local_dt

logger = get_logger("coach.week_report")

WEEK_REPORT_SCHEMA_VERSION = 1
_ZONES = ("z1", "z2", "z3", "z4", "z5")
_FLAG_EASY_TOO_HARD = "easy_run_too_hard"


def compute_week_report(user_id: int, *, db: Session, week_start: date, today: date,
                        weeks_back: int = WEEK_REPORT_SERIES_WEEKS,
                        next_week: dict | None = None,
                        adherence: dict | None = None) -> dict:
    """Числа отчёта за неделю week_start (пн) с рядом из weeks_back недель.

    today — локальная дата пользователя (вс = неделя закрыта; иначе week_in_progress).
    next_week — week_targets следующей недели (передаёт вызывающий, только в вс);
    adherence — planning.week_plan_review той же недели (передаёт вызывающий).
    (Weekly report numbers; caller supplies next-week targets and plan adherence.)
    """
    user = db.query(User).filter(User.id == user_id).first()
    max_hr = getattr(user, "max_hr", None)
    lthr = latest_lthr(user_id, db=db)
    series_start = week_start - timedelta(weeks=weeks_back - 1)
    week_end = week_start + timedelta(days=6)

    buckets = _bucket_sessions(user_id, db=db, user=user, first_monday=series_start,
                               last_day=week_end)
    insights = _insights_by_session(user_id, db=db, buckets=buckets)
    pain_by_day = recent_pain_by_day(user_id, days=weeks_back * 7 + 7, db=db)

    weeks = []
    for i in range(weeks_back):
        ws = series_start + timedelta(weeks=i)
        weeks.append(_week_stats(ws, buckets.get(ws, []), insights, max_hr=max_hr,
                                 lthr=lthr, pain_by_day=pain_by_day))
    this = weeks[-1]
    prev = weeks[-2] if len(weeks) > 1 else None
    past = [w for w in weeks[:-1] if w["runs"] > 0][-WEEK_REPORT_AVG_WEEKS:]
    avg = ({"km": round(mean(w["km"] for w in past), 1), "weeks": len(past)}
           if past else None)

    # P0 #308: монотонность/страйн Фостера за неделю (по дневным баллам нагрузки)
    from src.coach.load_monotony import daily_load_points, monotony_from_daily
    mono = monotony_from_daily(daily_load_points(user_id, db=db, start=week_start, days=7,
                                                 user=user, max_hr=max_hr, lthr=lthr))
    this["monotony"], this["strain"] = mono["monotony"], mono["strain"]
    this["trained_days"] = mono["trained_days"]

    targets = week_targets_stored(user_id, db=db, week_start=week_start)
    if targets.get("target_km") and this["km"] is not None:
        targets["pct_of_target"] = round(this["km"] / targets["target_km"], 2)

    report = {
        "schema_version": WEEK_REPORT_SCHEMA_VERSION,
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "week_in_progress": today < week_end,
        "this": this,
        "prev": prev,
        "avg_prev": avg,
        "series": [{"week_start": w["week_start"], "km": w["km"], "runs": w["runs"]}
                   for w in weeks],
        "targets": targets,
        "next_week": next_week,
        "adherence": adherence,
        "acwr": _load_ratio(user_id, db=db, week_end=week_end),
    }
    report["highlights"], report["concerns"] = _signals(report)
    report["missing"] = _missing(report)
    return report


def build_week_report(user_id: int, *, db: Session, today: date | None = None) -> dict:
    """Числа недели для отчёта и плана: вс — неделя закрыта, есть next_week (week_targets
    следующей) и сегодняшний невыполненный день считается пропущенным; среди недели
    (/report) — неделя идёт, next_week=None. (Weekly numbers shared by report and plan.)"""
    from src.coach import planning   # planning → week_view → … ; здесь импорт локальный от цикла
    from src.coach.planning_window import monday_of
    from src.utils.timeutils import user_now

    user = db.query(User).filter(User.id == user_id).first()
    today = today or user_now(user).date()
    week_start = monday_of(today)
    closing = today.weekday() == 6
    next_week = planning.week_targets(user_id, db=db, today=today) if closing else None
    adherence = planning.week_plan_review(user_id, db=db, week_start=week_start,
                                         include_today=closing)
    return compute_week_report(user_id, db=db, week_start=week_start, today=today,
                               next_week=next_week, adherence=adherence)


def _load_ratio(user_id: int, *, db: Session, week_end: date) -> float | None:
    """Острая/хроническая нагрузка на конец недели: ATI/CTI часов (Coros, coros doc §7),
    иначе локальный ACWR по training_load — только если острая нагрузка > 0 (в проде
    training_load часов почти всегда 0 → ratio 0.0 «низкая» врал бы). None — нет данных.
    (Acute:chronic ratio — watch ATI/CTI first, local ACWR only with real acute load.)"""
    dm = db.query(DailyMetrics).filter(
        DailyMetrics.user_id == user_id,
        DailyMetrics.date <= week_end,
        DailyMetrics.ati.isnot(None),
        DailyMetrics.cti.isnot(None),
        DailyMetrics.cti > 0,
    ).order_by(DailyMetrics.date.desc()).first()
    if dm is not None:
        return round(float(dm.ati) / float(dm.cti), 2)
    acwr = CoachRepository.acwr(user_id, db=db)
    if acwr.get("ratio") and acwr.get("acute_load", 0) > 0:
        return acwr["ratio"]
    return None


# --- сбор данных (data collection) -----------------------------------------------------

def _bucket_sessions(user_id: int, *, db: Session, user, first_monday: date,
                     last_day: date) -> dict[date, list[TrainingSession]]:
    """Тренировки по понедельникам недель, дата — локальная (local-date week buckets)."""
    since = datetime.combine(first_monday - timedelta(days=1), time.min, tzinfo=timezone.utc)
    until = datetime.combine(last_day + timedelta(days=2), time.min, tzinfo=timezone.utc)
    rows = db.query(TrainingSession).filter(
        TrainingSession.user_id == user_id,
        TrainingSession.begin_ts >= since,
        TrainingSession.begin_ts < until,
    ).all()
    buckets: dict[date, list[TrainingSession]] = {}
    for s in rows:
        if s.begin_ts is None:
            continue
        d = session_local_dt(s.begin_ts, s, user).date()
        if not first_monday <= d <= last_day:
            continue
        monday = d - timedelta(days=d.weekday())
        buckets.setdefault(monday, []).append(s)
    return buckets


def _insights_by_session(user_id: int, *, db: Session,
                         buckets: dict[date, list[TrainingSession]]) -> dict[int, dict]:
    ids = [s.id for items in buckets.values() for s in items]
    if not ids:
        return {}
    rows = db.query(WorkoutInsight).filter(
        WorkoutInsight.user_id == user_id,
        WorkoutInsight.session_id.in_(ids),
    ).all()
    return {r.session_id: (r.computed_json or {}) for r in rows}


def _session_zone_minutes(s: TrainingSession, computed: dict, *, max_hr, lthr) -> dict | None:
    """Минуты по зонам сессии: посекундные из computed, иначе по сегментам, иначе None."""
    tz = computed.get("time_in_zones") or {}
    if tz.get("available") and tz.get("minutes"):
        return {z: float(tz["minutes"].get(z) or 0.0) for z in _ZONES}
    if not s.segments_json or not max_hr:
        return None
    minutes = {z: 0.0 for z in _ZONES}
    known = False
    for seg in s.segments_json:
        avg_hr, dur = seg.get("avg_hr") or 0, seg.get("duration_min") or 0
        if not avg_hr or not dur:
            continue
        key = f"z{get_zone(avg_hr, max_hr, lthr)}"
        if key in minutes:
            minutes[key] += dur
            known = True
    return minutes if known else None


def _week_stats(week_start: date, items: list[TrainingSession], insights: dict[int, dict],
                *, max_hr, lthr, pain_by_day: dict) -> dict:
    """Числа одной недели (one week's numbers)."""
    km = minutes = 0.0
    quality = 0
    long_km, long_min = 0.0, 0.0
    zone_minutes = {z: 0.0 for z in _ZONES}
    zone_known = False
    load = 0.0
    load_known = False
    eff: list[float] = []
    cadence: list[int] = []
    flags: Counter = Counter()
    for s in items:
        s_km = float(s.total_distance_km or 0.0)
        s_min = float(s.duration_minutes or 0.0)
        km += s_km
        minutes += s_min
        if is_quality_session(effective_training_type(s), s.avg_heart_rate, max_hr, lthr):
            quality += 1
        if s_km > long_km:
            long_km, long_min = s_km, s_min
        computed = insights.get(s.id) or {}
        zm = _session_zone_minutes(s, computed, max_hr=max_hr, lthr=lthr)
        if zm is not None:
            zone_known = True
            for z in _ZONES:
                zone_minutes[z] += zm[z]
            load += sum(zm[z] * POINTS_PER_MIN.get(z, 0.0) for z in _ZONES)
            load_known = True
        hb = computed.get("hr_vs_baseline") or {}
        if hb.get("delta_bpm") is not None:
            eff.append(float(hb["delta_bpm"]))
        if s.avg_cadence:
            cadence.append(int(s.avg_cadence))
        for f in computed.get("flags") or []:
            flags[f] += 1
    total_zone = sum(zone_minutes.values())
    easy_share = ((zone_minutes["z1"] + zone_minutes["z2"]) / total_zone
                  if zone_known and total_zone > 0 else None)
    runs = len(items)
    week_days = [week_start + timedelta(days=i) for i in range(7)]
    return {
        "week_start": week_start.isoformat(),
        "km": round(km, 1),
        "minutes": round(minutes),
        "runs": runs,
        "quality_runs": quality,
        "long_run_km": round(long_km, 1) if runs else None,
        "long_run_min": round(long_min) if runs else None,
        # доля длительной осмысленна от двух пробежек (single run = trivially 100%)
        "long_run_share": round(long_km / km, 2) if runs >= 2 and km > 0 else None,
        "easy_time_share": round(easy_share, 2) if easy_share is not None else None,
        "hard_time_share": round(1 - easy_share, 2) if easy_share is not None else None,
        "load_points": round(load) if load_known else None,
        "efficiency_delta_bpm": round(mean(eff), 1) if eff else None,
        "efficiency_n": len(eff),
        "cadence_median": int(median(cadence)) if cadence else None,
        "pain_days": sum(1 for d in week_days if (pain_by_day.get(d) or 0) > 0),
        "flags": dict(flags),
    }


# --- сигналы для LLM (pre-selected signals) --------------------------------------------

def _signals(r: dict) -> tuple[list[dict], list[dict]]:
    """Предвыбор кодом: что хвалить (highlights) и что тревожит (concerns).

    LLM выбирает по одному из каждого списка и не выдумывает своих (промпт).
    Пороги — именованные константы coach/config (зеркало гайдов 10/20/30/44/45).
    """
    this, prev, targets = r["this"], r.get("prev"), r.get("targets") or {}
    hi: list[dict] = []
    co: list[dict] = []

    def h(key, hint, **ev):
        hi.append({"key": key, "hint": hint, "evidence": ev})

    def c(key, hint, **ev):
        co.append({"key": key, "hint": hint, "evidence": ev})

    if this["runs"] == 0:
        if not r.get("week_in_progress"):
            c("no_runs", "пробежек на неделе не было — форма не теряется до 5 дней, но пауза длиннее уже сказывается")
        return hi, co

    eff, n = this["efficiency_delta_bpm"], this["efficiency_n"]
    if eff is not None and n >= 2:
        if eff <= EFFICIENCY_GAIN_BPM:
            h("efficiency_gain", "пульс на своём темпе ниже базовой линии — аэробная база растёт (главный маркер прогресса по Лидьярду)",
              delta_bpm=eff, sessions=n)
        elif eff >= EFFICIENCY_LOSS_BPM:
            c("efficiency_loss", "пульс на своём темпе выше базовой линии — усталость, жара или недовосстановление",
              delta_bpm=eff, sessions=n)

    easy, hard = this["easy_time_share"], this["hard_time_share"]
    target = DISTRIBUTION_80_20["easy_share_target"]
    if easy is not None:
        if hard > HARD_SHARE_OVERLOAD:
            c("intensity_overload", "больше трети времени недели в Z3+ — следующая неделя почти целиком лёгкая (гайд 10)",
              hard_share=hard)
        elif easy >= target:
            h("easy_share_ok", "доля лёгкого времени в цели 80/20 — интенсивность распределена правильно",
              easy_share=easy)
        elif easy < target - DISTRIBUTION_80_20["tolerance"]:
            c("easy_share_low", "лёгкого времени меньше цели 80/20 — лёгкие пробежки бегутся слишком быстро",
              easy_share=easy)

    if prev and prev["km"] > 0:
        step_pct = round((this["km"] - prev["km"]) / prev["km"] * 100, 1)
        if step_pct > LOAD_PROGRESSION["max_weekly_increase_pct"]:
            c("volume_jump", "объём вырос быстрее безопасного шага — скачок объёма главный предвестник травмы (гайд 20)",
              step_pct=step_pct, max_pct=LOAD_PROGRESSION["max_weekly_increase_pct"])
        elif 0 < step_pct <= LOAD_PROGRESSION["max_weekly_increase_pct"] and this["pain_days"] == 0:
            h("volume_step_ok", "объём вырос в пределах безопасного шага и без боли — правильная постепенность",
              step_pct=step_pct)

    share, lmin = this["long_run_share"], this["long_run_min"]
    if (share is not None and share > LONG_RUN_MAX_PCT_WEEK) or (lmin and lmin > LONG_RUN_MAX_MIN):
        c("long_run_share_high", "длительная слишком большая относительно недели — растить её можно только вместе с общим объёмом (гайд 45)",
          share=share, minutes=lmin)

    if this["pain_days"] > 0:
        c("pain_days", "были дни с болью — рост нагрузки после боли равен нулю (гайд 30)",
          days=this["pain_days"])
    elif prev and prev["pain_days"] > 0:
        h("pain_free_week", "неделя без боли после недели с болью — колено отвечает на нагрузку правильно")

    if prev and this["runs"] > prev["runs"] and this["pain_days"] == 0:
        h("frequency_up", "пробежек больше, чем неделей раньше, и без боли — сначала частота, потом объём (Дэниелс/Лидьярд)",
          runs=this["runs"], prev_runs=prev["runs"])

    if (this.get("monotony") is not None and this["monotony"] > MONOTONY_HIGH
            and (this.get("trained_days") or 0) >= MONOTONY_MIN_TRAIN_DAYS):
        c("monotony_high", "нагрузка почти одинаковая день за днём без дня отдыха — монотонность по Фостеру повышает риск болезни и травмы, нужна вариативность",
          monotony=this["monotony"], trained_days=this["trained_days"])

    if r.get("acwr") is not None and r["acwr"] > WEEK_REPORT_ACWR_HIGH:
        c("acwr_high", "острая нагрузка заметно выше хронической — организму нужна разгрузка",
          ratio=r["acwr"])

    if (this["flags"].get(_FLAG_EASY_TOO_HARD) or 0) >= EASY_TOO_HARD_WEEK_FLAGS:
        c("easy_runs_too_hard", "несколько лёгких пробежек за неделю были слишком быстрыми — лёгкий день должен быть лёгким",
          count=this["flags"][_FLAG_EASY_TOO_HARD])

    adh = r.get("adherence") or {}
    if adh.get("planned"):
        if adh.get("missed", 0) == 0 and adh.get("done", 0) == adh["planned"]:
            h("plan_complete", "план недели выполнен полностью — дисциплина, на которой строится база",
              planned=adh["planned"])
        elif adh.get("missed", 0) >= 2:
            c("plan_missed", "пропущено несколько плановых дней — стоит понять причину, а не наращивать план",
              missed=adh["missed"], planned=adh["planned"])
    return hi, co


def _missing(r: dict) -> list[str]:
    this = r["this"]
    missing = []
    if this["easy_time_share"] is None:
        missing.append("easy_time_share (нет пульса/зон на неделе)")
    if this["efficiency_delta_bpm"] is None:
        missing.append("efficiency (нет базовой линии пульс↔темп или разборов)")
    if not (r.get("targets") or {}).get("target_km"):
        missing.append("targets (план на эту неделю не составлялся)")
    if r.get("acwr") is None:
        missing.append("acwr (мало дней с нагрузкой часов)")
    if r.get("adherence") is None:
        missing.append("adherence (плановых строк недели нет)")
    return missing
