# Тесты D7: каналы влияния разбора на будущие тренировки
# (D7 tests: review → future workouts influence channels) — DEV_PLAN §9 D-серия

from src.coach import orchestrator
from src.coach.llm.client import LLMResponse
from src.coach.prescriber import finalize
from src.coach.state import assess_state
from src.models import TrainingSession
from src.services.repositories_insights import InsightRepository
from tests.coach.fakes import ScriptedLLM

PLAIN_TURN = {"message": "Доброе утро! План простой.", "proposal": None,
              "followup_question": None, "log_suggestion": None}


def _finish_review(user_id, db, carry: str):
    sid = db.query(TrainingSession).filter_by(user_id=user_id).order_by(
        TrainingSession.begin_ts.desc()).first().id
    InsightRepository.upsert(user_id, sid, db=db)
    InsightRepository.finish(sid, db=db, source="llm", effort_match="harder",
                             assessment={"flags": ["hr_drift_high"]},
                             carry_forward=carry)
    return sid


def test_carry_forward_reaches_morning_context(athlete_with_history, db_session):
    """carry_forward вчерашнего разбора инлайнится в контекст утреннего хода."""
    _finish_review(athlete_with_history.id, db_session,
                   "жара выбила — завтра только лёгкий")
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=PLAIN_TURN)])
    orchestrator.handle_chat(athlete_with_history.id, "что сегодня делать?",
                             db=db_session, llm=llm, kind="morning")
    last_user = llm.calls[0]["messages"][-1]["content"]
    assert "recent_reviews" in last_user
    assert "жара выбила" in last_user
    assert "hr_drift_high" in last_user


def test_planned_workout_reaches_context(athlete_with_history, db_session):
    """Действующее назначение (for_date>=today) видно модели наутро."""
    state = assess_state(athlete_with_history.id, db=db_session)
    finalize(None, state, db=db_session, persist=True)  # Recommendation на сегодня
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=PLAIN_TURN)])
    orchestrator.handle_chat(athlete_with_history.id, "привет",
                             db=db_session, llm=llm)
    last_user = llm.calls[0]["messages"][-1]["content"]
    assert "planned_workout" in last_user


def test_weekly_sees_review_outcomes(athlete_with_history, db_session):
    """Недельный отчёт получает итоги разборов недели."""
    _finish_review(athlete_with_history.id, db_session, "колено стабильно")
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=PLAIN_TURN)])
    orchestrator.weekly_report(athlete_with_history.id, db=db_session, llm=llm)
    last_user = llm.calls[0]["messages"][-1]["content"]
    assert "recent_reviews" in last_user
    assert "колено стабильно" in last_user


def test_no_reviews_no_block(athlete_with_history, db_session):
    """Без завершённых разборов блок recent_reviews не инлайнится (нет шума)."""
    extras = orchestrator._build_extras(athlete_with_history.id, db=db_session)
    assert "recent_reviews (workout_insights)" not in extras
    assert "method_guides (search_guides)" not in extras  # без запроса — нет чанков


def test_review_extras_include_method_guides(athlete_with_history, db_session):
    """E3 (#242): разбор получает чанки методики по типу тренировки/боли."""
    from src.models import TrainingFeedback, TrainingSession
    sess = db_session.query(TrainingSession).filter_by(
        user_id=athlete_with_history.id).order_by(
        TrainingSession.begin_ts.desc()).first()
    db_session.add(TrainingFeedback(session_id=sess.id,
                                    user_id=athlete_with_history.id,
                                    rating=5, pain_level=2, pain_location="knee"))
    db_session.commit()
    extras = orchestrator._build_extras(athlete_with_history.id, db=db_session,
                                        session_id=sess.id)
    chunks = extras["method_guides (search_guides)"]
    assert 1 <= len(chunks) <= 2
    assert all({"guide", "heading", "text"} <= set(c) for c in chunks)
    # боль в фидбеке → чанк про колено в выдаче (pain → knee guide chunk)
    assert any("knee" in c["guide"] or "колен" in c["text"].lower() for c in chunks)


def test_weekly_extras_include_method_guides(athlete_with_history, db_session):
    """E3: недельный отчёт получает чанки про объём/прогрессию."""
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=PLAIN_TURN)])
    orchestrator.weekly_report(athlete_with_history.id, db=db_session, llm=llm)
    last_user = llm.calls[0]["messages"][-1]["content"]
    assert "method_guides" in last_user


def test_planned_workouts_list_all_days_with_days_ahead(athlete_with_history,
                                                        db_session):
    """Назначения на сегодня И на будущий день — оба в контексте, с days_ahead
    (инцидент 29.08: одиночный planned_workout затенял один из планов)."""
    from src.coach.contracts import WorkoutProposal

    state = assess_state(athlete_with_history.id, db=db_session)
    finalize(None, state, db=db_session, persist=True)   # rest на сегодня
    finalize(WorkoutProposal(workout_type="long", target_zone=2, duration_min=60,
                             for_days_ahead=2),
             state, db=db_session, persist=True)          # длительная на +2
    extras = orchestrator._build_extras(athlete_with_history.id, db=db_session)
    planned = extras["planned_workouts (recommendations)"]
    assert [p["days_ahead"] for p in planned] == [0, 2]
    assert planned[1]["type"] == "long"
    from datetime import date, timedelta
    from src.utils.timeutils import WEEKDAYS_RU
    assert planned[1]["weekday"] == WEEKDAYS_RU[
        (date.today() + timedelta(days=2)).weekday()]


