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
    def zone_distribution(user_id: int, days: int = 28, *, db: Session) -> dict:
        """Распределение времени по пульсовым зонам (Time distribution by HR zones)."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        user = db.query(User).filter(User.id == user_id).first()
        max_hr = user.max_hr if user else settings.default_max_hr
        sessions = db.query(TrainingSession).filter(
            TrainingSession.user_id == user_id,
            TrainingSession.begin_ts >= since,
        ).all()

        zone_minutes = {"z1": 0.0, "z2": 0.0, "z3": 0.0, "z4": 0.0, "z5": 0.0}
        for session in sessions:
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

    @staticmethod
    def load_ratio(user_id: int, days: int = 7, *, db: Session) -> dict:
        """Соотношение нагрузки (Acute:chronic load ratio).

        NB (BACKLOG): дни отдыха исключаются (`training_load IS NOT NULL`), поэтому ACWR смещён;
        `ratio=0.0` неотличим от «нет хронических данных». Рефактор — при реализации skills/load.
        """
        acute_since = datetime.now(timezone.utc) - timedelta(days=days)
        chronic_since = datetime.now(timezone.utc) - timedelta(days=days * 4)

        acute = db.query(func.avg(DailyMetrics.training_load)).filter(
            DailyMetrics.user_id == user_id,
            DailyMetrics.date >= acute_since.date(),
            DailyMetrics.training_load.isnot(None),
        ).scalar() or 0.0

        chronic = db.query(func.avg(DailyMetrics.training_load)).filter(
            DailyMetrics.user_id == user_id,
            DailyMetrics.date >= chronic_since.date(),
            DailyMetrics.training_load.isnot(None),
        ).scalar() or 0.0

        ratio = float(acute) / float(chronic) if chronic > 0 else 0.0
        return {"acute_load": float(acute), "chronic_load": float(chronic), "ratio": ratio}


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
                "avg_pace": r.avg_pace,
                "avg_heart_rate": r.avg_heart_rate,
                "total_distance_km": r.total_distance_km,
            }
            for r in rows
        ]
