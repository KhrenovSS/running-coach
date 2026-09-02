# Тесты оркестратора с фейковыми LLM (Orchestrator tests) — DEV_PLAN §10
from src.coach import orchestrator
from src.coach.llm.client import LLMResponse
from src.models import CoachMessage, Recommendation
from tests.coach.fakes import FailingLLM, ScriptedLLM

TURN_WITH_PROPOSAL = {
    "message": "Предлагаю сегодня интервалы — форма отличная!",
    "proposal": {"workout_type": "interval", "target_zone": 5,
                 "duration_min": 60, "distance_km": 10.0,
                 "structure": "10×400/400", "rationale": ["форма хорошая"]},
    "followup_question": "Как колено после вчерашнего?",
    "log_suggestion": None,
}


def test_failing_llm_falls_back_deterministically(athlete_with_history, db_session):
    """LLM падает → детерминированный текст, исключение не всплывает, диалог записан."""
    llm = FailingLLM()
    reply = orchestrator.handle_chat(athlete_with_history.id, "привет",
                                     db=db_session, llm=llm)
    assert reply.source == "fallback"
    assert "состояние" in reply.text.lower()
    msgs = db_session.query(CoachMessage).filter_by(
        user_id=athlete_with_history.id).all()
    assert {m.role for m in msgs} >= {"user", "assistant"}


def test_llm_proposal_goes_through_clamp(athlete_with_history, db_session):
    """Предложение LLM проходит clamp: часы восстановления → интервалы не сегодня.

    Фикстура: последняя тренировка недавно → recovery_hours_left > 0 →
    earliest_next_hard → hard-тип даунгрейдится. Recommendation записана с source=llm.
    """
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=TURN_WITH_PROPOSAL)])
    reply = orchestrator.handle_chat(athlete_with_history.id, "что сегодня?",
                                     db=db_session, llm=llm)
    assert reply.source == "llm"
    assert "Интервалы" not in reply.text          # карточка урезана — не интервалы
    assert "Ограничение по безопасности" in reply.text
    assert "Как колено" in reply.text             # followup дошёл

    rec = db_session.query(Recommendation).filter_by(
        user_id=athlete_with_history.id).order_by(Recommendation.id.desc()).first()
    assert rec.workout_type != "interval"

    # Учёт диалога: обе строки записаны, у assistant есть usage-мета
    msg = db_session.query(CoachMessage).filter_by(
        user_id=athlete_with_history.id, role="assistant").order_by(
        CoachMessage.id.desc()).first()
    assert msg.kind == "chat"


def test_today_block_has_local_now_and_no_utc_leak(athlete_with_history, db_session):
    """Инцидент 28.08: LLM назвал вечернюю тренировку «утренней» — времени в промпте
    не было. Теперь: «Сейчас:» с локальным временем и поясом, started_at_local у
    тренировок, earliest_next_hard без голого UTC (+00:00).
    """
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn",
                                   parsed={"message": "ок", "proposal": None,
                                           "followup_question": None,
                                           "log_suggestion": None})])
    orchestrator.handle_chat(athlete_with_history.id, "как дела?",
                             db=db_session, llm=llm)
    content = llm.calls[0]["messages"][-1]["content"]
    assert "Сейчас: " in content
    assert "(Europe/Moscow)" in content        # make_user: timezone Moscow
    assert "started_at_local" in content
    assert "+00:00" not in content             # earliest_next_hard — локальное время
    # День недели — готовым словом сразу после «Сейчас: » (weekday spelled out)
    from src.utils.timeutils import WEEKDAYS_RU
    now_part = content.split("Сейчас: ", 1)[1]
    assert any(now_part.startswith(d) for d in WEEKDAYS_RU)
    assert '"weekday"' in content              # поле у тренировок


