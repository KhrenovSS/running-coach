# Базовый интерфейс правила (Rule base interface)
# Этап 0 — скелет модуля коуча (Coach module skeleton). Реализация — на последующих этапах.

from abc import ABC, abstractmethod

from src.coach.contracts import AthleteState, Prescription


class Rule(ABC):
    """Правило каскада P1–P5. Может ужесточать/дополнять Prescription, но НЕ ослаблять P1-safety.
    (Priority-cascade rule; must never relax P1 safety bounds.)"""

    priority: int = 0

    @abstractmethod
    def apply(self, state: AthleteState, draft: Prescription) -> Prescription: ...
