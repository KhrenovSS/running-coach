# Скилл восстановления: Recovery % + часы до восстановления (Recovery skill)
# recovery_hours_left = recovery_hours_for(тип последней) − прошедшее время, ≥ 0.

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.coach.config import recovery_hours_for
from src.coach.contracts import SkillResult
from src.coach.skills.base import unknown_result
from src.coach.util import effective_training_type
from src.services.recovery_view import recovery_pct_structured
from src.services.repositories_coach import CoachRepository

_STATUS_MAP = {"recovered": "ok", "partial": "warning", "needs_rest": "danger"}


def hours_left(user_id: int, *, db: Session) -> float:
    """Часы до восстановления после последней тренировки, ≥ 0 (hours until recovered)."""
    sessions = CoachRepository.last_sessions(user_id, n=1, db=db)
    if not sessions or sessions[0].begin_ts is None:
        return 0.0
    last = sessions[0]
    need = recovery_hours_for(effective_training_type(last))
    begin = last.begin_ts
    if begin.tzinfo is None:  # SQLite отдаёт naive datetime (naive under SQLite)
        begin = begin.replace(tzinfo=timezone.utc)
    elapsed = (datetime.now(timezone.utc) - begin).total_seconds() / 3600
    return round(max(0.0, need - elapsed), 1)


def evaluate(user_id: int, *, db: Session) -> SkillResult:
    """Восстановление: recovery_pct с часов + расчётные часы до восстановления.

    (Recovery: watch-provided recovery_pct plus computed hours left until recovered.)
    """
    dm = CoachRepository.latest_metrics(user_id, db=db)
    left = hours_left(user_id, db=db)
    if dm is None:
        # Нет метрик, но часы до восстановления считаются от последней тренировки.
        if left > 0:
            return SkillResult(key="recovery", status="warning", value=left,
                               confidence=0.4, unit="h", as_of=None,
                               message=f"recovery_hours_left={left}",
                               evidence=f"no daily metrics; hours_left={left}")
        return unknown_result("recovery", "no daily metrics")

    pct = recovery_pct_structured(dm.recovery_pct)
    status = _STATUS_MAP.get(pct["status"], "unknown")
    if status in ("ok", "unknown") and left > 0:
        status = "warning"  # часы ещё не вышли → интенсив рано (hours not elapsed yet)
    return SkillResult(
        key="recovery",
        status=status,
        value=left,
        confidence=pct["confidence"] if pct["value"] is not None else 0.4,
        message=f"recovery_pct={pct['status']}; hours_left={left}",
        evidence=f"{pct['evidence']}; hours_left={left}",
        unit="h",
        as_of=dm.date,
    )
