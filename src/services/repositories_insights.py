# Репозиторий итогов разбора (Workout insights repository) — DEV_PLAN §9 D1
#
# Строка workout_insights = персистентный итог разбора + элемент очереди
# отложенного разбора. Претендентов на исполнение разводит атомарный claim
# (UPDATE ... WHERE status='pending'), ADR «Решение 4» в docs/coach/ARCHITECTURE.md.
# (One row = persisted review outcome AND deferred-review queue item; the atomic
# claim arbitrates competing executors.)

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.models import WorkoutInsight

REVIEW_MAX_ATTEMPTS = 3  # после — status='error', разбор не повторяем


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InsightRepository:
    """Все методы принимают db keyword-only — сессией владеет вызывающий (§8 CLAUDE.md)."""

    @staticmethod
    def upsert(user_id: int, session_id: int, *, db: Session,
               computed: dict | None = None, schema_version: int | None = None,
               status: str = 'pending') -> WorkoutInsight:
        """Создать строку или обновить computed существующей (идемпотентно по session_id).

        Статус существующей строки НЕ понижается: done/running не откатываются в pending
        повторным синком. (Idempotent by session_id; never demotes an existing status.)
        """
        row = db.query(WorkoutInsight).filter(
            WorkoutInsight.session_id == session_id).first()
        if row is None:
            row = WorkoutInsight(user_id=user_id, session_id=session_id,
                                 status=status, computed_json=computed,
                                 schema_version=schema_version)
            db.add(row)
            try:
                db.commit()
            except IntegrityError:
                # Гонка двух синков (app+bot): строку успел вставить сосед —
                # перечитываем его версию (concurrent insert lost the race).
                db.rollback()
                row = db.query(WorkoutInsight).filter(
                    WorkoutInsight.session_id == session_id).first()
            return row
        if computed is not None:
            row.computed_json = computed
            row.schema_version = schema_version
        db.commit()
        return row

    @staticmethod
    def claim(session_id: int, *, db: Session) -> bool:
        """Атомарный захват pending→running; True — разбор наш (atomic claim)."""
        updated = db.query(WorkoutInsight).filter(
            WorkoutInsight.session_id == session_id,
            WorkoutInsight.status == 'pending',
        ).update({"status": "running", "claimed_at": _utcnow(),
                  "attempts": WorkoutInsight.attempts + 1},
                 synchronize_session=False)
        db.commit()
        return updated == 1

    @staticmethod
    def release(session_id: int, *, db: Session) -> None:
        """Вернуть running-строку в очередь после сбоя; исчерпаны попытки → error."""
        row = db.query(WorkoutInsight).filter(
            WorkoutInsight.session_id == session_id,
            WorkoutInsight.status == 'running',
        ).first()
        if row is None:
            return
        row.status = 'pending' if row.attempts < REVIEW_MAX_ATTEMPTS else 'error'
        db.commit()

    @staticmethod
    def reclaim_stale_running(older_than_min: int, *, db: Session) -> int:
        """Зависшие running (креш между claim и finish) → обратно в очередь/error."""
        cutoff = _utcnow() - timedelta(minutes=older_than_min)
        rows = db.query(WorkoutInsight).filter(
            WorkoutInsight.status == 'running',
            WorkoutInsight.claimed_at < cutoff,
        ).all()
        for row in rows:
            row.status = 'pending' if row.attempts < REVIEW_MAX_ATTEMPTS else 'error'
        db.commit()
        return len(rows)

    @staticmethod
    def finish(session_id: int, *, db: Session, source: str,
               assessment: dict | None = None, effort_match: str | None = None,
               carry_forward: str | None = None,
               coach_message_id: int | None = None) -> None:
        """Зафиксировать итог разбора (persist the review outcome)."""
        row = db.query(WorkoutInsight).filter(
            WorkoutInsight.session_id == session_id).first()
        if row is None:
            return  # старые сессии без insight-строки — молча пропускаем
        row.status = 'done'
        row.source = source
        row.reviewed_at = _utcnow()
        row.assessment_json = assessment
        row.effort_match = effort_match
        row.carry_forward = carry_forward
        row.coach_message_id = coach_message_id
        db.commit()

    @staticmethod
    def pending_older_than(minutes: int, *, db: Session,
                           limit: int = 5) -> list[WorkoutInsight]:
        """Pending, ждущие дольше таймаута — кандидаты периодической джобы."""
        cutoff = _utcnow() - timedelta(minutes=minutes)
        return db.query(WorkoutInsight).filter(
            WorkoutInsight.status == 'pending',
            WorkoutInsight.created_at < cutoff,
        ).order_by(WorkoutInsight.created_at).limit(limit).all()

    @staticmethod
    def expire_older_than(hours: int, *, db: Session) -> int:
        """Протухшие pending → expired (тишина; computed_json остаётся для отчётов)."""
        cutoff = _utcnow() - timedelta(hours=hours)
        updated = db.query(WorkoutInsight).filter(
            WorkoutInsight.status == 'pending',
            WorkoutInsight.created_at < cutoff,
        ).update({"status": "expired"}, synchronize_session=False)
        db.commit()
        return updated

    @staticmethod
    def recent(user_id: int, *, db: Session, days: int = 7,
               limit: int = 3) -> list[WorkoutInsight]:
        """Свежие завершённые итоги — для утреннего вердикта/weekly (новые первыми)."""
        cutoff = _utcnow() - timedelta(days=days)
        return db.query(WorkoutInsight).filter(
            WorkoutInsight.user_id == user_id,
            WorkoutInsight.status == 'done',
            WorkoutInsight.created_at >= cutoff,
        ).order_by(WorkoutInsight.created_at.desc()).limit(limit).all()

    @staticmethod
    def for_session(user_id: int, session_id: int, *, db: Session) -> WorkoutInsight | None:
        """Строка конкретной сессии (ownership-фильтр по user_id)."""
        return db.query(WorkoutInsight).filter(
            WorkoutInsight.user_id == user_id,
            WorkoutInsight.session_id == session_id,
        ).first()
