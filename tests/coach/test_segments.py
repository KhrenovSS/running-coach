# Тесты посегментных метрик тренировки (per-segment workout metrics) — M2.1.
# Числа проставляет детерминированный код; при нехватке данных — честная пометка.

from src.coach.contracts import (Prescription, RecoverySpec, SafetyVerdict,
                                 WorkoutSegment)
from src.coach.render import render_prescription
from src.coach.segments import (enrich_and_clamp_segments, segments_from_schema,
                                segments_from_target)


def _seg(**kw) -> WorkoutSegment:
    base = dict(role="steady", amount_kind="min", amount_value=30, target_zone=2)
    base.update(kw)
    return WorkoutSegment(**base)


def test_hr_ceiling_from_zone_and_pace_missing_without_data():
    """Зона → потолок пульса детерминированно; темпа нет и данных нет → pace_missing."""
    out = enrich_and_clamp_segments(
        [_seg(target_zone=2)], workout_type="easy", proposal_type="easy",
        max_zone=5, max_hr=180, user_id=1, db=None)
    assert len(out) == 1
    assert out[0]["hr_ceiling"] == 144        # floor(180*0.80)
    assert out[0]["pace_missing"] is True      # db=None → ориентир не посчитать
    assert out[0]["hr_missing"] is False


def test_zone_clamped_to_max_zone():
    """Зона сегмента не выше потолка safety (per-segment clamp)."""
    out = enrich_and_clamp_segments(
        [_seg(target_zone=5)], workout_type="tempo", proposal_type="tempo",
        max_zone=2, max_hr=180, user_id=1, db=None)
    assert out[0]["target_zone"] == 2
    assert out[0]["hr_ceiling"] == 144


def test_explicit_pace_sets_hr_missing_without_data():
    """Явный темп задан, пульс на нём предсказать нечем → hr_missing, темп сохранён."""
    out = enrich_and_clamp_segments(
        [_seg(target_zone=4, pace_target_min_km=5.0)], workout_type="interval",
        proposal_type="interval", max_zone=5, max_hr=180, user_id=1, db=None)
    assert out[0]["pace_target_min_km"] == 5.0
    assert out[0]["hr_missing"] is True
    assert out[0]["pace_missing"] is False


def test_type_downgrade_drops_segments():
    """Тип понижен по интенсивности → структура недостоверна, сегменты не показываем."""
    out = enrich_and_clamp_segments(
        [_seg(role="work", target_zone=5)], workout_type="easy",
        proposal_type="interval", max_zone=2, max_hr=180, user_id=1, db=None)
    assert out == []


def test_recovery_until_hr_from_zone():
    """recovery без until_hr, но с зоной → until_hr считается из зоны."""
    out = enrich_and_clamp_segments(
        [_seg(role="work", repeat=6, target_zone=4,
              recovery=RecoverySpec(target_zone=1))],
        workout_type="interval", proposal_type="interval",
        max_zone=5, max_hr=180, user_id=1, db=None)
    assert out[0]["recovery"]["until_hr"] == 125   # int(180*0.70), floor float-quirk


def test_pace_hint_and_hr_from_baseline(monkeypatch):
    """Есть данные истории → ориентир темпа проставлен, pace_missing=False."""
    import src.services.workout_insights as wi
    monkeypatch.setattr(wi, "expected_pace_at_hr",
                        lambda uid, hr, *, db: {"pace_min_km": 6.5, "n_points": 9})
    out = enrich_and_clamp_segments(
        [_seg(target_zone=2)], workout_type="easy", proposal_type="easy",
        max_zone=5, max_hr=180, user_id=1, db=object())
    assert out[0]["pace_hint_min_km"] == 6.5
    assert out[0]["pace_missing"] is False


def _owner_example_prescription():
    out = enrich_and_clamp_segments(
        [_seg(role="warmup", amount_kind="min", amount_value=25, target_zone=2),
         _seg(role="work", repeat=7, amount_kind="sec", amount_value=18,
              target_zone=4, effort="свободно — не на пределе",
              recovery=RecoverySpec(until_hr=130, duration_min=2)),
         _seg(role="cooldown", amount_kind="min", amount_value=5, target_zone=2)],
        workout_type="easy", proposal_type="easy", max_zone=5, max_hr=180,
        user_id=1, db=None)
    return Prescription(safety=SafetyVerdict(), workout_type="easy",
                        target={"max_zone": 4, "segments": out},
                        volume={"duration_min": 35})   # неверный «верхний» объём (35) не показываем


