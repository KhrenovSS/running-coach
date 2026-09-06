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


# --- 06.09.2026: потолки недели видят вердикт safety; карточка называет замену ---

def _forbid_hard_verdict():
    from src.coach.contracts import ReasoningStep, SafetyVerdict
    return SafetyVerdict(max_zone=2, allowed_types=("rest", "recovery", "easy", "long"),
                         triggered=["week_intensity_overload"],
                         reasons=[ReasoningStep(rule="p1_safety", decision="max_zone=2",
                                                reason="за 7 дней 31% времени в Z3+")])


def test_apply_safety_to_targets_zeroes_quality_caps():
    from src.coach.contracts import SafetyVerdict
    from src.coach.planning_safety import apply_safety_to_targets

    base = {"hard_days_max": 1, "remaining_hard_days_max": 1,
            "quality_z3_km_max": 5.6, "quality_z4_km_max": 2.8, "target_km": 28.0}
    out = apply_safety_to_targets(base, _forbid_hard_verdict())
    assert out["hard_days_max"] == 0 and out["remaining_hard_days_max"] == 0
    assert out["quality_z3_km_max"] == 0.0 and out["quality_z4_km_max"] == 0.0
    assert out["quality_blocked_by_safety"] == "за 7 дней 31% времени в Z3+"
    assert base["hard_days_max"] == 1                      # чистая функция: вход не мутирует
    # Обычный вердикт (всё разрешено) — без изменений
    assert apply_safety_to_targets(base, SafetyVerdict()) is base


def test_weekly_plan_gated_tempo_rendered_as_easy_with_reason(athlete_with_history, db_session,
                                                              monkeypatch):
    """Инцидент 06.09.2026: LLM заложил tempo при запрете интенсива → раньше «Длительный бег
    40 мин» и общее «урезано». Теперь: строка easy, карточка называет замену и причину,
    шапка — «без интенсива (safety)», LLM получил hard_days_max=0."""
    from src.coach import prescriber, weekly_plan

    verdict = _forbid_hard_verdict()
    monkeypatch.setattr(weekly_plan, "evaluate_safety", lambda state, **kw: verdict)
    monkeypatch.setattr(prescriber, "evaluate_safety", lambda state, **kw: verdict)
    seen: dict = {}
    real_today_block = weekly_plan.build_today_block

    def spy_today_block(state_json, verdict_json, now_str, extras=None):
        seen["targets"] = (extras or {}).get("week_targets (planning)")
        return real_today_block(state_json, verdict_json, now_str, extras=extras)
    monkeypatch.setattr(weekly_plan, "build_today_block", spy_today_block)
    turn = dict(PLAN_TURN, weekly_plan=[
        {"workout_type": "easy", "target_zone": 2, "duration_min": 40, "for_days_ahead": 2},
        {"workout_type": "tempo", "target_zone": 3, "duration_min": 40, "for_days_ahead": 4},
        {"workout_type": "long", "target_zone": 2, "duration_min": 70, "for_days_ahead": 7},
    ])
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=turn)])
    uid = athlete_with_history.id
    text = generate_weekly_plan(uid, db=db_session, llm=llm, now=_sunday(athlete_with_history))
    assert text is not None

    rows = {r.for_date: r for r in db_session.query(Recommendation).filter_by(
        user_id=uid, status="planned").all()}
    types = sorted(r.workout_type for r in rows.values())
    assert types == ["easy", "easy", "long"]               # tempo → easy, длительная осталась
    gated = [r for r in rows.values() if r.proposal_json["workout_type"] == "tempo"][0]
    assert gated.workout_type == "easy" and gated.clamped
    assert "🟠 Темповая → 🟢 Лёгкий бег — за 7 дней 31% времени в Z3+" in text
    assert "без интенсива (safety)" in text
    assert "Часть дней урезана" not in text
    # LLM видел обнулённые потолки (targets в контексте промпта)
    assert seen["targets"]["hard_days_max"] == 0
    assert seen["targets"]["quality_z3_km_max"] == 0.0
    assert seen["targets"]["quality_blocked_by_safety"] == "за 7 дней 31% времени в Z3+"


