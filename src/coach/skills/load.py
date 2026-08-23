# Скилл нагрузки: ACWR + ATI/CTI (Load skill)
# ACWR — честный (BACKLOG #219): дни отдыха = 0, мало данных → ratio=None.

from __future__ import annotations

from sqlalchemy.orm import Session

from src.coach.config import INJURY_RISK_THRESHOLDS, LOAD_RATIO_HIGH
from src.coach.contracts import SkillResult
from src.coach.skills.base import unknown_result
from src.services.recovery_view import load_status_structured
from src.services.repositories_coach import CoachRepository


def evaluate(user_id: int, *, db: Session) -> SkillResult:
    """Нагрузка: ACWR (острая/хроническая) + анаэробный баланс ATI/CTI.

    (Load: acute:chronic workload ratio plus ATI/CTI anaerobic balance.)
    """
    acwr = CoachRepository.acwr(user_id, db=db)
    dm = CoachRepository.latest_metrics(user_id, db=db)
    ati_cti = load_status_structured(
        dm.training_load if dm else None,
        cti=dm.cti if dm else None,
        ati=dm.ati if dm else None,
    )

    ratio = acwr["ratio"]
    if ratio is None and ati_cti["value"] is None:
        return unknown_result("load", f"insufficient load data ({acwr['days_with_data']} days)")

    if ratio is not None and ratio > INJURY_RISK_THRESHOLDS["load_ratio_high"]:
        status = "danger"
    elif (ratio is not None and ratio > LOAD_RATIO_HIGH) or ati_cti["status"] == "high_anaerobic":
        status = "warning"
    elif ratio is not None:
        status = "ok"
    else:
        status = "unknown"  # только ATI/CTI без ACWR — целостной картины нет

    confidence = 0.8 if ratio is not None else 0.3
    return SkillResult(
        key="load",
        status=status,
        value=ratio,
        confidence=confidence,
        message=f"acwr={ratio}; ati_cti={ati_cti['status']}",
        evidence=(f"acute={acwr['acute_load']}, chronic={acwr['chronic_load']}, "
                  f"ratio={ratio}, days={acwr['days_with_data']}; {ati_cti['evidence']}"),
        unit="ratio",
        as_of=dm.date if dm else None,
    )
