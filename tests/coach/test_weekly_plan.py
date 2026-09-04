# Тесты генерации недельного плана (Weekly plan generation tests)
from datetime import date, timedelta

from src.coach.llm.client import LLMResponse
from src.coach.weekly_plan import generate_weekly_plan
from src.models import CoachMessage, Recommendation, UserModel
from tests.coach.conftest import _unique_user
from tests.coach.fakes import FailingLLM, ScriptedLLM
from src.utils.timeutils import user_now


def _sunday(user):
    """Локальное «сейчас» = ближайшее будущее воскресенье 19:00 — план на всю неделю
    (окно 1..7) независимо от реального дня недели (deterministic Sunday anchor)."""
    now = user_now(user)
    days = (6 - now.weekday()) % 7 or 7
    return (now + timedelta(days=days)).replace(hour=19, minute=0, second=0, microsecond=0)


def _wednesday(user):
    """Будущая среда 09:00 — остаток недели, пробежек в той неделе ещё нет (окно 0..4)."""
    now = user_now(user)
    days = (2 - now.weekday()) % 7 or 7
    return (now + timedelta(days=days)).replace(hour=9, minute=0, second=0, microsecond=0)

PLAN_TURN = {
    "message": "Неделя роста: аккуратно наращиваем объём, одна длительная.",
    "proposal": None,
    "followup_question": None,
    "log_suggestion": None,
    "weekly_plan": [
        {"workout_type": "easy", "target_zone": 2, "duration_min": 40,
         "for_days_ahead": 2},
        {"workout_type": "easy", "target_zone": 2, "duration_min": 45,
         "for_days_ahead": 4},
        {"workout_type": "rest", "target_zone": 1, "for_days_ahead": 5},
        {"workout_type": "long", "target_zone": 2, "duration_min": 70,
         "for_days_ahead": 7},
        {"workout_type": "easy", "target_zone": 2, "duration_min": 30,
         "for_days_ahead": 0},   # день 0 — отбрасывается (план только вперёд)
        {"workout_type": "easy", "target_zone": 2, "duration_min": 50,
         "for_days_ahead": 4},   # дубль дня — побеждает последний
    ],
}


def test_generate_weekly_plan_persists_rows(athlete_with_history, db_session):
    """План: строки status='planned' на будущие даты, rest/день-0/дубли чищены,
    карточка недели, kind='plan', мета мезоцикла в params_json."""
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=PLAN_TURN)])
    uid = athlete_with_history.id
    text = generate_weekly_plan(uid, db=db_session, llm=llm, now=_sunday(athlete_with_history))
    assert text is not None

    rows = db_session.query(Recommendation).filter_by(
        user_id=uid, status="planned").all()
    assert len(rows) == 3                                 # дни 2, 4(дубль→50мин), 7
    assert all(r.for_date > date.today() - timedelta(days=1) for r in rows)
    by_day = {r.for_date: r for r in rows}
    day4 = [r for r in rows if r.volume_json.get("duration_min") == 50.0]
    assert len(day4) == 1                                 # дубль дня схлопнут
    assert not any(r.workout_type == "rest" for r in rows)

    assert "План на неделю" in text
    assert "мезоцикла" in text and "Остальные дни — отдых" in text
    msg = db_session.query(CoachMessage).filter_by(
        user_id=uid, kind="plan", role="assistant").first()
    assert msg is not None and msg.meta_json["days"] == 3

    um = db_session.query(UserModel).filter_by(user_id=uid).first()
    meta = um.params_json["week_plan"]
    assert meta["mesocycle_week"] >= 1 and meta["target_km"] > 0


def test_generate_weekly_plan_llm_failure_returns_none(athlete_with_history,
                                                       db_session):
    """LLM недоступна → None и НИ ОДНОЙ строки плана (fallback-плана нет)."""
    uid = athlete_with_history.id
    before = db_session.query(Recommendation).filter_by(user_id=uid).count()
    assert generate_weekly_plan(uid, db=db_session, llm=FailingLLM()) is None
    assert db_session.query(Recommendation).filter_by(
        user_id=uid).count() == before


def test_generate_weekly_plan_empty_list_returns_none(athlete_with_history,
                                                      db_session):
    """weekly_plan=null от LLM → None (план не создан)."""
    turn = dict(PLAN_TURN, weekly_plan=None)
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=turn)])
    assert generate_weekly_plan(athlete_with_history.id,
                                db=db_session, llm=llm) is None


def test_weekly_plan_field_dropped_in_chat(athlete_with_history, db_session):
    """weekly_plan в обычном чате НЕ персистится, но вместо молчаливого дропа
    показывается сохранённый план недели (инцидент 02.09.2026: «общие слова»)."""
    from src.coach import orchestrator
    from src.coach.week_view import NO_PLAN_TEXT

    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=PLAN_TURN)])
    uid = athlete_with_history.id
    before = db_session.query(Recommendation).filter_by(user_id=uid).count()
    reply = orchestrator.handle_chat(uid, "привет", db=db_session, llm=llm)
    assert reply.source == "llm"
    assert db_session.query(Recommendation).filter_by(
        user_id=uid).count() == before                    # план не записан
    assert NO_PLAN_TEXT in reply.text                     # плана нет → подсказка /plan