# --- Датировка прошлых разборов по ТРЕНИРОВКЕ (инцидент 17.09.2026) ---------------
# (Dating recent_reviews by the workout, not by the insight row)

REVIEW_TURN = {"message": "Разбор: легло ровно.", "proposal": None,
               "followup_question": None, "log_suggestion": None,
               "assessment": {"effort_match": "ok", "causes": [], "flags": [],
                              "carry_forward": "продолжаем в том же духе"}}


def _extract_block(content: str, key: str):
    """Достать JSON-блок extras из последнего user-сообщения (build_today_block:
    строка «<key>:», следом одна строка json.dumps). (Pull one extras block as JSON.)"""
    import json
    lines = content.split("\n")
    idx = lines.index(f"{key}:")
    return json.loads(lines[idx + 1])


def _session_two_days_ago(user, db):
    """Тренировка ровно 2 локальных дня назад в полдень пояса пользователя — устойчиво к
    окну вокруг полуночи UTC/МСК. (Noon in the user's zone, two local days back.)"""
    from datetime import datetime, time, timedelta, timezone
    from zoneinfo import ZoneInfo
    from src.utils.timeutils import user_now
    from tests.helpers import build_training_session

    tz = ZoneInfo(user.timezone)
    local_date = user_now(user).date() - timedelta(days=2)
    begin_local = datetime.combine(local_date, time(12, 0), tzinfo=tz)
    sess = build_training_session(db, user.id, training_type="easy",
                                  begin_ts=begin_local.astimezone(timezone.utc))
    return sess, local_date


def _finish_old_review(user, db):
    """Завершить разбор тренировки двухдневной давности СЕЙЧАС (created_at = now):
    именно этот случай путал датировку до фикса. (Review row created now for an older run.)"""
    sess, local_date = _session_two_days_ago(user, db)
    InsightRepository.upsert(user.id, sess.id, db=db)
    InsightRepository.finish(sess.id, db=db, source="llm", effort_match="ok",
                             assessment={"flags": ["downhill_load_high"]},
                             carry_forward="спуски на маршруте — держим лёгкие дни")
    return sess, local_date


def test_recent_reviews_dated_by_session_not_by_insight_row(athlete_with_history,
                                                            db_session):
    """Регресс 17.09.2026: запись recent_reviews датируется ТРЕНИРОВКОЙ (days_ago=2,
    date/weekday её локальной даты), а не строкой разбора, созданной сегодня (days_ago=0)."""
    from src.utils.timeutils import WEEKDAYS_RU, session_local_dt

    user = athlete_with_history
    sess, local_date = _finish_old_review(user, db_session)
    # Перечитываем сессию из БД — так, как её увидит build_extras (as build_extras sees it)
    stored = db_session.get(TrainingSession, sess.id)
    assert session_local_dt(stored.begin_ts, stored, user).date() == local_date

    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=PLAIN_TURN)])
    orchestrator.handle_chat(user.id, "что сегодня делать?",
                             db=db_session, llm=llm, kind="morning")
    last_user = llm.calls[0]["messages"][-1]["content"]
    reviews = _extract_block(last_user, "recent_reviews (workout_insights)")
    rec = next(r for r in reviews if r["session_id"] == sess.id)

    assert rec["days_ago"] == 2, rec          # не 0 — разбор создан сегодня, тренировка нет
    assert rec["date"] == local_date.isoformat()
    assert rec["weekday"] == WEEKDAYS_RU[local_date.weekday()]
    # Прежние поля записи сохранены (legacy fields intact)
    assert rec["effort_match"] == "ok"
    assert rec["flags"] == ["downhill_load_high"]
    assert "спуски на маршруте" in rec["carry_forward"]


def test_review_context_recent_reviews_have_weekday(athlete_with_history, db_session):
    """Путь разбора (on_workout_completed): прошлый разбор попадает в контекст с непустыми
    weekday/date, а REVIEW_PROMPT велит датировать ПРЕЖНИЕ тренировки по этим полям."""
    from src.utils.timeutils import WEEKDAYS_RU

    user = athlete_with_history
    old_sess, local_date = _finish_old_review(user, db_session)
    # Самая свежая тренировка фикстуры (days_ago 0) — её и разбираем (freshest run)
    latest = db_session.query(TrainingSession).filter_by(user_id=user.id).order_by(
        TrainingSession.begin_ts.desc()).first()
    assert latest.id != old_sess.id
    InsightRepository.upsert(user.id, latest.id, db=db_session)

    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=REVIEW_TURN)])
    orchestrator.on_workout_completed(user.id, latest.id, db=db_session, llm=llm)

    assert len(llm.calls) == 1
    last_user = llm.calls[0]["messages"][-1]["content"]
    reviews = _extract_block(last_user, "recent_reviews (workout_insights)")
    rec = next(r for r in reviews if r["session_id"] == old_sess.id)
    assert rec["weekday"] in WEEKDAYS_RU
    assert rec["weekday"] == WEEKDAYS_RU[local_date.weekday()]
    assert rec["date"] == local_date.isoformat()
    # Сегодняшняя тренировка ещё не разобрана → в recent_reviews её нет (only past reviews)
    assert all(r["session_id"] != latest.id for r in reviews)
    # Правило датировки из REVIEW_PROMPT дошло до модели (prompt rule reached the model)
    assert "ПРЕЖНИХ тренировок" in last_user
    assert "weekday/days_ago" in last_user
