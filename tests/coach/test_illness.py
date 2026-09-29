# Гейт болезни (#322, 07.09.2026; ступени — решение владельца 29.09.2026) — гайд 50: болен →
# тренировки закрыты; после выздоровления — полный покой ILLNESS_REST_DAYS[kind], затем окно
# «только легко» ILLNESS_EASY_DAYS[kind] (правило 21b): бег разрешён, Z2, без интенсива.
# План и чат закрытые дни не трогают; окно «легко» сужает safety.clamp, не блок.

from datetime import timedelta

from src.coach import illness, orchestrator, planning
from src.coach.config import ILLNESS_EASY_DAYS, ILLNESS_EASY_MAX_DURATION_MIN, ILLNESS_REST_DAYS
from src.coach.contracts import WorkoutProposal
from src.coach.llm.client import LLMResponse
from src.coach.llm.schemas import CoachTurn, IllnessReport
from src.coach.planning_safety import project_state, quality_reopens_at
from src.coach.rules.p1_safety import evaluate_safety
from src.coach.safety import clamp
from src.coach.state import assess_state
from src.utils.timeutils import user_now
from tests.coach.fakes import ScriptedLLM

BASE_TURN = {"message": "Понял.", "proposal": None, "followup_question": None,
             "log_suggestion": None}


def test_turn_schema_accepts_illness():
    turn = CoachTurn(**BASE_TURN, illness={"status": "sick", "kind": "flu", "days_ago": 1})
    assert turn.illness.status == "sick" and turn.illness.kind == "flu"
    assert CoachTurn(**BASE_TURN).illness is None


def test_constants_staged():
    """Покой короче окна «легко» для каждого вида; ключи совпадают."""
    assert set(ILLNESS_REST_DAYS) == set(ILLNESS_EASY_DAYS)
    assert all(ILLNESS_REST_DAYS[k] < ILLNESS_EASY_DAYS[k] for k in ILLNESS_REST_DAYS)


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


def test_recovery_staged_rest_then_easy_only(athlete_with_history, db_session):
    """Простуда: день 0 — покой; с дня 1 — бег разрешён, но Z2/без интенсива/≤ 60 мин;
    после окна — чисто. Ускорения в окне clamp понижает до easy, не отбрасывает."""
    uid = athlete_with_history.id
    now = user_now(athlete_with_history)
    rest, easy = ILLNESS_REST_DAYS["cold"], ILLNESS_EASY_DAYS["cold"]
    text = illness.record_illness(IllnessReport(status="recovered", kind="cold", days_ago=0),
                                  uid, db=db_session, now=now)
    rest_until = now.date() + timedelta(days=rest)
    easy_until = now.date() + timedelta(days=easy)
    assert f"бег с {rest_until:%d.%m}" in text and f"до {easy_until:%d.%m}" in text
    assert "только лёгкие" in text
    st = illness.illness_state(uid, db=db_session)
    assert st["rest_until"] == rest_until.isoformat() and st["easy_until"] == easy_until.isoformat()
    assert "pause_until" not in st
    state = assess_state(uid, db=db_session)
    v0 = evaluate_safety(state, now=now)
    assert v0.allow_training is False and "illness" in v0.triggered
    assert f"{rest_until:%d.%m}" in v0.reasons[-1].reason
    v1 = evaluate_safety(project_state(state, {}, rest), now=now)
    assert v1.allow_training is True and "illness_return" in v1.triggered
    assert v1.max_zone == 2 and "tempo" not in v1.allowed_types
    assert v1.max_duration_min is not None and v1.max_duration_min <= ILLNESS_EASY_MAX_DURATION_MIN
    assert f"{easy_until:%d.%m}" in v1.reasons[-1].reason
    strides = WorkoutProposal(workout_type="tempo", target_zone=4, duration_min=45)
    card, clamped = clamp(strides, v1, state, now=now)
    assert clamped and card.workout_type == "easy" and card.target.get("max_zone", 2) <= 2
    v_end = evaluate_safety(project_state(state, {}, easy), now=now)
    assert "illness" not in v_end.triggered and "illness_return" not in v_end.triggered
    # kind без уточнения при выздоровлении — из прежней записи (грипп → свои ступени)
    illness.record_illness(IllnessReport(status="sick", kind="flu"), uid, db=db_session, now=now)
    illness.record_illness(IllnessReport(status="recovered"), uid, db=db_session, now=now)
    st = illness.illness_state(uid, db=db_session)
    assert st["kind"] == "flu"
    assert st["easy_until"] == (now.date() + timedelta(days=ILLNESS_EASY_DAYS["flu"])).isoformat()