def test_render_segments_compact_and_clear():
    """Компактный формат: заголовок с итогом, понятные строки, без загромождения."""
    text = render_prescription(_owner_example_prescription(), max_hr=180)
    assert "*🟢 Лёгкий бег с ускорениями* · ~46 мин" in text   # итог из сегментов
    assert "Разминка: 25 мин · пульс ≤144 (Z2)" in text
    assert "Ускорения ×7: 18 сек · пульс ≤167 (Z4) · свободно — не на пределе" in text
    assert "отдых между: 2 мин трусцой или до пульса ≤130" in text
    assert "Заминка: 5 мин · пульс ≤144 (Z2)" in text
    # загромождающие/честные-но-шумные пометки убраны из компактного формата
    assert "мало данных" not in text


def test_render_segments_no_conflicting_summary():
    """Нет противоречивой верхней строки: ни «35 мин», ни оценки дистанции сверху."""
    text = render_prescription(_owner_example_prescription(), max_hr=180)
    assert "35 мин" not in text          # верхний объём предложения не показываем
    assert "Z4 и ниже" not in text        # старой сводной строки нет


def test_segments_total_min():
    """Итог = сумма сегментов: 25 + 7×0.3 + 7×2 + 5 ≈ 46 мин (deterministic total)."""
    from src.coach.render_segments import segments_total_min
    p = _owner_example_prescription()
    assert segments_total_min(p.target["segments"]) == 46


def test_render_legacy_structure_still_works():
    """Старая строковая structure (записи до M2.1) по-прежнему рендерится."""
    p = Prescription(safety=SafetyVerdict(), workout_type="interval",
                     target={"max_zone": 5, "structure": "10×400/400"},
                     volume={"duration_min": 40})
    text = render_prescription(p, max_hr=180)
    assert "10×400/400" in text


def test_segments_roundtrip_target():
    """target-dicts → WorkoutSegment и обратно читаемо (persist round-trip)."""
    out = enrich_and_clamp_segments(
        [_seg(role="work", repeat=4, target_zone=4,
              recovery=RecoverySpec(until_hr=130))],
        workout_type="interval", proposal_type="interval",
        max_zone=5, max_hr=180, user_id=1, db=None)
    restored = segments_from_target(out)
    assert restored[0].role == "work" and restored[0].repeat == 4
    assert restored[0].recovery.until_hr == 130


def test_finalize_populates_segments(athlete_with_history, db_session):
    """Сквозь finalize: proposal с сегментами → target['segments'], зоны ≤ потолка."""
    from src.coach.contracts import WorkoutProposal
    from src.coach.prescriber import finalize
    from src.coach.state import assess_state

    state = assess_state(athlete_with_history.id, db=db_session)
    proposal = WorkoutProposal(
        workout_type="interval", target_zone=4, duration_min=40,
        segments=[
            WorkoutSegment(role="warmup", amount_kind="km", amount_value=3, target_zone=2),
            WorkoutSegment(role="work", repeat=6, amount_kind="sec", amount_value=20,
                           target_zone=4, recovery=RecoverySpec(until_hr=130)),
        ])
    p = finalize(proposal, state, db=db_session, source="llm")
    segs = p.target.get("segments")
    if p.workout_type == proposal.workout_type:      # тип не понижен safety
        assert segs and len(segs) == 2
        cap = p.target["max_zone"]
        assert all(s["target_zone"] is None or s["target_zone"] <= cap for s in segs)
        assert segs[0]["hr_ceiling"] is not None
    else:                                            # понижен → структура снята
        assert not segs


def test_segments_from_schema():
    """Схема хода LLM → доменные сегменты (schema → domain)."""
    from src.coach.llm.schemas import WorkoutProposalIn
    prop = WorkoutProposalIn(workout_type="interval", target_zone=4, duration_min=40,
                             segments=[{"role": "work", "repeat": 6, "amount_kind": "sec",
                                        "amount_value": 20, "target_zone": 4,
                                        "recovery": {"until_hr": 130}}])
    segs = segments_from_schema(prop.segments)
    assert len(segs) == 1 and segs[0].role == "work" and segs[0].repeat == 6
    assert segs[0].recovery.until_hr == 130
