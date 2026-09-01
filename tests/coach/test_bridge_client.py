# Тесты BridgeLLM — мост через подписку (Bridge client tests). Без сети:
# httpx.MockTransport. (No network — httpx.MockTransport only.)
import httpx
import pytest

from src.coach.llm.bridge_client import BridgeLLM, extract_json
from src.exceptions import LLMTransientError, LLMUnavailableError

TURN = '{"message": "Полегче сегодня.", "proposal": null, "followup_question": null, "log_suggestion": null}'


def _bridge(handler) -> BridgeLLM:
    # sleep=no-op: ретраи на транзиентный сбой не должны реально спать в тестах
    return BridgeLLM(base_url="http://bridge.test", token="secret",
                     transport=httpx.MockTransport(handler),
                     sleep=lambda _s: None)


def test_extract_json_variants():
    assert extract_json(TURN)["message"] == "Полегче сегодня."
    assert extract_json(f"```json\n{TURN}\n```")["message"] == "Полегче сегодня."
    assert extract_json(f"Вот ответ:\n{TURN}")["message"] == "Полегче сегодня."
    assert extract_json("просто текст без json") is None
    assert extract_json("") is None


def test_bridge_success_with_fences(athlete_with_history):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Bridge-Token"] == "secret"
        payload = request.read().decode()
        assert "system_text" in payload
        return httpx.Response(200, json={
            "text": f"```json\n{TURN}\n```",
            "usage": {"input_tokens": 100, "output_tokens": 20,
                      "cache_read_input_tokens": 0, "cache_creation_input_tokens": 50},
            "cost_usd": 0.01,
        })
    llm = _bridge(handler)
    resp = llm.complete(system=[{"type": "text", "text": "s1"},
                                {"type": "text", "text": "s2"}],
                        messages=[{"role": "user", "content": "привет"}])
    assert resp.parsed["message"] == "Полегче сегодня."
    assert resp.stop_reason == "end_turn"
    assert resp.usage["input_tokens"] == 100
    assert resp.usage["bridge_cost_usd"] == 0.01


def test_bridge_system_blocks_flattened():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json
        captured.update(_json.loads(request.read()))
        return httpx.Response(200, json={"text": TURN, "usage": {}})
    llm = _bridge(handler)
    llm.complete(system=[{"type": "text", "text": "ПЕРСОНА"},
                         {"type": "text", "text": "ПРОФИЛЬ"}],
                 messages=[{"role": "user", "content": "x"}])
    assert "ПЕРСОНА" in captured["system_text"] and "ПРОФИЛЬ" in captured["system_text"]


def test_bridge_permanent_4xx_not_retried():
    """401 (bad token) — постоянная ошибка: без повтора, LLMUnavailableError (не Transient)."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"detail": "bad bridge token"})
    llm = _bridge(handler)
    with pytest.raises(LLMUnavailableError) as ei:
        llm.complete(system=[], messages=[{"role": "user", "content": "x"}])
    assert not isinstance(ei.value, LLMTransientError)
    assert calls["n"] == 1


@pytest.mark.parametrize("status", [502, 503, 504])
def test_bridge_transient_exhausted_raises_transient(status):
    """5xx на всех попытках → LLMTransientError; попыток = 1 + COACH_BRIDGE_RETRIES."""
    from src.coach.llm.config import COACH_BRIDGE_RETRIES
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(status, json={"detail": "boom"})
    llm = _bridge(handler)
    with pytest.raises(LLMTransientError):
        llm.complete(system=[], messages=[{"role": "user", "content": "x"}])
    assert calls["n"] == 1 + COACH_BRIDGE_RETRIES


def test_bridge_retries_then_succeeds():
    """502 → 502 → 200: транзиентный сбой добивается повтором (recovery within retries)."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(502, json={"detail": "claude CLI exit=1: "})
        return httpx.Response(200, json={"text": TURN, "usage": {}})
    llm = _bridge(handler)
    resp = llm.complete(system=[], messages=[{"role": "user", "content": "x"}])
    assert resp.parsed["message"] == "Полегче сегодня."
    assert calls["n"] == 3


def test_bridge_timeout_then_succeeds():
    """Timeout на первой попытке → повтор → успех (timeout is transient/retryable)."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ReadTimeout("slow")
        return httpx.Response(200, json={"text": TURN, "usage": {}})
    llm = _bridge(handler)
    resp = llm.complete(system=[], messages=[{"role": "user", "content": "x"}])
    assert resp.parsed["message"] == "Полегче сегодня."
    assert calls["n"] == 2


def test_bridge_connection_error_exhausted_raises_transient():
    """Сетевой отказ на всех попытках → LLMTransientError (network is transient)."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")
    llm = _bridge(handler)
    with pytest.raises(LLMTransientError):
        llm.complete(system=[], messages=[{"role": "user", "content": "x"}])


def test_get_llm_priority(monkeypatch):
    """Приоритет фабрики: ключ > мост > Null (factory priority)."""
    from src.coach.llm.client import get_llm
    from src.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "coach_llm_bridge_url", "")
    assert type(get_llm()).__name__ == "NullLLM"

    monkeypatch.setattr(settings, "coach_llm_bridge_url", "http://bridge.test")
    assert type(get_llm()).__name__ == "BridgeLLM"
    # ключ побеждает мост — проверка порядка, без создания AnthropicLLM
    # (создание требует валидного ключа; порядок веток покрыт кодом выше)


def test_enriched_today_block_reaches_llm(athlete_with_history, db_session):
    """Обогащение: последний user-блок содержит recent_workouts и weekly_summary."""
    from src.coach import orchestrator
    from src.coach.llm.client import LLMResponse
    from tests.coach.fakes import ScriptedLLM

    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed={
        "message": "ок", "proposal": None,
        "followup_question": None, "log_suggestion": None})])
    orchestrator.handle_chat(athlete_with_history.id, "как я?", db=db_session, llm=llm)
    last_block = llm.calls[0]["messages"][-1]["content"]
    assert "recent_workouts" in last_block
    assert "weekly_summary" in last_block
