# Репозиторий модуля коуча (Coach module repository) — DEV_PLAN §6
#
# Конвенция Этапа 6 (BACKLOG #231): `db` — ОБЯЗАТЕЛЬНЫЙ keyword-only параметр,
# сессию владеет вызывающий код; репозиторий свои сессии не открывает.
# (db is a required keyword-only parameter; the caller owns the session.)

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from statistics import median

from sqlalchemy.orm import Session

from src.coach.config import (
    ACWR_ACUTE_DAYS,
    ACWR_CHRONIC_DAYS,
    ACWR_CHRONIC_MIN_DAYS,
    HARD_TYPES,
    RHR_BASELINE_DAYS,
    RHR_BASELINE_MIN_POINTS,
)
from src.coach.util import effective_training_type
from src.models import (CoachMessage, DailyMetrics, TrainingFeedback,
                        TrainingSession, WeightMeasurement)

# Whitelist полей DailyMetrics для рядов — никакого getattr по строке от LLM.
# (Whitelist of DailyMetrics fields for series — never getattr on an LLM string.)
METRIC_FIELDS = {
    "hrv": DailyMetrics.avg_sleep_hrv,
    "rhr": DailyMetrics.rhr,
    "tired_rate": DailyMetrics.tired_rate,
    "recovery_pct": DailyMetrics.recovery_pct,
    "training_load": DailyMetrics.training_load,
    "vo2max": DailyMetrics.vo2max,
}


