# Гейт болезни (#322, 07.09.2026) — гайд 50 (Швец): болен → тренировки закрыты; после
# выздоровления — пауза ILLNESS_PAUSE_DAYS[kind]; план и чат закрытые дни не трогают.

from datetime import timedelta

from src.coach import illness, orchestrator, planning
from src.coach.config import ILLNESS_PAUSE_DAYS
from src.coach.llm.client import LLMResponse
from src.coach.llm.schemas import CoachTurn, IllnessReport
from src.coach.planning_safety import project_state
from src.coach.rules.p1_safety import evaluate_safety
from src.coach.state import assess_state
from src.utils.timeutils import user_now
from tests.coach.fakes import ScriptedLLM

BASE_TURN = {"message": "Понял.", "proposal": None, "followup_question": None,
             "log_suggestion": None}


def test_turn_schema_accepts_illness():
    turn = CoachTurn(**BASE_TURN, illness={"status": "sick", "kind": "flu", "days_ago": 1})
    assert turn.illness.status == "sick" and turn.illness.kind == "flu"
    assert CoachTurn(**BASE_TURN).illness is None


def test_sick_blocks_training_until_recovery(athlete_with_history, db_session):
    uid = athlete_with_history.id
    now = user_now(athlete_with_history)
    text = illness.record_illness(IllnessReport(status="sick", kind="cold"), uid, db=db_session, now=now)
    assert "закрыты до выздоровления" in text
    state = assess_state(uid, db=db_session)
    verdict = evaluate_safety(state, now=now)
    assert verdict.allow_training is False and "illness" in verdict.triggered
    # прогноз на 7 дней вперёд — всё ещё закрыто (болен без сообщения о выздоровлении)
    assert evaluate_safety(project_state(state, {}, 7), now=now).allow_training is False
    assert illness.blocked_reason(uid, db=db_session, when=now.date(), today=now.date())


def test_recovery_pause_by_kind_and_projection(athlete_with_history, db_session):
    uid = athlete_with_history.id
    now = user_now(athlete_with_history)
    pause = ILLNESS_PAUSE_DAYS["cold"]
    text = illness.record_illness(IllnessReport(status="recovered", kind="cold", days_ago=0),
                                  uid, db=db_session, now=now)
    until = now.date() + timedelta(days=pause)
    assert f"{until:%d.%m}" in text and str(pause) in text
    st = illness.illness_state(uid, db=db_session)
    assert st["status"] == "recovered" and st["pause_until"] == until.isoformat()
    state = assess_state(uid, db=db_session)
    assert evaluate_safety(state, now=now).allow_training is False
    assert evaluate_safety(project_state(state, {}, pause - 1), now=now).allow_training is False
    assert evaluate_safety(project_state(state, {}, pause), now=now).allow_training is True
    # kind без уточнения при выздоровлении — из прежней записи (грипп → своя пауза)
    illness.record_illness(IllnessReport(status="sick", kind="flu"), uid, db=db_session, now=now)
    illness.record_illness(IllnessReport(status="recovered"), uid, db=db_session, now=now)
    assert illness.illness_state(uid, db=db_session)["kind"] == "flu"


def test_recovery_long_ago_has_no_block(athlete_with_history, db_session):
    uid = athlete_with_history.id
    now = user_now(athlete_with_history)
    text = illness.record_illness(IllnessReport(status="recovered", kind="other", days_ago=30),
                                  uid, db=db_session, now=now)
    assert "уже вышла" in text
    assert illness.block_days(illness.illness_state(uid, db=db_session), now.date()) is None
    assert evaluate_safety(assess_state(uid, db=db_session), now=now).allow_training is True


def test_week_targets_exclude_paused_days(athlete_with_history, db_session):
    uid = athlete_with_history.id
    now = user_now(athlete_with_history)
    illness.record_illness(IllnessReport(status="recovered", kind="other", days_ago=0),
                           uid, db=db_session, now=now)
    t = planning.week_targets(uid, db=db_session, today=now.date())
    pause = ILLNESS_PAUSE_DAYS["other"]
    assert all(d >= pause for d in t["days_ahead_allowed"])
    assert t["illness"]["blocked_days_from_today"] == pause
    assert len(t["availability"]["unavailable_dates"]) >= min(pause, 6)


def test_chat_records_illness_and_drops_proposal(athlete_with_history, db_session):
    """«Заболел, температура» → запись, текст с решением кода, назначение LLM отброшено."""
    uid = athlete_with_history.id
    turn = {**BASE_TURN, "message": "Выздоравливай!",
            "proposal": {"workout_type": "easy", "target_zone": 2, "duration_min": 30,
                         "for_days_ahead": 1},
            "illness": {"status": "sick", "kind": "cold", "days_ago": 0}}
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=turn)])
    reply = orchestrator.handle_chat(uid, "заболел, температура 38", db=db_session, llm=llm)
    assert "Зафиксировал болезнь" in reply.text
    assert "не назначаю" in reply.text
    assert "Лёгкий бег" not in reply.text
    assert illness.illness_state(uid, db=db_session)["status"] == "sick"
