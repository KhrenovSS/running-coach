# Prescriber — единая точка сборки назначения (single assembly point) — DEV_PLAN §4
#
# finalize(): предложение (LLM или fallback) → evaluate_safety → clamp → Prescription
# (+ опциональная запись в recommendations). Другого пути к Prescription нет.
# (proposal → safety → clamp → prescription; there is no other path.)

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from src.coach.contracts import AthleteState, Prescription, WorkoutProposal
from src.coach.fallback import fallback_proposal
from src.coach.rules.p1_safety import evaluate_safety
from src.coach.safety import clamp
from src.models import Recommendation
from src.utils.logger import get_logger

logger = get_logger("coach.prescriber")


def finalize(proposal: WorkoutProposal | None, state: AthleteState, *,
             db: Session | None = None, persist: bool = False,
             source: str = "fallback", now: datetime | None = None) -> Prescription:
    """Собрать назначение: safety вычисляется здесь же, clamp безусловный.

    proposal=None → детерминированное табличное предложение (fallback).
    (Assemble prescription; safety is computed here, clamp is unconditional.)
    """
    verdict = evaluate_safety(state, now=now)
    if proposal is None:
        proposal = fallback_proposal(state)
        source = "fallback"
    prescription, clamped = clamp(proposal, verdict, state, now=now, source=source)
    if clamped:
        logger.info("Prescription clamped for user=%s: %s -> %s (%s)",
                    state.user_id, proposal.workout_type,
                    prescription.workout_type, ",".join(verdict.triggered))
    if persist and db is not None:
        _save(prescription, state, db=db)
    return prescription


def _save(p: Prescription, state: AthleteState, *, db: Session) -> Recommendation:
    """Записать назначение в recommendations (persist prescription).

    proposal_json — предложение ДО урезания, safety_json — вердикт: метрика
    дрейфа LLM (DEV_PLAN §1.6). (Pre-clamp proposal + verdict = drift metric.)
    """
    from src.coach.tools.serialize import jsonable

    rec = Recommendation(
        user_id=state.user_id,
        for_date=p.when,
        workout_type=p.workout_type,
        target_json=p.target,
        volume_json=p.volume,
        rationale_json=[{"rule": r.rule, "decision": r.decision, "reason": r.reason}
                        for r in p.rationale],
        predicted_json=p.predicted,
        confidence=p.confidence,
        status="proposed",
        proposal_json=jsonable(p.proposal) if p.proposal else None,
        safety_json=jsonable(p.safety),
        clamped=p.clamped,
        source=p.source,
    )
    db.add(rec)
    db.commit()
    return rec