class CoachRepository:
    """Выборки для скиллов и state коуча (queries for coach skills and state)."""

    @staticmethod
    def latest_metrics(user_id: int, *, db: Session) -> DailyMetrics | None:
        """Свежайшая строка DailyMetrics (freshest daily metrics row)."""
        return db.query(DailyMetrics).filter(
            DailyMetrics.user_id == user_id,
        ).order_by(DailyMetrics.date.desc()).first()

    @staticmethod
    def metrics_for_date(user_id: int, day: date, *, db: Session) -> DailyMetrics | None:
        """Метрики конкретного дня — «утро дня тренировки» для разбора (D4)."""
        return db.query(DailyMetrics).filter(
            DailyMetrics.user_id == user_id,
            DailyMetrics.date == day,
        ).first()

    @staticmethod
    def metrics_series(user_id: int, field: str, days: int, *, db: Session,
                       ) -> list[tuple[date, float | None]]:
        """Ряд (date, value) по whitelist-полю за N дней (metric series over N days)."""
        col = METRIC_FIELDS.get(field)
        if col is None:
            raise ValueError(f"unknown metric field: {field!r}")
        since = datetime.now(timezone.utc).date() - timedelta(days=days)
        rows = db.query(DailyMetrics.date, col).filter(
            DailyMetrics.user_id == user_id,
            DailyMetrics.date >= since,
        ).order_by(DailyMetrics.date).all()
        return [(r[0], float(r[1]) if r[1] is not None else None) for r in rows]

    @staticmethod
    def weight_series(user_id: int, days: int = 90, *, db: Session,
                      ) -> list[tuple[date, float]]:
        """Ряд веса из weight_measurements (weight series)."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        rows = db.query(WeightMeasurement.measured_at, WeightMeasurement.weight_kg).filter(
            WeightMeasurement.user_id == user_id,
            WeightMeasurement.measured_at >= since,
        ).order_by(WeightMeasurement.measured_at).all()
        return [(r[0].date(), float(r[1])) for r in rows]

    @staticmethod
    def last_sessions(user_id: int, n: int = 10, *, db: Session) -> list[TrainingSession]:
        """Последние N тренировок, свежие первыми (last N sessions, newest first)."""
        return db.query(TrainingSession).filter(
            TrainingSession.user_id == user_id,
        ).order_by(TrainingSession.begin_ts.desc()).limit(n).all()

    @staticmethod
    def session_with_feedback(user_id: int, session_id: int, *, db: Session,
                              ) -> tuple[TrainingSession | None, TrainingFeedback | None]:
        """Сессия + её оценка, с проверкой владельца (session + feedback, ownership-checked)."""
        session = db.query(TrainingSession).filter(
            TrainingSession.id == session_id,
            TrainingSession.user_id == user_id,
        ).first()
        if session is None:
            return None, None
        fb = db.query(TrainingFeedback).filter(
            TrainingFeedback.session_id == session_id,
        ).first()
        return session, fb

    @staticmethod
    def consecutive_hard_days(user_id: int, *, db: Session) -> int:
        """Подряд идущие «тяжёлые» дни, начиная с сегодня (consecutive hard days).

        День тяжёлый, если есть сессия с эффективным типом из HARD_TYPES.
        День без тяжёлой сессии (или вообще без сессий) обрывает серию.
        """
        since = datetime.now(timezone.utc) - timedelta(days=14)
        sessions = db.query(TrainingSession).filter(
            TrainingSession.user_id == user_id,
            TrainingSession.begin_ts >= since,
        ).all()
        hard_days = {
            s.begin_ts.date() for s in sessions
            if s.begin_ts is not None and effective_training_type(s) in HARD_TYPES
        }
        streak = 0
        day = datetime.now(timezone.utc).date()
        while day in hard_days:
            streak += 1
            day -= timedelta(days=1)
        return streak

    @staticmethod
    def baseline_rhr(user_id: int, days: int = RHR_BASELINE_DAYS, *, db: Session,
                     ) -> int | None:
        """Baseline RHR — медиана за окно, БЕЗ сегодняшнего дня (median RHR excluding today).

        Сегодняшнее значение исключается: иначе аномалия сама сдвигает базу, с которой
        её сравнивают. Меньше RHR_BASELINE_MIN_POINTS точек → None (базы нет).
        """
        today = datetime.now(timezone.utc).date()
        since = today - timedelta(days=days)
        rows = db.query(DailyMetrics.rhr).filter(
            DailyMetrics.user_id == user_id,
            DailyMetrics.date >= since,
            DailyMetrics.date < today,
            DailyMetrics.rhr.isnot(None),
        ).all()
        values = [float(r[0]) for r in rows]
        if len(values) < RHR_BASELINE_MIN_POINTS:
            return None
        # int: rhr_anomaly сравнивает и форматирует diff как целые bpm (int bpm expected)
        return int(round(median(values)))

    @staticmethod
    def acwr(user_id: int, acute_days: int = ACWR_ACUTE_DAYS, *, db: Session) -> dict:
        """ACWR: острая/хроническая нагрузка (acute:chronic workload ratio).

        Исправляет BACKLOG #219: дни без записи или без training_load считаются
        нулевой нагрузкой (день отдыха), а не исключаются из среднего; при
        < ACWR_CHRONIC_MIN_DAYS дней с данными в хроническом окне ratio = None
        («нет данных» отличимо от «нет нагрузки»).
        """
        today = datetime.now(timezone.utc).date()
        chronic_since = today - timedelta(days=ACWR_CHRONIC_DAYS - 1)
        acute_since = today - timedelta(days=acute_days - 1)

        rows = db.query(DailyMetrics.date, DailyMetrics.training_load).filter(
            DailyMetrics.user_id == user_id,
            DailyMetrics.date >= chronic_since,
        ).all()
        by_day: dict[date, float] = {
            r[0]: float(r[1]) for r in rows if r[1] is not None
        }
        days_with_data = len(by_day)

        # Средние по ПОЛНОЙ длине окна: отсутствующий день = 0 нагрузки (день отдыха).
        acute_total = sum(v for d, v in by_day.items() if d >= acute_since)
        chronic_total = sum(by_day.values())
        acute_load = acute_total / acute_days
        chronic_load = chronic_total / ACWR_CHRONIC_DAYS

        if days_with_data < ACWR_CHRONIC_MIN_DAYS or chronic_load == 0:
            ratio = None
        else:
            ratio = round(acute_load / chronic_load, 2)
        return {
            "acute_load": round(acute_load, 1),
            "chronic_load": round(chronic_load, 1),
            "ratio": ratio,
            "days_with_data": days_with_data,
        }

    @staticmethod
    def metric_days_count(user_id: int, days: int = 90, *, db: Session) -> int:
        """Сколько дней с метриками за окно — вход data_confidence (days with metrics)."""
        since = datetime.now(timezone.utc).date() - timedelta(days=days)
        return db.query(DailyMetrics).filter(
            DailyMetrics.user_id == user_id,
            DailyMetrics.date >= since,
        ).count()

    @staticmethod
    def sessions_count(user_id: int, days: int = 90, *, db: Session) -> int:
        """Сколько тренировок за окно — вход data_confidence (sessions in window)."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        return db.query(TrainingSession).filter(
            TrainingSession.user_id == user_id,
            TrainingSession.begin_ts >= since,
        ).count()

    @staticmethod
    def turns_today(user_id: int, *, db: Session) -> int:
        """Сколько LLM-ходов сегодня — дневной бюджет (LLM turns today, budget gate)."""
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0,
                                                         second=0, microsecond=0)
        return db.query(CoachMessage).filter(
            CoachMessage.user_id == user_id,
            CoachMessage.role == "assistant",
            CoachMessage.created_at >= today_start,
        ).count()

    @staticmethod
    def recent_messages(user_id: int, limit: int = 8, *, db: Session) -> list[CoachMessage]:
        """Последние сообщения диалога, старые первыми (recent chat, oldest first)."""
        rows = db.query(CoachMessage).filter(
            CoachMessage.user_id == user_id,
        ).order_by(CoachMessage.created_at.desc(), CoachMessage.id.desc()).limit(limit).all()
        return list(reversed(rows))

    @staticmethod
    def save_message(user_id: int, role: str, text: str, *, db: Session,
                     kind: str = "chat", meta: dict | None = None,
                     tokens_in: int | None = None, tokens_out: int | None = None,
                     cost_usd: float | None = None) -> CoachMessage:
        """Записать сообщение диалога (persist one chat message)."""
        msg = CoachMessage(user_id=user_id, role=role, kind=kind, text=text,
                           meta_json=meta, tokens_in=tokens_in,
                           tokens_out=tokens_out, cost_usd=cost_usd)
        db.add(msg)
        db.commit()
        return msg
