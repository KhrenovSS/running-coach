# Тесты слоя tools (Tool layer tests) — DEV_PLAN §10
import json

import pytest

from src.coach.tools.registry import TOOLS, anthropic_tools, run_tool
from src.exceptions import NotFoundError, ToolExecutionError
from tests.coach.conftest import _unique_user


def test_tool_names_unique_and_schemas_strict():
    names = [t.name for t in TOOLS]
    assert len(names) == len(set(names))
    for t in TOOLS:
        assert t.input_schema["additionalProperties"] is False
        assert "required" in t.input_schema
    for d in anthropic_tools():
        assert d["strict"] is True
        json.dumps(d, sort_keys=True)  # сериализуемость определений


def test_every_tool_json_serializable(athlete_with_history, db_session):
    """Каждый tool на фикстуре с историей → json.dumps без ошибок."""
    from src.models import TrainingSession
    session = db_session.query(TrainingSession).filter_by(
        user_id=athlete_with_history.id).first()
    args_by_tool = {
        "get_athlete_state": {},
        "get_safety_verdict": {},
        "get_recent_workouts": {"limit": 3},
        "get_workout_detail": {"session_id": session.id},
        "get_metrics_series": {"metric": "hrv", "days": 14},
        "get_weekly_summary": {"weeks": 4},
        "search_guides": {"query": "боль колено"},
    }
    assert set(args_by_tool) == {t.name for t in TOOLS}
    for name, args in args_by_tool.items():
        result = run_tool(name, args, user_id=athlete_with_history.id, db=db_session)
        json.dumps(result)  # не должен упасть


def test_athlete_state_tool_has_all_skills(athlete_with_history, db_session):
    from src.coach.skills.base import SKILL_KEYS
    result = run_tool("get_athlete_state", {}, user_id=athlete_with_history.id,
                      db=db_session)
    assert set(result["skills"]) == set(SKILL_KEYS)
    assert "missing" in result
    assert "signals" not in result  # внутреннее сырьё safety не отдаётся LLM


def test_workout_detail_ownership(athlete_with_history, db_session):
    """Чужая сессия → NotFoundError (ownership check)."""
    from src.models import TrainingSession
    session = db_session.query(TrainingSession).filter_by(
        user_id=athlete_with_history.id).first()
    stranger = _unique_user(db_session)
    with pytest.raises(NotFoundError):
        run_tool("get_workout_detail", {"session_id": session.id},
                 user_id=stranger.id, db=db_session)


def test_unknown_tool_and_bad_args(empty_user, db_session):
    with pytest.raises(ToolExecutionError):
        run_tool("drop_database", {}, user_id=empty_user.id, db=db_session)
    with pytest.raises(ToolExecutionError):
        run_tool("get_metrics_series", {"metric": "no_such_metric"},
                 user_id=empty_user.id, db=db_session)


def test_search_guides_finds_knee(empty_user, db_session):
    result = run_tool("search_guides", {"query": "боль в колене"},
                      user_id=empty_user.id, db=db_session)
    assert result["chunks"]
    assert any("колено" in c["guide"] or "knee" in c["guide"] for c in result["chunks"])


def test_key_rules_digest_stable():
    """Дайджест key_rules стабилен между вызовами (prompt-cache prerequisite)."""
    from src.coach.knowledge.loader import key_rules_digest
    a, b = key_rules_digest(), key_rules_digest()
    assert a == b and "weekly_volume_increase_max_pct" in a