def test_budget_exhausted_no_llm_call(athlete_with_history, db_session):
    """Бюджет исчерпан → вежливый отказ БЕЗ вызова LLM (len(calls)==0)."""
    from src.coach.llm.config import COACH_MAX_TURNS_PER_DAY
    from src.services.repositories_coach import CoachRepository
    for _ in range(COACH_MAX_TURNS_PER_DAY):
        CoachRepository.save_message(athlete_with_history.id, "assistant", "x",
                                     db=db_session)
    llm = ScriptedLLM([])
    reply = orchestrator.handle_chat(athlete_with_history.id, "ещё вопрос",
                                     db=db_session, llm=llm)
    assert "лимит" in reply.text.lower()
    assert len(llm.calls) == 0


EASY_TURN = {
    "message": "Сегодня лёгкий бег — восстанавливаемся.",
    "proposal": {"workout_type": "easy", "target_zone": 2,
                 "duration_min": 40, "distance_km": 5.5,
                 "structure": None, "rationale": ["восстановление"]},
    "followup_question": None,
    "log_suggestion": None,
}


def test_chat_unchanged_proposal_renders_reminder_not_card(athlete_with_history,
                                                           db_session):
    """Инцидент 26.08: повтор того же proposal в чате дублировал карточку и
    плодил строки recommendations. Теперь — строка-напоминание без новой записи."""
    resp = LLMResponse(stop_reason="end_turn", parsed=EASY_TURN)
    llm = ScriptedLLM([resp, resp])
    uid = athlete_with_history.id

    first = orchestrator.handle_chat(uid, "что сегодня?", db=db_session, llm=llm)
    assert "Лёгкий бег" in first.text
    n_recs = db_session.query(Recommendation).filter_by(user_id=uid).count()
    assert n_recs >= 1

    second = orchestrator.handle_chat(uid, "какой пульс допустим?",
                                      db=db_session, llm=llm)
    assert "План на сегодня без изменений" in second.text
    assert "пульс до 151" in second.text          # F4: lthr=170 → потолок Z2 = 151
    assert "и ниже" not in second.text            # полная карточка не повторяется
    assert db_session.query(Recommendation).filter_by(
        user_id=uid).count() == n_recs            # дубль-записи нет


def test_chat_changed_proposal_gets_full_card(athlete_with_history, db_session):
    """Изменённое назначение → полная карточка и новая запись recommendations."""
    changed = dict(EASY_TURN)
    changed["proposal"] = dict(EASY_TURN["proposal"], duration_min=30,
                               distance_km=4.0)
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=EASY_TURN),
                       LLMResponse(stop_reason="end_turn", parsed=changed)])
    uid = athlete_with_history.id

    orchestrator.handle_chat(uid, "что сегодня?", db=db_session, llm=llm)
    n_recs = db_session.query(Recommendation).filter_by(user_id=uid).count()
    second = orchestrator.handle_chat(uid, "давай покороче",
                                      db=db_session, llm=llm)
    assert "30 мин" in second.text
    assert "План на сегодня без изменений" not in second.text
    assert db_session.query(Recommendation).filter_by(
        user_id=uid).count() == n_recs + 1


def test_morning_kind_not_deduped(athlete_with_history, db_session):
    """Дедуп — только для kind=chat: утренний вердикт всегда с полной карточкой."""
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=EASY_TURN),
                       LLMResponse(stop_reason="end_turn", parsed=EASY_TURN)])
    uid = athlete_with_history.id

    orchestrator.handle_chat(uid, "что сегодня?", db=db_session, llm=llm)
    n_recs = db_session.query(Recommendation).filter_by(user_id=uid).count()
    morning = orchestrator.handle_chat(uid, "утренний вердикт", db=db_session,
                                       llm=llm, kind="morning")
    assert "Лёгкий бег" in morning.text
    assert "План на сегодня без изменений" not in morning.text
    assert db_session.query(Recommendation).filter_by(
        user_id=uid).count() == n_recs + 1


def test_llm_card_contains_bpm_ceiling(athlete_with_history, db_session):
    """Карточка LLM-хода содержит потолок пульса зоны в уд/мин (инцидент 26.08)."""
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=EASY_TURN)])
    reply = orchestrator.handle_chat(athlete_with_history.id, "что сегодня?",
                                     db=db_session, llm=llm)
    assert "пульс до 151 уд/мин" in reply.text    # F4: lthr=170, Z2 → 151


