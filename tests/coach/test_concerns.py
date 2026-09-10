# Актуальные проблемы подопечного (coach/concerns.py, 10.09.2026): LLM сообщает факт, код ведёт
# контроль; без жалоб CONCERN_EXPIRE_DAYS проблема снимается; колено не захардкожено.

from datetime import timedelta

from src.coach import concerns, orchestrator
from src.coach.config import CONCERN_EXPIRE_DAYS
from src.coach.llm.client import LLMResponse
from src.coach.llm.prompts import SYSTEM_PERSONA
from src.coach.llm.schemas import CoachTurn, ConcernReport
from src.coach.skills import pain
from src.coach.state import assess_state
from src.coach.turn_context import build_extras, profile
from src.models import WellnessReport
from src.domain.models.base import utcnow
from src.utils.timeutils import user_now
from tests.coach.conftest import _unique_user
from tests.coach.fakes import ScriptedLLM

BASE_TURN = {"message": "Понял.", "proposal": None, "followup_question": None,
             "log_suggestion": None}


def test_turn_schema_accepts_concern():
    turn = CoachTurn(**BASE_TURN, concern={"status": "new", "kind": "injury",
                                           "location": "ankle", "label": "подвернул стопу"})
    assert turn.concern.status == "new" and turn.concern.location == "ankle"
    assert CoachTurn(**BASE_TURN).concern is None


def test_lifecycle_create_refresh_expire_resolve(db_session):
    user = _unique_user(db_session)
    now = user_now(user)
    today = now.date()
    text = concerns.record_concern(
        ConcernReport(status="new", kind="injury", location="ankle", label="подвернул стопу"),
        user.id, db=db_session, now=now)
    assert "Запомнил" in text and "голеностоп" in text and str(CONCERN_EXPIRE_DAYS) in text
    assert len(concerns.active_concerns(user.id, db=db_session, today=today)) == 1

    # тап боли через 5 дней продлевает контроль: на +18 дней проблема ещё активна
    concerns.refresh_from_pain(user.id, 2, db=db_session, today=today + timedelta(days=5))
    late = today + timedelta(days=5 + CONCERN_EXPIRE_DAYS - 1)
    assert concerns.active_concerns(user.id, db=db_session, today=late)
    # без сигналов CONCERN_EXPIRE_DAYS дней — не актуальна
    gone = today + timedelta(days=5 + CONCERN_EXPIRE_DAYS)
    assert concerns.active_concerns(user.id, db=db_session, today=gone) == []
    # ongoing на активной — обновляет упоминание, не дублирует
    concerns.record_concern(ConcernReport(status="ongoing", kind="injury", location="ankle"),
                            user.id, db=db_session, now=now)
    assert len(concerns.concerns_state(user.id, db=db_session)) == 1
    # resolved — снятие с контроля
    text = concerns.record_concern(ConcernReport(status="resolved", kind="injury", location="ankle"),
                                   user.id, db=db_session, now=now)
    assert "Снял с контроля" in text
    assert concerns.active_concerns(user.id, db=db_session, today=today) == []
    assert concerns.concerns_state(user.id, db=db_session)[0]["status"] == "resolved"


def test_pain_tap_creates_concern_without_chat(db_session):
    user = _unique_user(db_session)
    today = user_now(user).date()
    concerns.refresh_from_pain(user.id, 0, db=db_session, today=today)
    assert concerns.active_concerns(user.id, db=db_session, today=today) == []
    concerns.refresh_from_pain(user.id, 3, db=db_session, today=today)
    active = concerns.active_concerns(user.id, db=db_session, today=today)
    assert len(active) == 1 and active[0]["source"] == "pain_tap"
    assert concerns.primary_location(user.id, db=db_session, today=today) is None  # не уточнена
    assert concerns.pain_prompt_label(user.id, db=db_session, today=today) == "Боль или дискомфорт?"


def test_profile_and_persona_have_no_hardcoded_knee(db_session):
    user = _unique_user(db_session)
    assert "injuries" not in profile(user)
    # «правила боли в колене» (гайд 30) — методика, остаётся; травма подопечного — нет
    assert "травмы колена" not in SYSTEM_PERSONA and "беречь колено" not in SYSTEM_PERSONA


def test_missing_pain_only_with_active_concern(db_session):
    user = _unique_user(db_session)
    today = user_now(user).date()
    assert "pain" not in assess_state(user.id, db=db_session).missing
    # активная травма + устаревшая отметка → честный пробел «pain»
    concerns.record_concern(ConcernReport(status="new", kind="injury", location="knee"),
                            user.id, db=db_session, now=user_now(user))
    db_session.add(WellnessReport(user_id=user.id, report_date=utcnow().date() - timedelta(days=4),
                                  pain_level=3, pain_location="knee"))
    db_session.commit()
    res = pain.evaluate(user.id, db=db_session)
    assert res.value is None and "колено" not in res.message
    assert "pain" in assess_state(user.id, db=db_session).missing


def test_evening_question_names_the_location(db_session):
    user = _unique_user(db_session)
    now = user_now(user)
    assert concerns.evening_check_needed(user.id, db=db_session) is False
    concerns.record_concern(ConcernReport(status="new", kind="injury", location="ankle"),
                            user.id, db=db_session, now=now)
    assert concerns.evening_check_needed(user.id, db=db_session) is True
    active = concerns.active_concerns(user.id, db=db_session, today=now.date())
    assert "Голеностоп" in concerns.evening_question(active)
    assert concerns.pain_prompt_label(user.id, db=db_session, today=now.date()) == "Голеностоп?"


def test_chat_records_concern_and_context_block(athlete_with_history, db_session):
    uid = athlete_with_history.id
    today = user_now(athlete_with_history).date()
    assert "concerns (params)" not in build_extras(uid, db=db_session)
    turn = {**BASE_TURN, "message": "Бережём ногу.",
            "concern": {"status": "new", "kind": "injury", "location": "ankle",
                        "label": "подвернул на тропе", "days_ago": 1}}
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=turn)])
    reply = orchestrator.handle_chat(uid, "вчера подвернул ногу на тропе", db=db_session, llm=llm)
    assert "Запомнил" in reply.text and "голеностоп" in reply.text
    block = build_extras(uid, db=db_session)["concerns (params)"]
    assert block[0]["location"] == "ankle" and block[0]["days_since"] == 1
    assert block[0]["expires_in_days"] == CONCERN_EXPIRE_DAYS
    assert concerns.active_concerns(uid, db=db_session, today=today)[0]["label"] == "подвернул на тропе"
