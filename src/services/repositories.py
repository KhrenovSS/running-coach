# Слой агрегационных запросов для модуля аналитики
# Aggregation query layer for the analytics module
#
# Этап 6 (BACKLOG #231): `db` — ОБЯЗАТЕЛЬНЫЙ параметр (keyword-only). Сессию владеет
# вызывающий код (web-роут, telegram-джоба, coach/state.py); репозиторий свои сессии
# не открывает и не закрывает — это делало транзакции несоставимыми.
# (`db` is required and caller-owned; repositories never open/close their own sessions.)

from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.analysis.hr_zones import get_zone
from src.config import settings
from src.models import TrainingSession, DailyMetrics, User, TrainingFeedback


class TrainingRepository:
    """Агрегационные запросы для тренировок (Aggregation queries for training sessions)."""

    @staticmethod
    def weekly_volume(user_id: int, weeks: int = 4, *, db: Session) -> list[dict]:
        """Объём тренировок по неделям (Weekly training volume).

        Недели считаются от понедельника в UTC. Группировка выполняется в Python (без
        Postgres-only `date_trunc`), чтобы метод работал и на SQLite (тесты).
        """
        since = datetime.now(timezone.utc) - timedelta(weeks=weeks)
        rows = db.query(
            TrainingSession.begin_ts,
            TrainingSession.total_distance_km,
            TrainingSession.duration_minutes,
        ).filter(
            TrainingSession.user_id == user_id,
            TrainingSession.begin_ts >= since,
        ).all()

        buckets: dict = {}  # week_start(date) -> [km, minutes, count]
        for begin_ts, km, minutes in rows:
            if begin_ts is None:
                continue
            d = begin_ts.date()
            week_start = d - timedelta(days=d.weekday())  # понедельник недели
            b = buckets.setdefault(week_start, [0.0, 0.0, 0])
            b[0] += float(km or 0)
            b[1] += float(minutes or 0)
            b[2] += 1

        return [
            {
                "week_start": ws,
                "total_km": b[0],
                "total_minutes": b[1],
                "session_count": b[2],
            }
            for ws, b in sorted(buckets.items())
        ]

    @staticmethod
    def km_in_window(user_id: int, end_ts: datetime, *, days: int = 7,
                     db: Session) -> float:
        """Километраж за окно (end_ts − days, end_ts] — «неделя до сессии включительно».

        Для потолков качества/длительной (METRICS_GUIDE M1.5/M1.6): окно от даты
        сессии честнее ISO-недели — сессия в понедельник не даёт долю ≈100%.
        (Rolling-window km ending at the session — fairer than the ISO week.)
        """
        since = end_ts - timedelta(days=days)
        total = db.query(func.sum(TrainingSession.total_distance_km)).filter(
            TrainingSession.user_id == user_id,
            TrainingSession.begin_ts > since,
            TrainingSession.begin_ts <= end_ts,
        ).scalar()
        return float(total or 0.0)

    @staticmethod
    def zone_distribution(user_id: int, days: int = 28, *, db: Session) -> dict:
        """Распределение времени по пульсовым зонам (Time distribution by HR zones)."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        user = db.query(User).filter(User.id == user_id).first()
        max_hr = user.max_hr if user else settings.default_max_hr
        sessions = db.query(TrainingSession).filter(
            TrainingSession.user_id == user_id,
            TrainingSession.begin_ts >= since,
        ).all()

        # Посекундные зоны из workout_insights, если посчитаны (#281): сегментное
        # «вся длительность в зону среднего пульса» кладёт пограничный км целиком
        # в одну зону и маркирует recovery интервальной как hard
        # (prefer per-second zones from computed insights over segment-avg buckets)
        from src.models import WorkoutInsight
        session_ids = [s.id for s in sessions]
        insights = {}
        if session_ids:
            rows = db.query(WorkoutInsight).filter(
                WorkoutInsight.session_id.in_(session_ids)).all()
            insights = {r.session_id: r.computed_json or {} for r in rows}

        zone_minutes = {"z1": 0.0, "z2": 0.0, "z3": 0.0, "z4": 0.0, "z5": 0.0}
        for session in sessions:
            tz = insights.get(session.id, {}).get("time_in_zones") or {}
            if tz.get("available") and tz.get("minutes"):
                for zone_key, minutes in tz["minutes"].items():
                    if zone_key in zone_minutes:
                        zone_minutes[zone_key] += minutes or 0.0
                continue
            # Fallback — сегментное приближение (нет computed_json у сессии)
            if not session.segments_json:
                continue
            for segment in session.segments_json:
                avg_hr = segment.get('avg_hr') or 0
                duration = segment.get('duration_min', 0) or 0
                zone = get_zone(avg_hr, max_hr)
                zone_key = f"z{zone}"
                if zone_key in zone_minutes:
                    zone_minutes[zone_key] += duration

        return zone_minutes

    @staticmethod
    def training_type_distribution(user_id: int, days: int = 28, *, db: Session) -> dict:
        """Распределение типов тренировок (Training type distribution)."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        results = db.query(
            TrainingSession.training_type,
            func.count(TrainingSession.id).label('count'),
        ).filter(
            TrainingSession.user_id == user_id,
            TrainingSession.begin_ts >= since,
        ).group_by(TrainingSession.training_type).all()

        return {r.training_type: r.count for r in results if r.training_type}


