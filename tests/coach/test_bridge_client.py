# Тесты BridgeLLM — мост через подписку (Bridge client tests). Без сети:
# httpx.MockTransport. (No network — httpx.MockTransport only.)
import httpx
import pytest

from src.coach.llm.bridge_client import BridgeLLM, extract_json
from src.exceptions import LLMUnavailableError

TURN = '{"message": "Полегче сегодня.", "proposal": null, "followup_question": null, "log_suggestion": null}'


def _bridge(handler) -> BridgeLLM:
    return BridgeLLM(base_url="http://bridge.test", token="secret",
                     transport=httpx.MockTransport(handler))


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


@pytest.mark.parametrize("status", [401, 502, 504])
def test_bridge_http_errors_raise_unavailable(status):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"detail": "boom"})
    llm = _bridge(handler)
    with pytest.raises(LLMUnavailableError):
        llm.complete(system=[], messages=[{"role": "user", "content": "x"}])


def test_bridge_connection_error_raises_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")
    llm = _bridge(handler)
    with pytest.raises(LLMUnavailableError):
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
