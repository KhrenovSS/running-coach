# Утилиты модуля коуча (Coach module utilities)

from __future__ import annotations


def effective_training_type(session) -> str | None:
    """Эффективный тип тренировки: ручной override приоритетнее автоклассификации.

    В остальном приложении override с training_type не слит (BACKLOG) — коуч обязан
    решать это сам. (Manual override takes precedence over auto-classified type.)
    """
    if session is None:
        return None
    return session.training_type_override or session.training_type


def safe_div(num: float | None, den: float | None) -> float | None:
    """Деление с None/нулём в знаменателе → None (division that never raises)."""
    if num is None or den is None or den == 0:
        return None
    return num / den


def clamp_value(value: float, lo: float, hi: float) -> float:
    """Ограничить значение диапазоном [lo, hi] (clamp value to range)."""
    return max(lo, min(hi, value))
