# NullLLM — дефолт без ключа (keyless default) — DEV_PLAN §1.7

from __future__ import annotations

from src.coach.llm.client import LLMResponse
from src.coach.llm.config import COACH_MAX_TOKENS
from src.exceptions import LLMUnavailableError


class NullLLM:
    """Всегда бросает LLMUnavailableError → оркестратор уходит в fallback."""

    def complete(self, *, system: list[dict], messages: list[dict],
                 tools: list[dict] | None = None,
                 output_schema: dict | None = None,
                 effort: str = "low",
                 max_tokens: int = COACH_MAX_TOKENS) -> LLMResponse:
        raise LLMUnavailableError(
            "ANTHROPIC_API_KEY не задан — коуч в детерминированном режиме")
