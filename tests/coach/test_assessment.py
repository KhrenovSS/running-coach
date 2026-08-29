# Тесты D3: структурированная оценка разбора (ReviewAssessment)
# (D3 tests: structured review assessment) — DEV_PLAN §9 D-серия

import pytest
from pydantic import ValidationError

from src.coach import orchestrator
from src.coach.llm.client import LLMResponse
from src.coach.llm.schemas import CoachTurn, ReviewAssessment
from src.models import TrainingSession
from src.services.repositories_insights import InsightRepository
from tests.coach.fakes import ScriptedLLM

REVIEW_TURN_WITH_ASSESSMENT = {
    "message": "Тренировка легла тяжелее, чем должна была.",
    "proposal": None,
    "followup_question": "Как сон сегодня?",
    "log_suggestion": None,
    "assessment": {
        "effort_match": "harder",
        "causes": ["heat", "poor_sleep"],
        "flags": ["hr_drift_high"],
        "carry_forward": "завтра — только лёгкий бег, жара выбила",
    },
}


def _latest_session_id(user_id: int, db) -> int:
    s = db.query(TrainingSession).filter_by(user_id=user_id).order_by(
        TrainingSession.begin_ts.desc()).first()
    return s.id


def test_schema_validates_enums():
    """Enum-значения валидируются; неизвестная причина отклоняется."""
    a = ReviewAssessment.model_validate(REVIEW_TURN_WITH_ASSESSMENT["assessment"])
    assert a.effort_match == "harder"
    with pytest.raises(ValidationError):
        ReviewAssessment.model_validate({"effort_match": "ok", "causes": ["магнитные бури"]})


def test_old_turn_dicts_still_valid():
    """Обратная совместимость: turn-словари без assessment валидны (None)."""
    turn = CoachTurn.model_validate({"message": "привет", "proposal": None,
                                     "followup_question": None, "log_suggestion": None})
    assert turn.assessment is None


def test_review_persists_assessment_into_insight(athlete_with_history, db_session):
    """LLM-разбор с assessment → insight-строка done: колонки и JSON заполнены."""
    sid = _latest_session_id(athlete_with_history.id, db_session)
    InsightRepository.upsert(athlete_with_history.id, sid, db=db_session,
                             computed={"schema_version": 1})
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn",
                                   parsed=REVIEW_TURN_WITH_ASSESSMENT)])
    orchestrator.on_workout_completed(athlete_with_history.id, sid,
                                      db=db_session, llm=llm)
    row = InsightRepository.for_session(athlete_with_history.id, sid, db=db_session)
    assert row.status == "done"
    assert row.source == "llm"
    assert row.effort_match == "harder"
    assert row.carry_forward == "завтра — только лёгкий бег, жара выбила"
    assert row.assessment_json["causes"] == ["heat", "poor_sleep"]
    assert row.coach_message_id is not None


def test_deterministic_review_finishes_insight(athlete_with_history, db_session):
    """Детерминированный разбор тоже закрывает insight (source=fallback)."""
    sid = _latest_session_id(athlete_with_history.id, db_session)
    InsightRepository.upsert(athlete_with_history.id, sid, db=db_session)
    orchestrator.on_workout_completed(athlete_with_history.id, sid,
                                      db=db_session, llm=None, use_llm=False)
    row = InsightRepository.for_session(athlete_with_history.id, sid, db=db_session)
    assert row.status == "done"
    assert row.source == "fallback"
    assert row.assessment_json is None


def test_assessment_dropped_outside_review(athlete_with_history, db_session):
    """assessment в обычном чате игнорируется (WARNING, не сохраняется)."""
    turn = dict(REVIEW_TURN_WITH_ASSESSMENT)
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=turn)])
    reply = orchestrator.handle_chat(athlete_with_history.id, "как дела?",
                                     db=db_session, llm=llm)
    assert reply.source == "llm"
    assert reply.assessment is None


def test_flags_merged_from_computed_not_llm(athlete_with_history, db_session):
    """§6 METRICS_GUIDE: флаги assessment — детерминированные из computed.flags
    (с маппингом decoupling_high → hr_drift_high) + субъективные LLM; флаг,
    заявленный LLM без подтверждения в computed, отбрасывается."""
    from src.services.workout_insights import INSIGHTS_SCHEMA_VERSION

    sid = _latest_session_id(athlete_with_history.id, db_session)
    InsightRepository.upsert(
        athlete_with_history.id, sid, db=db_session,
        computed={"schema_version": INSIGHTS_SCHEMA_VERSION,
                  "flags": ["decoupling_high", "easy_run_too_hard", "heat"]},
        schema_version=INSIGHTS_SCHEMA_VERSION)
    turn = dict(REVIEW_TURN_WITH_ASSESSMENT)
    turn["assessment"] = dict(turn["assessment"],
                              flags=["great_session", "pace_hr_mismatch"])
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=turn)])
    orchestrator.on_workout_completed(athlete_with_history.id, sid,
                                      db=db_session, llm=llm)
    row = InsightRepository.for_session(athlete_with_history.id, sid, db=db_session)
    flags = row.assessment_json["flags"]
    # детерминированные первыми (heat в enum нет — остаётся только в computed);
    # pace_hr_mismatch без подтверждения в computed отброшен
    assert flags == ["hr_drift_high", "easy_run_too_hard", "great_session"]


def test_merged_flags_unit():
    """_merged_flags: маппинг, дедуп, фильтр по enum, cap 4."""
    merged = orchestrator._merged_flags(
        ["great_session", "pain", "hr_drift_high"],
        {"flags": ["decoupling_high", "decoupling_moderate", "hilly",
                   "easy_run_too_hard", "low_cadence", "rpe_elevated"]})
    assert merged == ["hr_drift_high", "easy_run_too_hard", "low_cadence",
                      "rpe_elevated"]                     # cap 4, subjective вытеснены
    assert orchestrator._merged_flags(["pain"], None) == ["pain"]
    assert orchestrator._merged_flags(["pain"], {"flags": []}) == ["pain"]
