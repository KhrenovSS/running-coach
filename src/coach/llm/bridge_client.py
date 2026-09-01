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
import time
from collections.abc import Callable

import httpx

from src.coach.llm.client import LLMResponse
from src.coach.llm.config import (COACH_BRIDGE_RETRIES,
                                  COACH_BRIDGE_RETRY_BACKOFF_S, COACH_MAX_TOKENS)
from src.exceptions import LLMTransientError, LLMUnavailableError

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)

# Транзиентные HTTP-статусы моста (retryable): 502 — claude CLI exit!=0,
# 503 — сервис занят, 504 — таймаут CLI. 4xx/2xx решает вызывающий.
_TRANSIENT_STATUSES = (502, 503, 504)


def post_with_retry(post_fn: Callable[[], httpx.Response], *,
                    retries: int = COACH_BRIDGE_RETRIES,
                    backoff: float = COACH_BRIDGE_RETRY_BACKOFF_S,
                    sleep: Callable[[float], None] = time.sleep) -> httpx.Response:
    """POST с повтором на транзиентный сбой моста (timeout/сеть/5xx).

    Возвращает Response на 200 ИЛИ на не-транзиентный не-200 (4xx — решает
    вызывающий); исчерпав попытки на транзиентном сбое — бросает LLMTransientError.
    `sleep` инъектируется (в тестах — no-op, сеть/задержки запрещены).
    (POST with retry on transient bridge failures; permanent 4xx returned as-is.)
    """
    last: LLMTransientError | None = None
    for attempt in range(retries + 1):
        try:
            resp = post_fn()
        except httpx.TimeoutException as e:
            last = LLMTransientError(f"мост: таймаут ({e})")
        except httpx.HTTPError as e:   # TransportError и прочие сетевые
            last = LLMTransientError(f"мост недоступен: {e}")
        else:
            if resp.status_code not in _TRANSIENT_STATUSES:
                return resp            # 200 или постоянная 4xx — наружу
            last = LLMTransientError(
                f"мост: HTTP {resp.status_code}: {resp.text[:200]}")
        if attempt < retries:
            sleep(backoff * (attempt + 1))
    assert last is not None            # цикл всегда выставляет last перед выходом
    raise last


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
                 transport: httpx.BaseTransport | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        from src.config import settings
        self._base_url = (base_url or settings.coach_llm_bridge_url).rstrip("/")
        self._token = token if token is not None else settings.coach_llm_bridge_token
        # transport/sleep — для тестов (httpx.MockTransport + no-op sleep):
        # сеть и реальные задержки в тестах запрещены
        self._client = httpx.Client(timeout=150, transport=transport)
        self._sleep = sleep

    def complete(self, *, system: list[dict], messages: list[dict],
                 tools: list[dict] | None = None,
                 output_schema: dict | None = None,
                 effort: str = "low",
                 max_tokens: int = COACH_MAX_TOKENS) -> LLMResponse:
        system_text = "\n\n".join(b.get("text", "") for b in system)
        payload = {"system_text": system_text, "messages": messages,
                   "effort": effort, "max_tokens": max_tokens}
        # Транзиентные сбои (timeout/сеть/5xx) ретраятся внутри и, исчерпавшись,
        # бросают LLMTransientError; сюда возвращается только 200 или постоянная 4xx.
        resp = post_with_retry(
            lambda: self._client.post(f"{self._base_url}/complete", json=payload,
                                      headers={"X-Bridge-Token": self._token}),
            sleep=self._sleep)
        if resp.status_code != 200:   # постоянная ошибка (401 bad token и т.п.)
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
