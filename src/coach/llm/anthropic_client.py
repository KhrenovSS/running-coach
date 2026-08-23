# Anthropic-клиент (Anthropic client) — DEV_PLAN §8
#
# Вся специфика API живёт здесь. Факты актуального API (не тренировочный приор):
# thinking={"type":"adaptive"} (budget_tokens удалён → 400); глубина —
# output_config.effort; структурированный выход — output_config.format
# (не устаревший output_format); assistant prefill удалён; temperature удалена.

from __future__ import annotations

import json

from src.coach.llm.client import LLMResponse, ToolCall
from src.coach.llm.config import (
    COACH_MAX_TOKENS,
    PRICE_CACHE_READ_PER_M,
    PRICE_CACHE_WRITE_PER_M,
    PRICE_INPUT_PER_M,
    PRICE_OUTPUT_PER_M,
)
from src.exceptions import LLMUnavailableError
from src.utils.logger import get_logger

logger = get_logger("coach.llm")


def estimate_cost_usd(usage: dict) -> float:
    """Стоимость хода по usage (turn cost from usage counters)."""
    return round(
        (usage.get("input_tokens", 0) * PRICE_INPUT_PER_M
         + usage.get("output_tokens", 0) * PRICE_OUTPUT_PER_M
         + usage.get("cache_read_input_tokens", 0) * PRICE_CACHE_READ_PER_M
         + usage.get("cache_creation_input_tokens", 0) * PRICE_CACHE_WRITE_PER_M)
        / 1_000_000, 6)


class AnthropicLLM:
    """Клиент Anthropic API; ленивый импорт SDK (lazy SDK import)."""

    def __init__(self):
        try:
            import anthropic
        except ImportError as e:  # SDK не установлен — эквивалент отсутствия ключа
            raise LLMUnavailableError(f"anthropic SDK не установлен: {e}") from e
        from src.config import settings
        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._model = settings.coach_llm_model

    def complete(self, *, system: list[dict], messages: list[dict],
                 tools: list[dict] | None = None,
                 output_schema: dict | None = None,
                 effort: str = "low",
                 max_tokens: int = COACH_MAX_TOKENS) -> LLMResponse:
        anthropic = self._anthropic
        output_config: dict = {"effort": effort}
        if output_schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": output_schema}
        kwargs: dict = {
            "model": self._model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
            "thinking": {"type": "adaptive"},
            "output_config": output_config,
        }
        if tools:
            kwargs["tools"] = tools
        try:
            resp = self._client.messages.create(**kwargs)
        # Цепочка от частного к общему (specific-first chain; no bare except)
        except anthropic.AuthenticationError as e:
            raise LLMUnavailableError(f"неверный API-ключ: {e}") from e
        except anthropic.RateLimitError as e:
            raise LLMUnavailableError(f"rate limit: {e}") from e
        except anthropic.APIStatusError as e:
            raise LLMUnavailableError(f"API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LLMUnavailableError(f"нет соединения с API: {e}") from e

        text = ""
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            if block.type == "text":
                text += block.text
            elif block.type == "tool_use":
                # Вход tool'а всегда через объект, не через строковый матчинг
                args = block.input if isinstance(block.input, dict) else json.loads(block.input)
                tool_calls.append(ToolCall(id=block.id, name=block.name, args=args))

        parsed = None
        if output_schema is not None and resp.stop_reason == "end_turn" and text:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                logger.warning("Structured output не распарсился (len=%d)", len(text))

        usage = {
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
            "cache_read_input_tokens": getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
            "cache_creation_input_tokens": getattr(resp.usage, "cache_creation_input_tokens", 0) or 0,
        }
        return LLMResponse(text=text, tool_calls=tool_calls,
                           stop_reason=resp.stop_reason, parsed=parsed,
                           raw_content=resp.content, usage=usage)