def test_replan_supersedes_previous_future_rows(athlete_with_history, db_session):
    """Повторный /plan гасит будущие строки прежнего плана (инцидент 02.09.2026:
    строки первого плана «ожили» и дали 7 беговых дней в /week)."""
    uid = athlete_with_history.id
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=PLAN_TURN),
                       LLMResponse(stop_reason="end_turn", parsed=PLAN_TURN)])
    sunday = _sunday(athlete_with_history)
    assert generate_weekly_plan(uid, db=db_session, llm=llm, now=sunday) is not None
    first_ids = {r.id for r in db_session.query(Recommendation).filter_by(
        user_id=uid, status="planned").all()}
    assert len(first_ids) == 3

    assert generate_weekly_plan(uid, db=db_session, llm=llm, now=sunday) is not None
    rows = db_session.query(Recommendation).filter_by(user_id=uid).all()
    by_id = {r.id: r for r in rows}
    assert all(by_id[i].status == "superseded" for i in first_ids)
    active = [r for r in rows if r.status == "planned"]
    assert len(active) == 3 and not (first_ids & {r.id for r in active})
    msg = db_session.query(CoachMessage).filter_by(
        user_id=uid, kind="plan", role="assistant").order_by(CoachMessage.id.desc()).first()
    assert msg.meta_json["superseded"] == 3


def test_run_day_cap_trims_plan_and_notes_it(athlete_with_history, db_session):
    """LLM вернула больше беговых дней, чем run_days_max → лишние лёгкие урезаны,
    под карточкой — пометка; каркас (long) сохранён."""
    from src.coach import planning

    seven = {**PLAN_TURN, "weekly_plan": [
        {"workout_type": "easy", "target_zone": 2, "duration_min": 30 + d,
         "for_days_ahead": d} for d in range(1, 7)] + [
        {"workout_type": "long", "target_zone": 2, "duration_min": 70, "for_days_ahead": 7}]}
    uid = athlete_with_history.id
    sunday = _sunday(athlete_with_history)
    cap = planning.week_targets(uid, db=db_session, today=sunday.date())["remaining_run_days_max"]
    assert cap < 7
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=seven)])
    text = generate_weekly_plan(uid, db=db_session, llm=llm, now=sunday)
    rows = db_session.query(Recommendation).filter_by(user_id=uid, status="planned").all()
    assert len(rows) == cap
    assert any(r.workout_type == "long" for r in rows)
    assert f"Беговых дней урезано до {cap}" in text


def test_clean_days_respects_window():
    """_clean_days: только дни из окна; день 0 принимается лишь когда он в окне (#293)."""
    from src.coach.contracts import WorkoutProposal as WP
    from src.coach.weekly_plan import _clean_days

    items = [WP(workout_type="easy", target_zone=2, duration_min=30, for_days_ahead=d)
             for d in (0, 1, 3, 6, 7)]
    assert [it.for_days_ahead for it in _clean_days(items)] == [1, 3, 6, 7]      # default 1..7
    assert [it.for_days_ahead for it in _clean_days(items, allowed=[0, 1, 2, 3, 4])] == [0, 1, 3]


def test_midweek_plan_covers_rest_of_week_only(athlete_with_history, db_session):
    """Среда без пробежки: окно 0..4 — день 0 записан (planned, строки на сегодня не было),
    день 7 отброшен; все даты внутри пн–вс той недели; в шапке — «сделано … осталось»."""
    from src.coach.planning_window import monday_of

    uid = athlete_with_history.id
    wed = _wednesday(athlete_with_history)
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=PLAN_TURN)])
    text = generate_weekly_plan(uid, db=db_session, llm=llm, now=wed)
    assert text is not None
    rows = db_session.query(Recommendation).filter(
        Recommendation.user_id == uid, Recommendation.for_date >= wed.date()).all()
    offsets = sorted((r.for_date - wed.date()).days for r in rows)
    assert offsets == [0, 2, 4]                           # 7 — за окном, 5 — rest
    monday = monday_of(wed.date())
    assert all(monday <= r.for_date <= monday + timedelta(days=6) for r in rows)
    assert all(r.status == "planned" for r in rows)
    assert "сделано 0.0 км, осталось" in text
    assert f"▶ Ср {wed:%d.%m}" in text


def test_midweek_day0_replaces_existing_today_row_as_adjusted(athlete_with_history, db_session):
    """Если на «сегодня» уже была строка плана — день 0 пишется как adjusted,
    старая строка гасится (superseded)."""
    uid = athlete_with_history.id
    wed = _wednesday(athlete_with_history)
    old = Recommendation(user_id=uid, for_date=wed.date(), workout_type="tempo",
                         target_json={"max_zone": 3}, volume_json={"duration_min": 45.0},
                         status="planned", source="llm")
    db_session.add(old)
    db_session.commit()
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=PLAN_TURN)])
    assert generate_weekly_plan(uid, db=db_session, llm=llm, now=wed) is not None
    db_session.refresh(old)
    assert old.status == "superseded"
    today_rows = db_session.query(Recommendation).filter_by(
        user_id=uid, for_date=wed.date()).order_by(Recommendation.id.desc()).all()
    assert today_rows[0].status == "adjusted" and today_rows[0].workout_type == "easy"


def test_plan_with_closed_availability_window_returns_notice(db_session, monkeypatch):
    """#294: все дни окна закрыты → текст-объяснение без вызова LLM и без записи строк."""
    from src.coach import planning
    from src.coach.weekly_plan import generate_weekly_plan
    from src.models import Recommendation
    from tests.coach.conftest import _unique_user
    from tests.coach.fakes import ScriptedLLM

    user = _unique_user(db_session)
    monkeypatch.setattr(planning, "week_targets", lambda *a, **k: {
        "days_ahead_allowed": [], "availability": {"weekday_names": ["Пн", "Вт"]},
        "week_start": "2026-09-07"})
    llm = ScriptedLLM([])
    text = generate_weekly_plan(user.id, db=db_session, llm=llm)
    assert "бегать некуда" in text and "Пн, Вт" in text
    assert llm.calls == []
    assert db_session.query(Recommendation).filter_by(user_id=user.id).count() == 0
