# Поток отложенного разбора (Deferred review flow) — DEV_PLAN §9 D5
#
# Синк (любой контейнер) только СОЗДАЁТ insight-строки; исполняет разбор только
# бот через атомарный claim (ADR «Решение 4» в docs/coach/ARCHITECTURE.md).
# Триггеры: тап боли (сразу), RPE-тап (+грейс), периодическая джоба (таймаут).
# (Sync creates rows; only the bot executes reviews via the atomic claim.)

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from src.coach import orchestrator
from src.coach.llm.client import CoachLLM
from src.models import WorkoutInsight
from src.services.repositories_insights import InsightRepository
from src.services.workout_insights import upsert_workout_insights
from src.utils.logger import get_logger

logger = get_logger("coach.review_flow")


def _ts(nt: dict) -> float:
    ts = nt.get("begin_ts")
    return ts.timestamp() if isinstance(ts, datetime) else float("-inf")


def ensure_insights_for_batch(user_id: int, trainings: list[dict], *,
                              db: Session, initiative: str) -> int | None:
    """Создать insight-строки батча; вернуть session_id, поставленный в pending.

    normal/high → самая свежая тренировка ждёт тапа/таймаута (pending), остальные
    'none'; low/off → все 'none' (upsert считает и физио-метрики D2).
    """
    if not trainings:
        return None
    latest_sid = max(trainings, key=_ts)["session_id"]
    pending_sid = latest_sid if initiative in ("normal", "high") else None
    for nt in sorted(trainings, key=_ts):
        sid = nt["session_id"]
        status = "pending" if sid == pending_sid else "none"
        try:
            upsert_workout_insights(user_id, sid, db=db, status=status)
        except Exception as e:  # метрики не должны блокировать конвейер разбора
            logger.error("Insight upsert failed for session=%s: %s", sid, e)
            InsightRepository.upsert(user_id, sid, db=db, status=status)
    return pending_sid


def run_pending_review(session_id: int, *, db: Session,
                       llm: CoachLLM | None = None) -> str | None:
    """Исполнить отложенный разбор: атомарный claim → разбор → done.

    None — claim не наш (дедуп конкурирующих триггеров), строки нет, или
    initiative на момент исполнения = off. Инициатива перечитывается: между
    синком и таймаутом пользователь мог её сменить.
    """
    row = db.query(WorkoutInsight).filter(
        WorkoutInsight.session_id == session_id).first()
    if row is None:
        return None
    user_id = row.user_id
    if not InsightRepository.claim(session_id, db=db):
        return None
    try:
        initiative = orchestrator.get_initiative(user_id, db=db)
        if initiative == "off":
            # выключил после синка → тишина, строку выводим из очереди
            db.query(WorkoutInsight).filter(
                WorkoutInsight.session_id == session_id,
            ).update({"status": "none"}, synchronize_session=False)
            db.commit()
            return None
        use_llm = initiative in ("normal", "high")
        # on_workout_completed сам уважает бюджет, падает в fallback и
        # закрывает строку через InsightRepository.finish (status=done).
        return orchestrator.on_workout_completed(
            user_id, session_id, db=db, llm=llm, use_llm=use_llm)
    except Exception as e:  # разбор не должен терять строку (release → retry)
        logger.error("Pending review failed for session=%s: %s",
                     session_id, e, exc_info=True)
        InsightRepository.release(session_id, db=db)
        return None


def due_review_sessions(older_than_min: int, *, db: Session,
                        limit: int = 5) -> list[tuple[int, int]]:
    """(user_id, session_id) pending-строк старше таймаута — для джобы бота."""
    rows = InsightRepository.pending_older_than(older_than_min, db=db, limit=limit)
    return [(r.user_id, r.session_id) for r in rows]
