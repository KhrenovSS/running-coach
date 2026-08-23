# Скилл распределения интенсивности: баланс 80/20 (Distribution skill)
# Здесь считаются числа; вывод «что с этим делать» — за LLM (бывший P3, DEV_PLAN §2).

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.coach.config import DISTRIBUTION_80_20
from src.coach.contracts import SkillResult
from src.coach.skills.base import unknown_result
from src.services.repositories import TrainingRepository


def evaluate(user_id: int, *, db: Session) -> SkillResult:
    """Баланс лёгкого/тяжёлого времени за 28 дней против цели 80/20.

    easy = Z1+Z2, hard = Z3+ (по минутам из segments_json).
    (Easy/hard time share over 28 days vs the 80/20 target.)
    """
    zones = TrainingRepository.zone_distribution(user_id, days=28, db=db)
    total = sum(zones.values())
    if total <= 0:
        return unknown_result("distribution", "no zone data in 28 days")

    easy = zones["z1"] + zones["z2"]
    easy_share = round(easy / total, 2)
    target = DISTRIBUTION_80_20["easy_share_target"]
    tolerance = DISTRIBUTION_80_20["tolerance"]

    status = "ok" if easy_share >= target - tolerance else "warning"
    return SkillResult(
        key="distribution",
        status=status,
        value=easy_share,
        confidence=0.8 if total >= 120 else 0.5,  # < 2 часов данных — картина шаткая
        message=f"easy_share={easy_share:.0%} (target {target:.0%}±{tolerance:.0%})",
        evidence=(f"minutes: z1={zones['z1']:.0f}, z2={zones['z2']:.0f}, z3={zones['z3']:.0f}, "
                  f"z4={zones['z4']:.0f}, z5={zones['z5']:.0f}; total={total:.0f}"),
        unit="share",
        as_of=datetime.now(timezone.utc).date(),
    )
