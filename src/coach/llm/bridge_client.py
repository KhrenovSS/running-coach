# BridgeLLM — LLM через мост подписки (Subscription-bridge LLM client) — план 23.08
#
# Реализация CoachLLM поверх host-моста (bin/coach_llm_bridge.py). Ограничение
# режима: tool-цикл неактивен (headless Claude Code не отдаёт невыполненный
# tool_use) — параметр tools игнорируется; контекст обогащён оркестратором.
# JSON обеспечивается контрактом промпта + pydantic-валидацией в agent.run_turn.
# (CoachLLM over the host bridge; tools are ignored — the loop is inactive.)

from __future__ import annotations

import json
import re

import httpx

from src.coach.llm.client import LLMResponse
from src.coach.llm.config import COACH_MAX_TOKENS
from src.exceptions import LLMUnavailableError

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def extract_json(text: str) -> dict | None:
    """Достать первый JSON-объект: чистый / в фенсах / с преамбулой (robust extract)."""
    if not text:
        return None
    candidates = [text.strip()]
    m = _FENCE.search(text)
    if m:
        candidates.insert(0, m.group(1))
    brace = text.find("{")
    if brace > 0:
        candidates.append(text[brace:])
    for cand in candidates:
        try:
            obj = json.loads(cand)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return None


class BridgeLLM:
    """CoachLLM через host-мост (CoachLLM over the host-side bridge)."""

    def __init__(self, base_url: str | None = None, token: str | None = None,
                 transport: httpx.BaseTransport | None = None):
        from src.config import settings
        self._base_url = (base_url or settings.coach_llm_bridge_url).rstrip("/")
        self._token = token if token is not None else settings.coach_llm_bridge_token
        # transport — для тестов (httpx.MockTransport), сеть в тестах запрещена
        self._client = httpx.Client(timeout=150, transport=transport)

    def complete(self, *, system: list[dict], messages: list[dict],
                 tools: list[dict] | None = None,
                 output_schema: dict | None = None,
                 effort: str = "low",
                 max_tokens: int = COACH_MAX_TOKENS) -> LLMResponse:
        system_text = "\n\n".join(b.get("text", "") for b in system)
        payload = {"system_text": system_text, "messages": messages,
                   "effort": effort, "max_tokens": max_tokens}
        try:
            resp = self._client.post(f"{self._base_url}/complete", json=payload,
                                     headers={"X-Bridge-Token": self._token})
        except httpx.TimeoutException as e:
            raise LLMUnavailableError(f"мост: таймаут ({e})") from e
        except httpx.HTTPError as e:
            raise LLMUnavailableError(f"мост недоступен: {e}") from e
        if resp.status_code != 200:
            raise LLMUnavailableError(
                f"мост: HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        text = data.get("text", "")
        return LLMResponse(
            text=text,
            stop_reason="end_turn",
            parsed=extract_json(text),
            usage={**data.get("usage", {}), "bridge_cost_usd": data.get("cost_usd")},
        )
