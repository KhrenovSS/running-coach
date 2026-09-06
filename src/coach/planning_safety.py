# Согласование потолков недели с вердиктом safety (week targets ⟂ safety verdict)
#
# Инцидент 06.09.2026: safety запретил интенсив на неделю (правила 16/17), а week_targets
# всё ещё давал hard_days_max=1 → LLM заложил темповую, clamp вырезал её молча, проза
# осталась про «качественную работу». Потолки должны видеть вердикт ДО вызова LLM.
# (Targets must reflect the verdict before the LLM plans, so prose matches the card.)

from __future__ import annotations

from typing import Any

from src.coach.config import HARD_TYPES
from src.coach.contracts import SafetyVerdict


def quality_blocked(verdict: SafetyVerdict) -> bool:
    """Вердикт не оставил ни одного качественного типа (no hard type is allowed)."""
    if not verdict.allow_training:
        return True
    if not verdict.allowed_types:            # пусто = все разрешены (empty = all allowed)
        return False
    return not (set(HARD_TYPES) & set(verdict.allowed_types))


def apply_safety_to_targets(targets: dict[str, Any], verdict: SafetyVerdict) -> dict[str, Any]:
    """Обнулить потолки качества недели, если safety закрыл интенсив; иначе — без изменений.

    Чистая функция: возвращает новый dict, ключ `quality_blocked_by_safety` — первая причина
    вердикта (текст для шапки карточки и промпта). (Pure: zero quality caps when hard types
    are forbidden; records the first safety reason.)
    """
    if not quality_blocked(verdict):
        return targets
    out = dict(targets)
    out["hard_days_max"] = 0
    if "remaining_hard_days_max" in out:
        out["remaining_hard_days_max"] = 0
    out["quality_z3_km_max"] = 0.0
    out["quality_z4_km_max"] = 0.0
    reason = next((r.reason for r in verdict.reasons if r.reason), None)
    out["quality_blocked_by_safety"] = reason or "интенсив закрыт границами безопасности"
    return out
