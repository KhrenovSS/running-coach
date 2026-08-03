# Базовый контракт скилла (Skill base contract)
# Этап 0 — скелет модуля коуча (Coach module skeleton). Реализация — на последующих этапах.

from typing import Protocol

from src.coach.contracts import SkillResult


class Skill(Protocol):
    """Скилл — чистая функция над данными БД, возвращает SkillResult.
    (A skill is a pure function over DB data returning a SkillResult.)"""

    key: str

    def evaluate(self, user_id: int, db=None) -> SkillResult: ...
