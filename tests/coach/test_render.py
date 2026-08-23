# Тесты детерминированного рендера (Deterministic render tests) — DEV_PLAN §10
from src.coach.contracts import AthleteState, WorkoutProposal
from src.coach.rules.p1_safety import evaluate_safety
from src.coach.render import render_prescription, render_state_card
from src.coach.safety import clamp
from tests.coach.test_safety_clamp import AGGRESSIVE, _state


def test_render_numbers_match_prescription():
    """Числа карточки — из полей Prescription, не из прозы (numbers from fields)."""
    state = _state()
    verdict = evaluate_safety(state)
    p, _ = clamp(WorkoutProposal(workout_type="easy", target_zone=2,
                                 duration_min=45, distance_km=7.5), verdict, state)
    text = render_prescription(p)
    assert "Лёгкий бег" in text
    assert "Z2" in text
    assert "45 мин" in text
    assert "7.5 км" in text
    assert "Ограничение по безопасности" not in text  # не урезано — блока нет


def test_render_clamped_has_safety_block():
    """При clamped=True в карточке есть фиксированный не-LLM-блок ограничения."""
    state = _state(hrv_status="very_low")
    verdict = evaluate_safety(state)
    p, clamped = clamp(AGGRESSIVE, verdict, state)
    assert clamped
    text = render_prescription(p)
    assert "⚠️ *Ограничение по безопасности:*" in text
    assert "Интервалы" not in text  # агрессивный тип не просочился в карточку


def test_render_rest_has_no_volume():
    state = _state(pain_level=7)
    verdict = evaluate_safety(state)
    p, _ = clamp(AGGRESSIVE, verdict, state)
    text = render_prescription(p)
    assert "Отдых" in text
    assert "км" not in text and "мин" not in text.replace("Ограничение", "")


def test_render_state_card_low_confidence_warns():
    state = AthleteState(user_id=1, data_confidence=0.2)
    text = render_state_card(state)
    assert "Данных мало" in text
