# Тесты слоя tools (Tool layer tests) — DEV_PLAN §10
import json
from datetime import UTC

import pytest

from src.coach.tools.registry import TOOLS, anthropic_tools, run_tool
from src.domain.models.base import utcnow
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


def test_session_brief_has_days_ago(athlete_with_history, db_session):
    """Инцидент 23.08: LLM назвал сегодняшнюю тренировку «вчерашней».

    days_ago (0 = сегодня) и started_at_local — единственные источники
    относительных дат и времени суток для модели.
    """
    from zoneinfo import ZoneInfo

    from src.models import TrainingSession
    result = run_tool("get_recent_workouts", {"limit": 5},
                      user_id=athlete_with_history.id, db=db_session)
    newest = result["workouts"][0]
    assert newest["days_ago"] == 0

    # Эталон — zoneinfo напрямую, не через наш хелпер (анти-дрейф)
    s = db_session.query(TrainingSession).filter_by(
        id=newest["session_id"]).one()
    begin_utc = s.begin_ts if s.begin_ts.tzinfo else s.begin_ts.replace(tzinfo=UTC)
    expected = begin_utc.astimezone(ZoneInfo("Europe/Moscow"))
    assert newest["started_at_local"] == expected.strftime("%Y-%m-%d %H:%M")
    assert newest["tz"] == "Europe/Moscow"
    assert newest["date"] == expected.date().isoformat()
    from src.utils.timeutils import WEEKDAYS_RU
    assert newest["weekday"] == WEEKDAYS_RU[expected.weekday()]

    from src.coach.state import assess_state
    state = assess_state(athlete_with_history.id, db=db_session)
    assert state.last_workout["days_ago"] == 0
    assert state.last_workout["started_at_local"] == expected.strftime("%Y-%m-%d %H:%M")
    assert state.last_workout["tz"] == "Europe/Moscow"
    assert state.last_workout["weekday"] == WEEKDAYS_RU[expected.weekday()]


def test_session_brief_evening_workout_stays_evening(db_session):
    """Инцидент 28.08: LLM назвал вечернюю тренировку «утренней».

    Вечер UTC (16:05) в поясе тренировки Moscow → started_at_local 19:05;
    кросс-полуночь (22:00 UTC) → локальная дата = UTC-дата + 1, days_ago
    считается от локальной пары дат.
    """
    from zoneinfo import ZoneInfo

    from tests.helpers import build_training_session
    user = _unique_user(db_session)

    evening = utcnow().replace(hour=16, minute=5, second=0, microsecond=0)
    s1 = build_training_session(db_session, user.id, begin_ts=evening,
                                timezone="Europe/Moscow")
    late = utcnow().replace(hour=22, minute=0, second=0, microsecond=0)
    s2 = build_training_session(db_session, user.id, begin_ts=late,
                                timezone="Europe/Moscow")

    result = run_tool("get_recent_workouts", {"limit": 5},
                      user_id=user.id, db=db_session)
    briefs = {w["session_id"]: w for w in result["workouts"]}

    assert briefs[s1.id]["started_at_local"].endswith("19:05")
    assert briefs[s1.id]["tz"] == "Europe/Moscow"

    # 22:00 UTC = 01:00 MSK следующего дня (crosses midnight in local zone)
    local_late = late.replace(tzinfo=UTC).astimezone(ZoneInfo("Europe/Moscow"))
    b2 = briefs[s2.id]
    assert b2["date"] == local_late.date().isoformat()
    assert b2["started_at_local"] == local_late.strftime("%Y-%m-%d %H:%M")
    now_local = utcnow().replace(tzinfo=UTC).astimezone(ZoneInfo("Europe/Moscow"))
    assert b2["days_ago"] == (now_local.date() - local_late.date()).days


def test_workout_detail_morning_metrics_by_local_date(db_session):
    """Регрессия #265: вечерняя тренировка 22:00 UTC (01:00 MSK следующего дня) →
    daily_metrics_morning берётся по ЛОКАЛЬНОЙ дате, не по UTC."""
    from zoneinfo import ZoneInfo

    from tests.helpers import build_daily_metrics, build_training_session

    user = _unique_user(db_session)
    late = utcnow().replace(hour=22, minute=0, second=0, microsecond=0)
    local_date = late.replace(tzinfo=UTC).astimezone(
        ZoneInfo("Europe/Moscow")).date()
    assert local_date != late.date()                     # кросс-полуночный кейс
    s = build_training_session(db_session, user.id, begin_ts=late,
                               timezone="Europe/Moscow")
    build_daily_metrics(db_session, user.id, metric_date=late.date(), rhr=44)
    build_daily_metrics(db_session, user.id, metric_date=local_date, rhr=55)

    detail = run_tool("get_workout_detail", {"session_id": s.id},
                      user_id=user.id, db=db_session)
    assert detail["daily_metrics_morning"]["rhr"] == 55  # локальный день, не UTC