def test_log_suggestion_passthrough(athlete_with_history, db_session):
    """log_suggestion от LLM доезжает до ChatReply (кнопку строит хендлер)."""
    turn = {"message": "Понял, колено потягивало.", "proposal": None,
            "followup_question": None,
            "log_suggestion": {"kind": "pain", "value": 2}}
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=turn)])
    reply = orchestrator.handle_chat(athlete_with_history.id,
                                     "колено потягивало первые 2 км",
                                     db=db_session, llm=llm)
    assert reply.log_suggestion is not None
    assert reply.log_suggestion.value == 2


def test_future_day_proposal_dated_card_and_dedup(athlete_with_history, db_session):
    """Инцидент 29.08: воскресный план подписывался «на сегодня».

    for_days_ahead=2 → Recommendation.for_date = сегодня+2, карточка с днём недели
    и «Предварительно»; повтор → напоминание с днём, без новой записи; назначения
    на разные дни не матчатся дедупом.
    """
    from datetime import date, timedelta

    from src.coach.render import _WEEKDAYS_RU

    sunday_turn = dict(EASY_TURN)
    sunday_turn["proposal"] = dict(EASY_TURN["proposal"], workout_type="long",
                                   duration_min=60, distance_km=None,
                                   for_days_ahead=2)
    resp = LLMResponse(stop_reason="end_turn", parsed=sunday_turn)
    llm = ScriptedLLM([resp, resp,
                       LLMResponse(stop_reason="end_turn", parsed=EASY_TURN)])
    uid = athlete_with_history.id
    target = date.today() + timedelta(days=2)
    day_name = _WEEKDAYS_RU[target.weekday()]

    first = orchestrator.handle_chat(uid, "давай длительную через два дня",
                                     db=db_session, llm=llm)
    assert f"Длительный бег — {day_name} {target:%d.%m}" in first.text
    assert "Предварительно — утром сверимся по состоянию." in first.text
    assert "План на сегодня" not in first.text
    rec = db_session.query(Recommendation).filter_by(
        user_id=uid).order_by(Recommendation.id.desc()).first()
    assert rec.for_date == target
    n_recs = db_session.query(Recommendation).filter_by(user_id=uid).count()

    second = orchestrator.handle_chat(uid, "какой пульс на длительной?",
                                      db=db_session, llm=llm)
    assert f"План на {day_name} ({target:%d.%m}) без изменений" in second.text
    assert db_session.query(Recommendation).filter_by(
        user_id=uid).count() == n_recs                # дубль-записи нет

    # Сегодняшний easy НЕ матчится с будущей строкой — полная карточка + запись
    third = orchestrator.handle_chat(uid, "а что сегодня?",
                                     db=db_session, llm=llm)
    assert "без изменений" not in third.text
    assert db_session.query(Recommendation).filter_by(
        user_id=uid).count() == n_recs + 1


def test_turns_today_ignores_fallback(athlete_with_history, db_session):
    """Регрессия #251: fallback-карточки не тратят LLM-бюджет — бэкфилл из 40
    детерминированных разборов не блокирует чат/утро."""
    from src.coach.llm.config import COACH_MAX_TURNS_PER_DAY
    from src.services.repositories_coach import CoachRepository

    uid = athlete_with_history.id
    for _ in range(COACH_MAX_TURNS_PER_DAY):
        CoachRepository.save_message(uid, "assistant", "карточка", db=db_session,
                                     kind="review", meta={"fallback": True})
    assert CoachRepository.turns_today(uid, db=db_session) == 0

    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=EASY_TURN)])
    reply = orchestrator.handle_chat(uid, "что сегодня?", db=db_session, llm=llm)
    assert reply.source == "llm"                    # бюджет не съеден fallback'ами
    assert CoachRepository.turns_today(uid, db=db_session) == 1


