# Скилл усталости: HRV-статус + аномалия RHR + tired_rate (Fatigue skill)
# Источники порогов — src/coach/config.py через recovery_view (DEV_PLAN §3).

from __future__ import annotations

from sqlalchemy.orm import Session

from src.coach.contracts import SkillResult
from src.coach.skills.base import combined_confidence, unknown_result, worst_status
from src.services.recovery_view import (
    hrv_status_structured,
    rhr_anomaly,
    tired_rate_structured,
)
from src.services.repositories_coach import CoachRepository


def evaluate(user_id: int, *, db: Session) -> SkillResult:
    """Усталость по свежайшим метрикам: HRV, отклонение RHR от базы, tired_rate.

    (Fatigue from freshest metrics: HRV status, RHR anomaly vs baseline, tired_rate.)
    """
    dm = CoachRepository.latest_metrics(user_id, db=db)
    if dm is None:
        return unknown_result("fatigue", "no daily metrics")

    hrv = hrv_status_structured(dm.avg_sleep_hrv, dm.sleep_hrv_baseline,
                                dm.sleep_hrv_sd, dm.sleep_hrv_interval_list)
    rhr = rhr_anomaly(dm.rhr, CoachRepository.baseline_rhr(user_id, db=db))
    tired = tired_rate_structured(dm.tired_rate)

    status = worst_status(
        [hrv["status"], rhr["status"], tired["status"]],
        danger={"very_low", "critical_elevated"},
        warning={"low", "elevated", "high"},
    )
    parts = [
        f"hrv={hrv['status']}", f"rhr={rhr['status']}", f"tired={tired['status']}",
    ]
    return SkillResult(
        key="fatigue",
        status=status,
        value=dm.tired_rate,
        confidence=combined_confidence([hrv, rhr, tired]),
        message="; ".join(parts),
        evidence=f"{hrv['evidence']}; {rhr['evidence']}; {tired['evidence']}",
        unit="tired_rate",
        as_of=dm.date,
    )