class HealthRepository:
    """Агрегационные запросы для метрик здоровья (Aggregation queries for health metrics)."""

    @staticmethod
    def hrv_trend(user_id: int, days: int = 30, *, db: Session) -> list[dict]:
        """Тренд HRV за период (HRV trend over period)."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        results = db.query(
            DailyMetrics.date,
            DailyMetrics.avg_sleep_hrv,
            DailyMetrics.sleep_hrv_baseline,
        ).filter(
            DailyMetrics.user_id == user_id,
            DailyMetrics.date >= since.date(),
            DailyMetrics.avg_sleep_hrv.isnot(None),
        ).order_by(DailyMetrics.date).all()

        return [
            {
                "date": r.date,
                "avg_sleep_hrv": float(r.avg_sleep_hrv),
                "baseline": float(r.sleep_hrv_baseline) if r.sleep_hrv_baseline is not None else None,
            }
            for r in results
        ]

    @staticmethod
    def vo2max_trend(user_id: int, days: int = 90, *, db: Session) -> list[dict]:
        """Тренд VO2max за период (VO2max trend over period)."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        results = db.query(
            DailyMetrics.date,
            DailyMetrics.vo2max,
        ).filter(
            DailyMetrics.user_id == user_id,
            DailyMetrics.date >= since.date(),
            DailyMetrics.vo2max.isnot(None),
        ).order_by(DailyMetrics.date).all()

        return [{"date": r.date, "vo2max": float(r.vo2max)} for r in results]

    # load_ratio удалён (BACKLOG #219): ACWR смещался (дни отдыха исключались),
    # ratio=0.0 был неотличим от «нет данных». Замена — CoachRepository.acwr
    # в src/services/repositories_coach.py. (Removed; replaced by CoachRepository.acwr.)


class FeedbackRepository:
    """Агрегация субъективных оценок (RPE 0–10) для аналитики (Training feedback / RPE aggregation)."""

    @staticmethod
    def avg_rating(user_id: int, days: int = 28, *, db: Session) -> float | None:
        """Средняя субъективная тяжесть за период (Average perceived effort over period)."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        val = db.query(func.avg(TrainingFeedback.rating)).filter(
            TrainingFeedback.user_id == user_id,
            TrainingFeedback.created_at >= since,
        ).scalar()
        return float(val) if val is not None else None

    @staticmethod
    def rating_for_session(session_id: int, *, db: Session) -> int | None:
        """Оценка конкретной тренировки (Rating for a specific session)."""
        fb = db.query(TrainingFeedback).filter(
            TrainingFeedback.session_id == session_id,
        ).first()
        return fb.rating if fb else None

    @staticmethod
    def ratings_with_sessions(user_id: int, days: int = 28, *, db: Session) -> list[dict]:
        """RPE в связке с параметрами сессии — для будущего skills/workout.py.

        (RPE paired with session params — for the future workout skill: predicted-vs-actual effort.)
        """
        since = datetime.now(timezone.utc) - timedelta(days=days)
        rows = db.query(
            TrainingFeedback.session_id,
            TrainingFeedback.rating,
            TrainingFeedback.created_at,
            TrainingSession.training_type,
            TrainingSession.training_type_override,
            TrainingSession.avg_pace,
            TrainingSession.avg_heart_rate,
            TrainingSession.total_distance_km,
        ).join(
            TrainingSession, TrainingFeedback.session_id == TrainingSession.id
        ).filter(
            TrainingFeedback.user_id == user_id,
            TrainingFeedback.created_at >= since,
        ).order_by(TrainingFeedback.created_at).all()

        return [
            {
                "session_id": r.session_id,
                "rating": r.rating,
                "created_at": r.created_at,
                "training_type": r.training_type,
                "training_type_override": r.training_type_override,
                "avg_pace": r.avg_pace,
                "avg_heart_rate": r.avg_heart_rate,
                "total_distance_km": r.total_distance_km,
            }
            for r in rows
        ]