def test_weekly_plan_caps_long_run_by_code(athlete_with_history, db_session, monkeypatch):
    """06.09.2026: LLM дал длительную 70 мин ≈ 10 км при потолке 30 % недели — код урезает
    до потолка, карточка получает заметку, meta — флаг; LLM видел просьбы подопечного."""
    from src.coach import prescriber, weekly_plan
    from src.services.repositories_coach import CoachRepository

    uid = athlete_with_history.id
    CoachRepository.save_message(uid, "user", "тело просит аккуратных ускорений", db=db_session)

    def fake_predict(p, state, *, db):
        if p.workout_type == "rest":
            return {}
        # Быстрый темп → 70 мин ≈ 17,5 км, заведомо выше потолка 30 % любой недели фикстуры
        return {"pace_min_km": 4.0, "distance_km": round((p.volume.get("duration_min") or 0) / 4.0, 1)}
    monkeypatch.setattr(prescriber, "predict_volume", fake_predict)
    seen: dict = {}
    real_today_block = weekly_plan.build_today_block

    def spy(state_json, verdict_json, now_str, extras=None):
        seen["extras"] = extras or {}
        return real_today_block(state_json, verdict_json, now_str, extras=extras)
    monkeypatch.setattr(weekly_plan, "build_today_block", spy)

    turn = dict(PLAN_TURN, weekly_plan=[
        {"workout_type": "easy", "target_zone": 2, "duration_min": 40, "for_days_ahead": 2},
        {"workout_type": "long", "target_zone": 2, "duration_min": 70, "for_days_ahead": 7},
    ])
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=turn)])
    text = generate_weekly_plan(uid, db=db_session, llm=llm, now=_sunday(athlete_with_history))
    assert text is not None

    targets = seen["extras"]["week_targets (planning)"]
    cap_km = targets["long_run_km_max"]
    long_row = db_session.query(Recommendation).filter_by(
        user_id=uid, status="planned", workout_type="long").one()
    est_km = long_row.volume_json["duration_min"] / 4.0
    assert est_km <= cap_km + 0.3 + 0.15, (est_km, cap_km)   # допуск + округление минут
    assert long_row.volume_json["duration_min"] < 70
    assert "⚠️ Длительная урезана до" in text and "потолок 30 % недельного объёма" in text
    msg = db_session.query(CoachMessage).filter_by(user_id=uid, kind="plan", role="assistant") \
        .order_by(CoachMessage.id.desc()).first()
    assert msg.meta_json["long_run_capped"] is True
    requests_ = seen["extras"]["athlete_requests (chat, 7d)"]
    assert any("ускорений" in r["text"] for r in requests_)


def test_weekly_plan_caps_week_volume_and_puts_notes_in_card(athlete_with_history, db_session,
                                                              monkeypatch):
    """06.09.2026: сумма плана выше цели → лёгкие дни ужаты кодом, длительная под своим потолком,
    заметки стоят до футера, meta.week_volume_capped."""
    from src.coach import prescriber, weekly_plan

    def fake_predict(p, state, *, db):
        if p.workout_type == "rest":
            return {}
        return {"pace_min_km": 4.0, "distance_km": round((p.volume.get("duration_min") or 0) / 4.0, 1)}
    monkeypatch.setattr(prescriber, "predict_volume", fake_predict)
    seen: dict = {}
    real_today_block = weekly_plan.build_today_block

    def spy(state_json, verdict_json, now_str, extras=None):
        seen["targets"] = (extras or {}).get("week_targets (planning)")
        return real_today_block(state_json, verdict_json, now_str, extras=extras)
    monkeypatch.setattr(weekly_plan, "build_today_block", spy)

    # 3 × 90 мин по 4:00/км = 67,5 км — заведомо выше цели любой фикстуры
    turn = dict(PLAN_TURN, weekly_plan=[
        {"workout_type": "easy", "target_zone": 2, "duration_min": 90, "for_days_ahead": 1},
        {"workout_type": "easy", "target_zone": 2, "duration_min": 90, "for_days_ahead": 3},
        {"workout_type": "easy", "target_zone": 2, "duration_min": 90, "for_days_ahead": 5},
        {"workout_type": "long", "target_zone": 2, "duration_min": 40, "for_days_ahead": 7},
    ])
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=turn)])
    uid = athlete_with_history.id
    text = generate_weekly_plan(uid, db=db_session, llm=llm, now=_sunday(athlete_with_history))
    assert text is not None
    target_km = seen["targets"]["target_km"]

    rows = db_session.query(Recommendation).filter_by(user_id=uid, status="planned").all()
    total_km = sum(r.volume_json["duration_min"] / 4.0 for r in rows)
    assert total_km <= target_km * 1.05 + 0.5, (total_km, target_km)
    easy_minutes = [r.volume_json["duration_min"] for r in rows if r.workout_type == "easy"]
    assert easy_minutes and all(m < 90 for m in easy_minutes)
    card = text.split("*План на неделю")[1].split("\n")
    note_idx = next(i for i, l in enumerate(card) if "Объём недели урезан" in l)
    assert note_idx < len(card) - 1 and card[-1].startswith("Остальные дни — отдых")
    msg = db_session.query(CoachMessage).filter_by(user_id=uid, kind="plan", role="assistant") \
        .order_by(CoachMessage.id.desc()).first()
    assert msg.meta_json["week_volume_capped"] is True


