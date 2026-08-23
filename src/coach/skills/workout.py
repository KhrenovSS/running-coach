# Скилл разбора тренировки (Workout review skill) — per-session, не state-скилл.
# Сводит факты одной сессии; глубокий разбор — задача LLM через get_workout_detail.

from __future__ import annotations

from sqlalchemy.orm import Session

from src.coach.contracts import SkillResult
from src.coach.skills.base import unknown_result
from src.coach.util import effective_training_type
from src.services.repositories_coach import CoachRepository


def evaluate_session(user_id: int, session_id: int, *, db: Session) -> SkillResult:
    """Факты завершённой тренировки: тип, объём, темп, пульс, TE, RPE.

    (Facts of a completed session: type, volume, pace, HR, training effect, RPE.)
    """
    session, fb = CoachRepository.session_with_feedback(user_id, session_id, db=db)
    if session is None:
        return unknown_result("workout", f"session {session_id} not found")

    ttype = effective_training_type(session)
    rpe = fb.rating if fb else None
    parts = [
        f"type={ttype}",
        f"km={session.total_distance_km}",
        f"pace={session.avg_pace}",
        f"avg_hr={session.avg_heart_rate}",
        f"te={session.training_effect}",
        f"rpe={rpe}",
    ]
    suspect = bool(session.suspect_flags)
    return SkillResult(
        key="workout",
        status="warning" if suspect else "ok",
        value=session.training_effect,
        confidence=0.5 if suspect else 0.9,
        message="; ".join(parts),
        evidence=(f"session_id={session.id}; duration_min={session.duration_minutes}; "
                  f"anaerobic_te={session.anaerobic_training_effect}; "
                  f"suspect_flags={session.suspect_flags or []}"),
        unit="TE",
        as_of=session.begin_ts.date() if session.begin_ts else None,
    )
