# Тесты numeric-checker'а (#247): проза не противоречит карточке (v1 — детект)
from src.coach.contracts import SafetyVerdict, Prescription
from src.coach.numeric_check import check_prose


def _prescription(**kw) -> Prescription:
    base = dict(safety=SafetyVerdict(allow_training=True),
                workout_type="easy",
                target={"max_zone": 2},
                volume={"duration_min": 40.0, "distance_km": 6.0},
                predicted={"pace_min_km": 6.5, "expected_hr": 138})
    base.update(kw)
    return Prescription(**base)


def test_matching_numbers_pass():
    p = _prescription()
    msg = ("Сегодня лёгкие 40 мин, примерно 6 км в Z2, темп около 6:30/км, "
           "пульс держим до 141 уд/мин.")
    assert check_prose(msg, p, max_hr=177) == []   # 141 = потолок Z2 при 177


def test_mismatched_numbers_detected():
    p = _prescription()
    msg = "Пробеги 12 км за 90 мин в Z4, темп 4:30/км, пульс 175 уд/мин."
    found = check_prose(msg, p, max_hr=177)
    assert len(found) == 5                          # км, мин, темп, пульс, зона
    assert any("км" in f for f in found)
    assert any("зона" in f for f in found)


def test_tolerances_absorb_rounding():
    p = _prescription()
    # «около 7 км», «45 минут» — в пределах допусков (±1 км, ±5 мин)
    assert check_prose("около 7 км за 45 мин", p, max_hr=177) == []


def test_no_card_or_empty_prose_is_silent():
    assert check_prose("любые 99 км", None, max_hr=177) == []
    assert check_prose("", _prescription(), max_hr=177) == []


def test_rest_without_expected_numbers_not_spammy():
    """Нет эталона данного рода (rest без объёмов) → числа не флагуются
    (честного сравнения нет — не спамим ложным)."""
    p = _prescription(workout_type="rest", target={}, volume={}, predicted={})
    assert check_prose("отдохни, вчера было 10 км", p, max_hr=177) == []


def test_e2e_mismatch_recorded_in_meta(athlete_with_history, db_session):
    """Проза с чужими числами при карточке → meta.numeric_mismatch у строки."""
    from src.coach import orchestrator
    from src.coach.llm.client import LLMResponse
    from src.models import CoachMessage
    from tests.coach.fakes import ScriptedLLM

    turn = {"message": "Сегодня будет 25 км в Z5 — держись!",
            "proposal": {"workout_type": "easy", "target_zone": 2,
                         "duration_min": 40, "distance_km": 6.0,
                         "structure": None, "rationale": []},
            "followup_question": None, "log_suggestion": None}
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=turn)])
    orchestrator.handle_chat(athlete_with_history.id, "что сегодня?",
                             db=db_session, llm=llm)
    msg = db_session.query(CoachMessage).filter_by(
        user_id=athlete_with_history.id, role="assistant").order_by(
        CoachMessage.id.desc()).first()
    mismatches = msg.meta_json.get("numeric_mismatch")
    assert mismatches and any("25" in m for m in mismatches)
    # текст пользователю НЕ изменён (v1 — только детект)
    assert "25 км" in msg.text
