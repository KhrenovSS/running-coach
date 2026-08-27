# Тесты прогноза темпа/дистанции в назначении (data-driven volume estimate) — 26.08.2026
#
# finalize() заполняет Prescription.predicted из baseline HR↔темп; рендер показывает
# ориентир вместо догадки LLM. (finalize fills predicted; render shows the estimate.)

import src.services.workout_insights as wi
from src.coach import orchestrator
from src.coach.contracts import WorkoutProposal
from src.coach.llm.client import LLMResponse
from src.coach.prescriber import finalize
from src.coach.state import assess_state
from src.models import Recommendation
from tests.coach.fakes import ScriptedLLM

# Эмпирическая оценка: на потолке Z2 (141 при max_hr=177) темп 6.12 мин/км;
# 40 мин → ≈6.5 км. (Empirical estimate stub for the coach flow tests.)
_ESTIMATE = {"pace_min_km": 6.12, "n_points": 20}


def test_finalize_fills_predicted_and_persists(athlete_with_history, db_session,
                                               monkeypatch):
    monkeypatch.setattr(wi, "expected_pace_at_hr",
                        lambda uid, hr, *, db: dict(_ESTIMATE))
    state = assess_state(athlete_with_history.id, db=db_session)
    p = finalize(WorkoutProposal(workout_type="easy", target_zone=2,
                                 duration_min=40), state,
                 db=db_session, persist=True, source="llm")
    assert p.predicted["hr_ceiling"] == 141
    assert p.predicted["pace_min_km"] == 6.12
    assert abs(p.predicted["distance_km"] - 6.5) < 0.06
    assert p.predicted["based_on"]["n_points"] == 20
    rec = db_session.query(Recommendation).filter_by(
        user_id=athlete_with_history.id).order_by(Recommendation.id.desc()).first()
    assert rec.predicted_json == p.predicted   # прогноз персистится (задел #246)


def test_finalize_without_estimate_predicted_empty(athlete_with_history, db_session,
                                                   monkeypatch):
    """Нет данных для оценки → predicted пуст, назначение собирается как раньше."""
    monkeypatch.setattr(wi, "expected_pace_at_hr", lambda uid, hr, *, db: None)
    state = assess_state(athlete_with_history.id, db=db_session)
    p = finalize(WorkoutProposal(workout_type="easy", target_zone=2,
                                 duration_min=40, distance_km=5.5), state,
                 db=db_session)
    assert p.predicted == {}


def test_chat_reply_contains_estimate_line(athlete_with_history, db_session,
                                           monkeypatch):
    """Полный контур: ход LLM → карточка со строкой «Ориентир…», км LLM скрыт."""
    monkeypatch.setattr(wi, "expected_pace_at_hr",
                        lambda uid, hr, *, db: dict(_ESTIMATE))
    turn = {"message": "Сегодня легко.", "followup_question": None,
            "log_suggestion": None,
            "proposal": {"workout_type": "easy", "target_zone": 2,
                         "duration_min": 40, "distance_km": 5.5,
                         "structure": None, "rationale": ["восстановление"]}}
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=turn)])
    reply = orchestrator.handle_chat(athlete_with_history.id, "что сегодня?",
                                     db=db_session, llm=llm)
    assert "Ориентир по твоим пробежкам: ~6:07/км → ≈6.5 км" in reply.text
    assert "~5.5 км" not in reply.text


# --- Pace-режим: прогноз пульса на целевом темпе (pace-lead predicted) ---

_HR_ESTIMATE = {"hr_bpm": 138, "n_points": 8}  # ниже потолка Z2 (141) — clamp не вмешивается


def test_finalize_pace_mode_fills_expected_hr(athlete_with_history, db_session,
                                              monkeypatch):
    """Pace-режим: predicted = ожидаемый пульс; дистанция детерминирована в clamp."""
    monkeypatch.setattr(wi, "expected_hr_at_pace",
                        lambda uid, pace, *, db: dict(_HR_ESTIMATE))
    state = assess_state(athlete_with_history.id, db=db_session)
    p = finalize(WorkoutProposal(workout_type="easy", target_zone=2,
                                 duration_min=40, distance_km=99.0,
                                 target_pace_min_km=6.5), state,
                 db=db_session, persist=True, source="llm")
    assert p.target["pace_min_km"] == 6.5
    assert p.volume["distance_km"] == round(40 / 6.5, 1)   # не 99.0 от LLM
    assert p.predicted["expected_hr"] == 138
    assert p.predicted["pace_min_km"] == 6.5
    assert p.predicted["based_on"]["n_points"] == 8
    rec = db_session.query(Recommendation).filter_by(
        user_id=athlete_with_history.id).order_by(Recommendation.id.desc()).first()
    assert rec.target_json["pace_min_km"] == 6.5           # темп персистится
    assert rec.predicted_json == p.predicted


def test_finalize_pace_mode_without_estimate(athlete_with_history, db_session,
                                             monkeypatch):
    """Мало данных для пульса → predicted пуст, темп-цель остаётся."""
    monkeypatch.setattr(wi, "expected_hr_at_pace", lambda uid, pace, *, db: None)
    state = assess_state(athlete_with_history.id, db=db_session)
    p = finalize(WorkoutProposal(workout_type="easy", target_zone=2,
                                 duration_min=40, target_pace_min_km=6.5), state,
                 db=db_session)
    assert p.target["pace_min_km"] == 6.5
    assert p.predicted == {}


def test_chat_reply_pace_lead_card(athlete_with_history, db_session, monkeypatch):
    """Полный контур: LLM ведёт по темпу → карточка «Темп …», «не смотрим»."""
    monkeypatch.setattr(wi, "expected_hr_at_pace",
                        lambda uid, pace, *, db: dict(_HR_ESTIMATE))
    turn = {"message": "Поведём по темпу.", "followup_question": None,
            "log_suggestion": None,
            "proposal": {"workout_type": "easy", "target_zone": 2,
                         "duration_min": 40, "distance_km": None,
                         "target_pace_min_km": 6.5,
                         "structure": None, "rationale": ["просьба подопечного"]}}
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=turn)])
    reply = orchestrator.handle_chat(athlete_with_history.id, "дай тренировку по темпу",
                                     db=db_session, llm=llm)
    assert "Темп 6:30/км" in reply.text
    assert "на пульс сегодня не смотрим" in reply.text
    assert "~138 уд/мин" in reply.text
