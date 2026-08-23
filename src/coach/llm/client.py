# Интерфейс LLM (LLM interface) — DEV_PLAN §8
#
# Вся специфика провайдера заперта за Protocol: смена провайдера не трогает
# оркестратор/агента. Дефолт без ключа — NullLLM (детерминированный режим).
# (Provider specifics live behind the Protocol; NullLLM is the keyless default.)

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from src.coach.llm.config import COACH_MAX_TOKENS


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"
    parsed: dict | None = None                 # распарсенный structured output
    raw_content: Any = None                    # блоки ответа — эхо в следующий запрос
    usage: dict = field(default_factory=dict)


class CoachLLM(Protocol):
    """Контракт LLM-клиента (LLM client contract)."""

    def complete(self, *, system: list[dict], messages: list[dict],
                 tools: list[dict] | None = None,
                 output_schema: dict | None = None,
                 effort: str = "low",
                 max_tokens: int = COACH_MAX_TOKENS) -> LLMResponse: ...


def get_llm() -> CoachLLM:
    """Фабрика: AnthropicLLM при наличии ключа, иначе NullLLM (keyed → real, else null)."""
    from src.config import settings

    if settings.anthropic_api_key:
        from src.coach.llm.anthropic_client import AnthropicLLM
        return AnthropicLLM()
    from src.coach.llm.null import NullLLM
    return NullLLM()