def test_history_filters_kinds_and_uses_prose(athlete_with_history, db_session):
    """Регрессия #258: weekly/plan-простыни не попадают в окно истории; вместо
    составного текста (проза+карточка) модель видит meta.prose; синтетический
    user-промпт заменён меткой."""
    from src.coach.turn_context import history
    from src.services.repositories_coach import CoachRepository

    uid = athlete_with_history.id
    CoachRepository.save_message(uid, "user", "привет", db=db_session, kind="chat")
    CoachRepository.save_message(uid, "assistant",
                                 "проза\n\n🟢 Лёгкий бег · 40 мин",
                                 db=db_session, kind="chat",
                                 meta={"prose": "проза"})
    CoachRepository.save_message(uid, "user", "Составь план недели...",
                                 db=db_session, kind="plan")
    CoachRepository.save_message(uid, "assistant", "План на неделю (01.09–07.09)",
                                 db=db_session, kind="plan")
    CoachRepository.save_message(uid, "user", "Утренний вердикт: что мне делать...",
                                 db=db_session, kind="morning")
    CoachRepository.save_message(uid, "assistant", "вердикт-проза\n\nкарточка",
                                 db=db_session, kind="morning",
                                 meta={"fallback": True})

    h = history(uid, db=db_session)
    contents = [m["content"] for m in h]
    assert not any("План на неделю" in c for c in contents)     # kind='plan' — вон
    assert "проза" in contents                                  # prose вместо текста
    assert "[утренний вердикт]" in contents                     # метка вместо промпта
    # fallback-строка без prose деградирует на полный текст — без исключений
    assert any("вердикт-проза" in c for c in contents)


def test_show_week_plan_flag_appends_stored_card(athlete_with_history, db_session):
    """show_week_plan=true → к прозе добавляется карточка СОХРАНЁННОГО плана недели;
    новых строк recommendations нет, LLM ничего не составляла (инцидент 02.09.2026)."""
    from datetime import timedelta

    from src.utils.timeutils import user_now

    uid = athlete_with_history.id
    today = user_now(athlete_with_history).date()
    sunday = today - timedelta(days=today.weekday()) + timedelta(days=6)
    db_session.add(Recommendation(user_id=uid, for_date=sunday, workout_type="long",
                                  target_json={"max_zone": 2},
                                  volume_json={"duration_min": 80.0, "distance_km": 9.0},
                                  status="proposed", source="llm", clamped=False))
    db_session.commit()
    before = db_session.query(Recommendation).filter_by(user_id=uid).count()

    turn = {"message": "Неделя спокойная, воскресенье — с компанией.", "proposal": None,
            "followup_question": None, "log_suggestion": None, "show_week_plan": True}
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=turn)])
    reply = orchestrator.handle_chat(uid, "какой план на неделю?", db=db_session, llm=llm)

    assert reply.source == "llm"
    assert "План на неделю" in reply.text
    assert "80 мин" in reply.text and "≈9.0 км" in reply.text
    assert db_session.query(Recommendation).filter_by(user_id=uid).count() == before


def test_unchanged_today_ignores_superseded(athlete_with_history, db_session):
    """Дедуп назначения не сравнивает с погашенной строкой (иначе карточка глушится)."""
    from src.coach.contracts import WorkoutProposal
    from src.coach.rules.p1_safety import evaluate_safety
    from src.coach.safety import clamp
    from src.coach.state import assess_state
    from src.coach.turn_context import unchanged_today
    from src.utils.timeutils import user_now

    uid = athlete_with_history.id
    state = assess_state(uid, db=db_session)
    p, _ = clamp(WorkoutProposal(workout_type="easy", target_zone=2, duration_min=40),
                 evaluate_safety(state), state)
    p.when = user_now(athlete_with_history).date()
    db_session.add(Recommendation(user_id=uid, for_date=p.when, workout_type="easy",
                                  target_json=dict(p.target), volume_json=dict(p.volume),
                                  status="superseded", source="llm"))
    db_session.commit()
    assert unchanged_today(p, uid, db=db_session) is False
