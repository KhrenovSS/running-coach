# Тесты детерминированного рендера (Deterministic render tests) — DEV_PLAN §10
from src.coach.contracts import AthleteState, WorkoutProposal
from src.coach.rules.p1_safety import evaluate_safety
from src.coach.render import (
    render_prescription,
    render_prescription_short,
    render_state_card,
)
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


def test_render_prescription_with_max_hr_shows_bpm_ceiling():
    """Инцидент 26.08: карточка не содержала цифр пульса — «точный потолок
    увидишь в карточке» вёл в никуда. С max_hr потолок зоны в уд/мин обязателен."""
    state = _state()
    verdict = evaluate_safety(state)
    p, _ = clamp(WorkoutProposal(workout_type="easy", target_zone=2,
                                 duration_min=40, distance_km=5.5), verdict, state)
    text = render_prescription(p, max_hr=177)
    assert "пульс до 141 уд/мин" in text   # 177·0.80 = 141.6 → floor
    # без max_hr — прежний формат, строки пульса нет (backward-compatible)
    assert "пульс" not in render_prescription(p)


def test_render_prescription_z5_no_bpm_line():
    """Z5 — потолка в уд/мин нет: строка пульса не рендерится."""
    state = _state()
    verdict = evaluate_safety(state)
    p, _ = clamp(WorkoutProposal(workout_type="easy", target_zone=2), verdict, state)
    p.target["max_zone"] = 5
    assert "пульс" not in render_prescription(p, max_hr=177)


def test_render_prescription_short_reminder_line():
    """Короткое напоминание (решение владельца 26.08): тип · пульс до N · мин."""
    state = _state()
    verdict = evaluate_safety(state)
    p, _ = clamp(WorkoutProposal(workout_type="easy", target_zone=2,
                                 duration_min=40, distance_km=5.5), verdict, state)
    text = render_prescription_short(p, max_hr=177)
    assert text.startswith("План на сегодня без изменений:")
    assert "🟢 Лёгкий бег · пульс до 141 · 40 мин" in text
    # без max_hr — вместо пульса зона
    assert "Z2 и ниже" in render_prescription_short(p)


def test_render_predicted_estimate_replaces_llm_distance():
    """Пожелание 26.08: дистанция — расчётный ориентир из данных, не догадка LLM.

    С predicted: строка «Ориентир…» с темпом, км от LLM скрыт; в напоминании — то же.
    """
    state = _state()
    verdict = evaluate_safety(state)
    p, _ = clamp(WorkoutProposal(workout_type="easy", target_zone=2,
                                 duration_min=40, distance_km=5.5), verdict, state)
    p.predicted = {"pace_min_km": 7.5, "distance_km": 5.3, "hr_ceiling": 141}
    text = render_prescription(p, max_hr=177)
    assert "Ориентир по твоим пробежкам: ~7:30/км → ≈5.3 км" in text
    assert "~5.5 км" not in text            # догадка LLM скрыта
    short = render_prescription_short(p, max_hr=177)
    assert "~7:30/км ≈ 5.3 км" in short


def test_render_no_predicted_keeps_llm_distance():
    """Без прогноза — прежний формат с `~N км` из proposal."""
    state = _state()
    verdict = evaluate_safety(state)
    p, _ = clamp(WorkoutProposal(workout_type="easy", target_zone=2,
                                 duration_min=40, distance_km=5.5), verdict, state)
    p.predicted = {}
    text = render_prescription(p, max_hr=177)
    assert "~5.5 км" in text
    assert "Ориентир" not in text


def test_render_prescription_short_rest():
    """Отдых в напоминании — без пульса и объёма."""
    state = _state(pain_level=7)
    verdict = evaluate_safety(state)
    p, _ = clamp(AGGRESSIVE, verdict, state)
    text = render_prescription_short(p, max_hr=177)
    assert "Отдых" in text
    assert "пульс" not in text and "мин" not in text


def test_render_state_card_low_confidence_warns():
    state = AthleteState(user_id=1, data_confidence=0.2)
    text = render_state_card(state)
    assert "Данных мало" in text