def test_legacy_pause_until_record_uses_staged_windows(athlete_with_history, db_session):
    """Запись до 29.09.2026 (только pause_until) читается по новым ступеням от recovered_at:
    прод 29.09 — recovered_at 24.09, cold → покой до 25.09, легко до 01.10, не запрет до 08.10."""
    uid = athlete_with_history.id
    today = user_now(athlete_with_history).date()
    recovered = today - timedelta(days=5)
    illness._save(uid, {"status": "recovered", "kind": "cold", "since": None,
                        "recovered_at": recovered.isoformat(),
                        "pause_until": (recovered + timedelta(days=14)).isoformat()}, db=db_session)
    st = illness.illness_state(uid, db=db_session)
    assert illness.stages(st) == (recovered + timedelta(days=1), recovered + timedelta(days=7))
    assert illness.block_days(st, today) is None
    assert illness.easy_days(st, today) == 2
    assert illness.blocked_reason(uid, db=db_session, when=today, today=today) is None
    ctx = illness.context_block(st, today)
    assert ctx["blocked_days_from_today"] is None and ctx["easy_days_from_today"] == 2
    assert ctx["easy_until"] == (recovered + timedelta(days=7)).isoformat()


def test_recovery_long_ago_has_no_block(athlete_with_history, db_session):
    uid = athlete_with_history.id
    now = user_now(athlete_with_history)
    text = illness.record_illness(IllnessReport(status="recovered", kind="other", days_ago=30),
                                  uid, db=db_session, now=now)
    assert "уже вышло" in text
    st = illness.illness_state(uid, db=db_session)
    assert illness.block_days(st, now.date()) is None and illness.easy_days(st, now.date()) is None
    assert illness.context_block(st, now.date()) is None
    assert evaluate_safety(assess_state(uid, db=db_session), now=now).allow_training is True


def test_recovery_rest_already_passed_text(athlete_with_history, db_session):
    """Выздоровел 3 дня назад (простуда): покой вышел — «бегать уже можно», окно «легко» открыто."""
    uid = athlete_with_history.id
    now = user_now(athlete_with_history)
    text = illness.record_illness(IllnessReport(status="recovered", kind="cold", days_ago=3),
                                  uid, db=db_session, now=now)
    assert "Бегать уже можно" in text
    assert illness.blocked_reason(uid, db=db_session, when=now.date(), today=now.date()) is None


def test_week_targets_exclude_rest_days_only(athlete_with_history, db_session):
    """Полный покой закрывает даты плана; окно «легко» — дни открыты, но интенсива нет.
    Якорь — будущий понедельник 09:00: среди недели `/plan` = остаток недели (#293, #328)."""
    uid = athlete_with_history.id
    real_now = user_now(athlete_with_history)
    days = (0 - real_now.weekday()) % 7 or 7
    now = (real_now + timedelta(days=days)).replace(hour=9, minute=0, second=0, microsecond=0)
    illness.record_illness(IllnessReport(status="recovered", kind="other", days_ago=0),
                           uid, db=db_session, now=now)
    t = planning.week_targets(uid, db=db_session, today=now.date())
    rest, easy = ILLNESS_REST_DAYS["other"], ILLNESS_EASY_DAYS["other"]
    assert all(d >= rest for d in t["days_ahead_allowed"])
    assert any(rest <= d < easy for d in t["days_ahead_allowed"])   # окно «легко» открыто
    assert t["illness"]["blocked_days_from_today"] == rest
    assert t["illness"]["easy_days_from_today"] == easy
    assert len(t["availability"]["unavailable_dates"]) >= rest
    # интенсив закрыт на всё окно «легко»: прогноз по дню плана (weekly_plan → apply_safety_to_targets)
    state = assess_state(uid, db=db_session)
    assert quality_reopens_at(state, {}, now=now, days=list(range(rest, easy))) is None


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


def test_chat_in_easy_window_keeps_easy_run_and_downgrades_strides(athlete_with_history, db_session):
    """Окно «легко»: лёгкая пробежка назначается (не «не назначаю»), ускорения понижаются."""
    uid = athlete_with_history.id
    now = user_now(athlete_with_history)
    illness.record_illness(IllnessReport(status="recovered", kind="cold", days_ago=2),
                           uid, db=db_session, now=now)
    turn = {**BASE_TURN, "message": "Ок, побегаем.",
            "proposal": {"workout_type": "interval", "target_zone": 4, "duration_min": 40,
                         "for_days_ahead": 0}}
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=turn)])
    reply = orchestrator.handle_chat(uid, "хочу сегодня ускорения", db=db_session, llm=llm)
    assert "не назначаю" not in reply.text and "Лёгкий бег" in reply.text
    rows = planning.latest_rows_for_dates(uid, db=db_session, dates=[now.date()])
    assert rows and rows[now.date()].workout_type == "easy" and rows[now.date()].clamped
