# Детерминированный fallback без LLM (Deterministic no-LLM fallback) — DEV_PLAN §1.7
#
# Продукт работает без API-ключа: предложение строится таблицей из состояния,
# затем проходит тот же clamp, что и предложения LLM.
# (The product works without a key; fallback proposals pass the same clamp.)

from __future__ import annotations

from src.coach.config import RECOVERY_PCT_MODERATE, RECOVERY_PCT_READY
from src.coach.contracts import AthleteState, WorkoutProposal


def fallback_proposal(state: AthleteState) -> WorkoutProposal:
    """Консервативное табличное предложение из readiness (conservative table proposal).

    Числа не претендуют на ум LLM — это безопасный минимум: лёгкий бег при
    готовности, восстановительный при средней, отдых при низкой/неизвестной.
    """
    readiness = state.readiness_score
    if readiness is None:
        return WorkoutProposal(
            workout_type="recovery", target_zone=1, duration_min=30,
            rationale=["нет данных о готовности — только восстановительный"],
        )
    if readiness >= RECOVERY_PCT_READY:
        return WorkoutProposal(
            workout_type="easy", target_zone=2, duration_min=45,
            rationale=[f"готовность {readiness:.0f}/100 — обычный лёгкий бег"],
        )
    if readiness >= RECOVERY_PCT_MODERATE:
        return WorkoutProposal(
            workout_type="recovery", target_zone=1, duration_min=30,
            rationale=[f"готовность {readiness:.0f}/100 — восстановительный"],
        )
    return WorkoutProposal(
        workout_type="rest", target_zone=1,
        rationale=[f"готовность {readiness:.0f}/100 — отдых"],
    )
