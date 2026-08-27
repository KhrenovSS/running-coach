# Тесты ручного tool-loop (Manual agent loop tests) — DEV_PLAN §10
import json

import pytest

from src.coach.llm.agent import run_turn
from src.coach.llm.client import LLMResponse, ToolCall
from src.coach.llm.config import COACH_MAX_TOOL_ITERATIONS
from src.exceptions import CoachError
from tests.coach.fakes import ScriptedLLM

TURN_JSON = {"message": "Сегодня лучше полегче.", "proposal": None,
             "followup_question": None, "log_suggestion": None}


def _tool_use_resp(name: str, args: dict, call_id: str = "tc_1") -> LLMResponse:
    return LLMResponse(stop_reason="tool_use",
                       tool_calls=[ToolCall(id=call_id, name=name, args=args)],
                       raw_content=[{"type": "tool_use", "id": call_id,
                                     "name": name, "input": args}])


def test_agent_tool_roundtrip(athlete_with_history, db_session):
    """tool_use → выполнен реальный tool → tool_result с тем же id → финальный JSON."""
    llm = ScriptedLLM([
        _tool_use_resp("get_athlete_state", {}),
        LLMResponse(stop_reason="end_turn", parsed=TURN_JSON),
    ])
    turn, usage = run_turn(llm, user_id=athlete_with_history.id, db=db_session,
                           system=[], messages=[{"role": "user", "content": "привет"}])
    assert turn.message == "Сегодня лучше полегче."
    assert usage["tool_calls"] == ["get_athlete_state"]
    # Второй запрос содержит tool_result с тем же tool_use_id
    second = llm.calls[1]["messages"]
    results = second[-1]["content"]
    assert results[0]["type"] == "tool_result" and results[0]["tool_use_id"] == "tc_1"
    payload = json.loads(results[0]["content"])
    assert "skills" in payload


def test_agent_tool_error_is_data_not_crash(empty_user, db_session):
    """Ошибка tool'а → is_error tool_result, ход продолжается (tool error is data)."""
    llm = ScriptedLLM([
        _tool_use_resp("get_workout_detail", {"session_id": 999999}),
        LLMResponse(stop_reason="end_turn", parsed=TURN_JSON),
    ])
    turn, _ = run_turn(llm, user_id=empty_user.id, db=db_session,
                       system=[], messages=[{"role": "user", "content": "?"}])
    assert turn.message
    results = llm.calls[1]["messages"][-1]["content"]
    assert results[0].get("is_error") is True


def test_agent_iteration_cap(empty_user, db_session):
    """Бесконечные tool_use → CoachError после лимита, не вечный цикл."""
    llm = ScriptedLLM([_tool_use_resp("get_athlete_state", {}, f"tc_{i}")
                       for i in range(COACH_MAX_TOOL_ITERATIONS + 2)])
    with pytest.raises(CoachError, match="лимит"):
        run_turn(llm, user_id=empty_user.id, db=db_session,
                 system=[], messages=[{"role": "user", "content": "?"}])


def test_agent_invalid_json_raises_coach_error(empty_user, db_session):
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", text="это не json")])
    with pytest.raises(CoachError, match="JSON"):
        run_turn(llm, user_id=empty_user.id, db=db_session,
                 system=[], messages=[{"role": "user", "content": "?"}])


def test_agent_schema_violation_raises(empty_user, db_session):
    """JSON есть, но не CoachTurn (например, зона 9) → CoachError, не тихий проглот."""
    bad = {"message": "ок", "proposal": {"workout_type": "interval", "target_zone": 9}}
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=bad)])
    with pytest.raises(CoachError, match="валидац"):
        run_turn(llm, user_id=empty_user.id, db=db_session,
                 system=[], messages=[{"role": "user", "content": "?"}])


def test_rest_proposal_with_zero_volumes_validates():
    """Инцидент 23.08: sonnet заполнил нули для rest → схема отвергала → fallback.

    0 → None (нет объёма); CoachTurn валидируется.
    """
    from src.coach.llm.schemas import CoachTurn

    turn = CoachTurn.model_validate({
        "message": "Сегодня отдых.",
        "proposal": {"workout_type": "rest", "target_zone": 1,
                     "duration_min": 0, "distance_km": 0,
                     "structure": None, "rationale": []},
        "followup_question": None, "log_suggestion": None,
    })
    assert turn.proposal.duration_min is None
    assert turn.proposal.distance_km is None

    # null-зона для rest (второй live-случай 23.08) → Z1
    turn2 = CoachTurn.model_validate({
        "message": "Отдых.", "proposal": {"workout_type": "rest", "target_zone": None},
        "followup_question": None, "log_suggestion": None,
    })
    assert turn2.proposal.target_zone == 1


def test_target_pace_validation():
    """target_pace_min_km: 0 → None (нет темпа), вне границ → ValidationError."""
    import pytest
    from pydantic import ValidationError

    from src.coach.llm.schemas import WorkoutProposalIn

    p = WorkoutProposalIn.model_validate(
        {"workout_type": "easy", "target_zone": 2, "target_pace_min_km": 0})
    assert p.target_pace_min_km is None
    ok = WorkoutProposalIn.model_validate(
        {"workout_type": "tempo", "target_zone": 4, "target_pace_min_km": 5.5})
    assert ok.target_pace_min_km == 5.5
    for bad in (1.0, 20.0):
        with pytest.raises(ValidationError):
            WorkoutProposalIn.model_validate(
                {"workout_type": "tempo", "target_zone": 4, "target_pace_min_km": bad})
