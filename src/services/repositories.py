# Слой агрегационных запросов для модуля аналитики
# Aggregation query layer for the analytics module

from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from src.analysis.hr_zones import get_zone
from src.config import settings
from src.models import SessionLocal, TrainingSession, DailyMetrics, User


class TrainingRepository:
    """Агрегационные запросы для тренировок (Aggregation queries for training sessions)."""

    @staticmethod
    def weekly_volume(user_id: int, weeks: int = 4) -> list[dict]:
        """Объём тренировок по неделям (Weekly training volume)."""
        db = SessionLocal()
        try:
            since = datetime.now(timezone.utc) - timedelta(weeks=weeks)
            results = db.query(
                func.date_trunc('week', TrainingSession.begin_ts).label('week_start'),
                func.sum(TrainingSession.total_distance_km).label('total_km'),
                func.sum(TrainingSession.duration_minutes).label('total_minutes'),
                func.count(TrainingSession.id).label('session_count'),
            ).filter(
                TrainingSession.user_id == user_id,
                TrainingSession.begin_ts >= since,
            ).group_by(
                func.date_trunc('week', TrainingSession.begin_ts)
            ).order_by('week_start').all()

            return [
                {
                    "week_start": r.week_start.date() if r.week_start else None,
                    "total_km": float(r.total_km or 0),
                    "total_minutes": float(r.total_minutes or 0),
                    "session_count": r.session_count,
                }
                for r in results
            ]
        finally:
            db.close()

    @staticmethod
    def zone_distribution(user_id: int, days: int = 28) -> dict:
        """Распределение времени по пульсовым зонам (Time distribution by HR zones)."""
        db = SessionLocal()
        try:
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
        finally:
            db.close()

    @staticmethod
    def training_type_distribution(user_id: int, days: int = 28) -> dict:
        """Распределение типов тренировок (Training type distribution)."""
        db = SessionLocal()
        try:
            since = datetime.now(timezone.utc) - timedelta(days=days)
            results = db.query(
                TrainingSession.training_type,
                func.count(TrainingSession.id).label('count'),
            ).filter(
                TrainingSession.user_id == user_id,
                TrainingSession.begin_ts >= since,
            ).group_by(TrainingSession.training_type).all()

            return {r.training_type: r.count for r in results if r.training_type}
        finally:
            db.close()


class HealthRepository:
    """Агрегационные запросы для метрик здоровья (Aggregation queries for health metrics)."""

    @staticmethod
    def hrv_trend(user_id: int, days: int = 30) -> list[dict]:
        """Тренд HRV за период (HRV trend over period)."""
        db = SessionLocal()
        try:
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
                    "baseline": float(r.sleep_hrv_baseline) if r.sleep_hrv_baseline else None,
                }
                for r in results
            ]
        finally:
            db.close()

    @staticmethod
    def vo2max_trend(user_id: int, days: int = 90) -> list[dict]:
        """Тренд VO2max за период (VO2max trend over period)."""
        db = SessionLocal()
        try:
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
        finally:
            db.close()

    @staticmethod
    def load_ratio(user_id: int, days: int = 7) -> dict:
        """Соотношение нагрузки (Acute:chronic load ratio)."""
        db = SessionLocal()
        try:
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
        finally:
            db.close()
