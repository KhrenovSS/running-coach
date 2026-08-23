# Фейки LLM для тестов (LLM fakes) — DEV_PLAN §10. Ни один тест не ходит в сеть.

from __future__ import annotations

from src.coach.llm.client import LLMResponse
from src.exceptions import LLMUnavailableError


class ScriptedLLM:
    """Отдаёт заранее записанные ответы; пишет kwargs каждого вызова в .calls."""

    def __init__(self, responses: list[LLMResponse]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def complete(self, **kwargs) -> LLMResponse:
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("ScriptedLLM: ответы закончились (script exhausted)")
        return self._responses.pop(0)


class FailingLLM:
    """Всегда LLMUnavailableError — проверка fallback-пути."""

    calls: list = []

    def __init__(self):
        self.calls = []

    def complete(self, **kwargs) -> LLMResponse:
        self.calls.append(kwargs)
        raise LLMUnavailableError("scripted failure")