def test_render_no_unbalanced_markdown():
    """Инцидент 23.08: одиночный `_` (tired_rate) ломал legacy-Markdown Telegram.

    Вне backticks в карточках не должно быть `_`; `*` — парные.
    """
    import re

    from src.coach.contracts import SkillResult
    from src.coach.render import render_state_card

    state = AthleteState(user_id=1, data_confidence=0.9, skills={
        "fatigue": SkillResult(key="fatigue", status="warning", value=-26,
                               unit="tired_rate", confidence=0.8),
        "load": SkillResult(key="load", status="danger", value=1.68, unit="ratio"),
    })
    text = render_state_card(state)
    outside_code = re.sub(r"`[^`]*`", "", text)   # вырезать code-entities
    assert "_" not in outside_code, f"голый _ вне backticks: {outside_code!r}"
    assert outside_code.count("*") % 2 == 0, "непарные * в карточке"


def test_render_earliest_in_local_timezone(monkeypatch):
    """Инцидент 23.08: earliest показывался в UTC (17:59 вместо 20:59 мск)."""
    from datetime import datetime

    from src.config import settings

    monkeypatch.setattr(settings, "timezone", "Europe/Moscow")
    state = _state()
    state.recovery_hours_left = 1.0
    verdict = evaluate_safety(state, now=datetime(2026, 8, 23, 16, 59))
    p, _ = clamp(WorkoutProposal(workout_type="easy", target_zone=2), verdict, state,
                 now=datetime(2026, 8, 23, 16, 59))
    text = render_prescription(p)
    assert "20:59" in text     # 17:59 UTC → 20:59 MSK
    assert "17:59" not in text


def test_render_earliest_prefers_user_timezone(monkeypatch):
    """BACKLOG #260: пояс пользователя приоритетнее settings.timezone (user tz wins)."""
    from datetime import datetime
    from types import SimpleNamespace

    from src.config import settings

    monkeypatch.setattr(settings, "timezone", "Europe/Moscow")
    state = _state()
    state.recovery_hours_left = 1.0
    verdict = evaluate_safety(state, now=datetime(2026, 8, 23, 16, 59))
    p, _ = clamp(WorkoutProposal(workout_type="easy", target_zone=2), verdict, state,
                 now=datetime(2026, 8, 23, 16, 59))
    user = SimpleNamespace(timezone="Europe/Berlin")
    text = render_prescription(p, user=user)
    assert "19:59" in text     # 17:59 UTC → 19:59 Berlin (не 20:59 MSK)
    assert "20:59" not in text


# --- Pace-режим: цель — темп+время, пульс справочно (pace-lead cards) ---

def _pace_prescription(expected_hr: int | None = 166):
    """Заклэмпленное pace-назначение: темп 5.5 (5:30/км), 40 мин → ≈7.3 км."""
    state = _state()
    verdict = evaluate_safety(state)
    p, _ = clamp(WorkoutProposal(workout_type="tempo", target_zone=4,
                                 duration_min=40, target_pace_min_km=5.5),
                 verdict, state)
    if expected_hr is not None:
        p.predicted = {"expected_hr": expected_hr, "pace_min_km": 5.5,
                       "based_on": {"n_points": 8, "window_days": 120}}
    return p


def test_render_pace_lead_full_card():
    """Все параметры: цель — темп+время, дистанция расчётная, пульс справочно."""
    text = render_prescription(_pace_prescription(), max_hr=177)
    assert "Темп 5:30/км" in text
    assert "40 мин" in text
    assert "≈7.3 км" in text                       # 40 / 5.5
    assert "на пульс сегодня не смотрим" in text
    assert "~166 уд/мин" in text
    assert "ориентировочно" in text
    assert "пульс до" not in text                  # HR-цели в pace-режиме нет
    assert "и ниже" not in text                    # строки зоны нет


def test_render_pace_lead_no_hr_estimate():
    """Мало данных для прогноза пульса → пометка вместо цифры."""
    text = render_prescription(_pace_prescription(expected_hr=None), max_hr=177)
    assert "Темп 5:30/км" in text
    assert "мало данных" in text
    assert "уд/мин" not in text


def test_render_pace_lead_short():
    """Short-напоминание pace-режима: тип · темп · время · дистанция."""
    text = render_prescription_short(_pace_prescription(), max_hr=177)
    assert text.startswith("План на сегодня без изменений:")
    assert "темп 5:30/км" in text
    assert "40 мин" in text
    assert "≈7.3 км" in text
    assert "пульс до" not in text