def test_weekly_plan_keeps_strides_segments(athlete_with_history, db_session, monkeypatch):
    """06.09.2026: сегменты элементов weekly_plan терялись → обещанные ускорения не доходили до
    карточки. Теперь лёгкий день с 4×20 с при закрытом интенсиве сохраняет структуру."""
    from src.coach import prescriber, weekly_plan

    verdict = _forbid_hard_verdict()
    monkeypatch.setattr(weekly_plan, "evaluate_safety", lambda state, **kw: verdict)
    monkeypatch.setattr(prescriber, "evaluate_safety", lambda state, **kw: verdict)
    strides_day = {
        "workout_type": "easy", "target_zone": 2, "duration_min": 40, "for_days_ahead": 2,
        "segments": [
            {"role": "warmup", "amount_kind": "min", "amount_value": 25, "target_zone": 2},
            {"role": "work", "amount_kind": "sec", "amount_value": 20, "repeat": 4,
             "target_zone": 3, "effort": "свободно", "recovery": {"duration_min": 1.5}},
            {"role": "cooldown", "amount_kind": "min", "amount_value": 8, "target_zone": 2},
        ],
    }
    turn = dict(PLAN_TURN, weekly_plan=[strides_day,
                                        {"workout_type": "long", "target_zone": 2,
                                         "duration_min": 50, "for_days_ahead": 7}])
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=turn)])
    uid = athlete_with_history.id
    text = generate_weekly_plan(uid, db=db_session, llm=llm, now=_sunday(athlete_with_history))
    assert text is not None
    row = db_session.query(Recommendation).filter_by(user_id=uid, status="planned",
                                                     workout_type="easy").one()
    segs = (row.target_json or {}).get("segments") or []
    assert segs, "сегменты ускорений потеряны при сборке плана"
    assert any(s.get("role") == "work" and s.get("repeat") == 4 for s in segs)
    assert not row.clamped                                        # ускорения — не интенсив
    assert "4×20 сек" in text or "4×20" in text


def test_weekly_plan_volume_cap_skips_structured_day_and_leaves_trail(athlete_with_history,
                                                                       db_session, monkeypatch):
    """06.09.2026: перебор объёма + день с ускорениями → структурный день неизменен, соседние
    ужаты, proposal_json.rationale урезанных дней содержит «урезано кодом»."""
    from src.coach import prescriber

    def fake_predict(p, state, *, db):
        if p.workout_type == "rest":
            return {}
        return {"pace_min_km": 4.0, "distance_km": round((p.volume.get("duration_min") or 0) / 4.0, 1)}
    monkeypatch.setattr(prescriber, "predict_volume", fake_predict)
    strides = [{"role": "warmup", "amount_kind": "min", "amount_value": 20, "target_zone": 2},
               {"role": "work", "amount_kind": "sec", "amount_value": 20, "repeat": 5,
                "target_zone": 3, "recovery": {"duration_min": 2.0}},
               {"role": "cooldown", "amount_kind": "min", "amount_value": 10, "target_zone": 2}]
    turn = dict(PLAN_TURN, weekly_plan=[
        {"workout_type": "easy", "target_zone": 2, "duration_min": 90, "for_days_ahead": 1},
        {"workout_type": "easy", "target_zone": 2, "duration_min": 39, "for_days_ahead": 3,
         "segments": strides},   # 39 при сегментах на 42 — код выставит 42 (06.09.2026)
        {"workout_type": "easy", "target_zone": 2, "duration_min": 90, "for_days_ahead": 5},
        {"workout_type": "long", "target_zone": 2, "duration_min": 40, "for_days_ahead": 7},
    ])
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=turn)])
    uid = athlete_with_history.id
    text = generate_weekly_plan(uid, db=db_session, llm=llm, now=_sunday(athlete_with_history))
    assert text is not None and "Объём недели урезан" in text
    rows = db_session.query(Recommendation).filter_by(user_id=uid, status="planned").all()
    structured = [r for r in rows if (r.target_json or {}).get("segments")]
    assert len(structured) == 1 and structured[0].volume_json["duration_min"] == 42   # из сегментов
    trimmed = [r for r in rows if r.workout_type == "easy" and not (r.target_json or {}).get("segments")]
    assert trimmed and all(r.volume_json["duration_min"] < 90 for r in trimmed)
    assert all(any(x.startswith("урезано кодом") for x in r.proposal_json["rationale"]) for r in trimmed)
    structured_line = next(l for l in text.splitlines() if "5×20 сек свободно" in l)
    assert "(отдых 2 мин трусцой)" in structured_line
    assert " 42 мин" in structured_line and " 39 мин" not in structured_line   # длительность из сегментов
