# Потолки объёма в ad-hoc пути (чат/утро) — #338–#343, инцидент 13.09.2026 (day caps tests)
from datetime import date, timedelta

import pytest

from src.coach import orchestrator, planning, prescriber
from src.coach.contracts import (
    AthleteState,
    Prescription,
    RecoverySpec,
    SafetyVerdict,
    WorkoutProposal,
    WorkoutSegment,
)
from src.coach.day_caps import cap_day_volume, cap_run_days, context_block, finalize_with_caps, run_days_used
from src.coach.llm.client import LLMResponse
from src.coach.segment_trim import shrink_proposal, total_minutes, trim_segments
from src.models import Recommendation
from tests.coach.conftest import _unique_user
from tests.coach.fakes import ScriptedLLM

PACE = 7.0   # фейковый темп истории: мин/км → км = минуты / 7


def _prescription(duration_min, *, when=None, workout_type="long"):
    return Prescription(safety=SafetyVerdict(), workout_type=workout_type, when=when or date.today(),
                        volume={"duration_min": float(duration_min)},
                        predicted={"pace_min_km": PACE, "distance_km": round(duration_min / PACE, 1)})


def _targets(today, **over):
    monday = today - timedelta(days=today.weekday())
    t = {"week_start": monday.isoformat(), "plan_scope": "rest_of_week",
         "target_km": 26.0, "done_km": 16.0, "remaining_km": 10.0, "prev_week_km": 26.0,
         "long_run_km_max": 8.4, "long_run_max_pct": 0.40, "long_run_min_max": 150.0,
         "long_run_min_hint": 50, "long_run_hold": False, "hard_days_max": 1,
         "days_ahead_allowed": list(range(0, 7 - today.weekday()))}
    t.update(over)
    return t


# --- segment_trim: урезание по литературе (решение владельца 16.09.2026) ---

def _strides_long():
    return [WorkoutSegment(role="warmup", amount_value=10, target_zone=1),
            WorkoutSegment(role="steady", amount_value=50, target_zone=2),
            WorkoutSegment(role="work", amount_kind="sec", amount_value=20, repeat=5, target_zone=4,
                           recovery=RecoverySpec(duration_min=2.0)),
            WorkoutSegment(role="cooldown", amount_value=2, target_zone=1)]


def test_trim_strides_cuts_steady_and_keeps_strides():
    """Длительная с ускорениями 74 → 58 мин: ровная часть режется, 5 ускорений остаются."""
    r = trim_segments(_strides_long(), 58)
    assert r.segments and r.total_min <= 58
    work = next(s for s in r.segments if s.role == "work")
    assert work.repeat == 5 and work.amount_value == 20
    assert next(s for s in r.segments if s.role == "warmup").amount_value == 10   # пол разминки
    assert "5 ускорений сохранены" in r.note and "ровная часть" in r.note


def test_trim_strides_dropped_when_steady_too_short():
    """Ровной части осталось бы < 30 мин → ускорения снимаются (ровная пробежка под потолком)."""
    r = trim_segments(_strides_long(), 35)
    assert r.segments == [] and "ускорения сняты" in r.note


def test_trim_quality_reduces_repeats_keeps_warmup_cooldown():
    q = [WorkoutSegment(role="warmup", amount_value=15, target_zone=2),
         WorkoutSegment(role="work", amount_value=3, repeat=6, target_zone=4,
                        recovery=RecoverySpec(duration_min=2.0)),
         WorkoutSegment(role="cooldown", amount_value=10, target_zone=1)]
    r = trim_segments(q, 45)                              # 55 → 45: 6×5 → 4×5
    assert [s.role for s in r.segments] == ["warmup", "work", "cooldown"]
    assert r.segments[1].repeat == 4 and r.segments[0].amount_value == 15 and r.segments[2].amount_value == 10
    assert r.note == "повторы 6 → 4" and r.total_min == 45
    # Ниже минимума повторов не идём — структура снимается
    assert trim_segments(q, 20).segments == []


def test_trim_caps_strides_count_by_guide():
    """Гайд 46: ускорений не больше 8 за тренировку — даже когда объём под потолком."""
    segs = [WorkoutSegment(role="steady", amount_value=40, target_zone=2),
            WorkoutSegment(role="work", amount_kind="sec", amount_value=20, repeat=12, target_zone=4)]
    r = trim_segments(segs, 60)
    assert r.segments[1].repeat == 8 and "ускорения 12 → 8" in r.note


def test_shrink_proposal_partial_structure_keeps_segments():
    """Структура покрывает лишь часть тренировки (одни ускорения) → сегменты как есть, минуты вниз."""
    p = WorkoutProposal(workout_type="easy", target_zone=2, duration_min=42, segments=[
        WorkoutSegment(role="work", amount_kind="sec", amount_value=20, repeat=5, target_zone=3)])
    new, note = shrink_proposal(p, 33, trail="t")
    assert new.duration_min == 33 and len(new.segments) == 1 and note is None
    assert new.code_trimmed and new.rationale == ["t"] and p.duration_min == 42   # вход не мутирует


def test_shrink_proposal_structured_duration_equals_segments_sum():
    p = WorkoutProposal(workout_type="long", target_zone=2, duration_min=74, distance_km=10.5,
                        segments=_strides_long())
    new, note = shrink_proposal(p, 58, trail="t")
    assert new.duration_min == int(total_minutes(new.segments)) <= 58
    assert new.distance_km < 10.5 and "ускорений сохранены" in note


# --- cap_day_volume: потолок дня от остатка недели (чистая) ---

def test_cap_day_volume_trims_to_remaining_minus_other_days():
    today = date.today()
    proposal = WorkoutProposal(workout_type="easy", target_zone=2, duration_min=60)
    p = _prescription(60, workout_type="easy")                       # ≈8.6 км
    capped, note = cap_day_volume(proposal, p, _targets(today, remaining_km=6.0), other_planned_km=2.0)
    assert capped is not None and capped.duration_min == 30            # пол 30 мин (6.3 − 2 = 4.3 км)
    assert "Объём урезан до 30 мин" in note and "осталось 6.0 км" in note and "2.0 уже назначено" in note
    assert capped.rationale[-1].startswith("урезано кодом: 60 → 30 мин (объём недели")


def test_cap_day_volume_within_allowance_or_outside_week_untouched():
    today = date.today()
    proposal = WorkoutProposal(workout_type="easy", target_zone=2, duration_min=60)
    p = _prescription(60, workout_type="easy")
    assert cap_day_volume(proposal, p, _targets(today, remaining_km=9.0)) == (None, None)   # 8.6 ≤ 9.45
    nxt = _prescription(60, when=today + timedelta(days=8), workout_type="easy")            # вне недели
    assert cap_day_volume(proposal, nxt, _targets(today, remaining_km=1.0)) == (None, None)
    rest = WorkoutProposal(workout_type="rest", target_zone=1)
    assert cap_day_volume(rest, p, _targets(today, remaining_km=1.0)) == (None, None)


def test_context_block_compact_and_unallocated():
    t = _targets(date.today(), planned_km_remaining=7.0)
    block = context_block(t)
    assert block["remaining_km"] == 10.0 and block["long_run_km_max"] == 8.4
    assert block["planned_km_remaining"] == 7.0 and block["unallocated_km"] == 3.5   # 10 × 1.05 − 7
    assert "quality_ladder" not in block and "rule" in block
    assert "frequency_rule" not in block                       # без run_days_max — молчим
    # 17.09.2026: частота — модель видит лимит дней и сколько уже занято
    block = context_block(_targets(date.today(), run_days_max=4, rest_days_min=3, done_runs=2, run_days_used=3))
    assert block["run_days_max"] == 4 and block["run_days_used"] == 3 and "frequency_rule" in block


# --- E2E: инцидент 13.09.2026 в чате ---

def _fake_predict(p, state, *, db):
    if p.workout_type == "rest":
        return {}
    d = p.volume.get("duration_min") or 0
    return {"pace_min_km": PACE, "distance_km": round(d / PACE, 1)}


def _plan_row(db, user_id, today, *, workout_type="long", duration=50.0, predicted_km=7.1,
              status="planned"):
    rec = Recommendation(user_id=user_id, for_date=today, workout_type=workout_type,
                         target_json={"max_zone": 2}, volume_json={"duration_min": duration},
                         predicted_json={"pace_min_km": PACE, "distance_km": predicted_km},
                         status=status, source="llm")
    db.add(rec)
    db.commit()
    return rec


def _turn(duration, distance=None, workout_type="long"):
    return {"message": "Хорошо, давай.", "followup_question": None, "log_suggestion": None,
            "proposal": {"workout_type": workout_type, "target_zone": 2, "duration_min": duration,
                         "distance_km": distance, "structure": None, "segments": [],
                         "rationale": ["просьба подопечного"], "for_days_ahead": 0}}


@pytest.fixture
def capped_world(athlete_with_history, db_session, monkeypatch):
    """Фиксированные числа недели + детерминированный темп истории (7:00/км)."""
    from src.utils.timeutils import user_now
    today = user_now(athlete_with_history).date()
    monkeypatch.setattr(planning, "week_targets", lambda *a, **k: _targets(today))
    monkeypatch.setattr(prescriber, "predict_volume", _fake_predict)
    return athlete_with_history, today


def test_chat_request_for_more_is_capped_like_incident_13_09(capped_world, db_session, monkeypatch):
    """План дня — длительная 50 мин (≈7.1 км), подопечный просит 72 мин / 10 км при потолке 8.4 км →
    карточка 58 мин, строка «⚠️ Длительная урезана…», в recommendations — след урезания и исходные 72."""
    from src.coach import chat_flow
    user, today = capped_world
    _plan_row(db_session, user.id, today)
    seen: dict = {}
    real_block = chat_flow.build_today_block

    def spy(state_json, verdict_json, now_str, extras=None):
        seen["targets"] = (extras or {}).get("week_targets (planning)")
        return real_block(state_json, verdict_json, now_str, extras=extras)
    monkeypatch.setattr(chat_flow, "build_today_block", spy)

    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=_turn(72, 10.0))])
    reply = orchestrator.handle_chat(user.id, "а можно 10 км?", db=db_session, llm=llm)
    assert reply.source == "llm"
    assert "⚠️ Длительная урезана до 58 мин" in reply.text and "потолок 40 % недельного объёма" in reply.text
    assert "58 мин" in reply.text and "72 мин" not in reply.text.split("⚠️")[1].split("\n")[0]
    # #339: модель видела числа недели
    assert seen["targets"]["long_run_km_max"] == 8.4 and seen["targets"]["remaining_km"] == 10.0
    row = db_session.query(Recommendation).filter_by(user_id=user.id).order_by(Recommendation.id.desc()).first()
    assert row.workout_type == "long" and row.volume_json["duration_min"] == 58.0
    assert row.proposal_json["duration_min"] == 58 and row.proposal_json["code_trimmed"] is True
    assert any(r.startswith("урезано кодом: 72 → 58 мин") for r in row.proposal_json["rationale"])


def test_chat_request_within_caps_accepted(capped_world, db_session):
    """Просьба в пределах потолков (60 мин ≈ 8.6 км при остатке 10 км) принимается без урезания."""
    user, today = capped_world
    _plan_row(db_session, user.id, today)
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=_turn(58))])
    reply = orchestrator.handle_chat(user.id, "можно час?", db=db_session, llm=llm)
    assert "урезан" not in reply.text and "Изменил план" in reply.text
    row = db_session.query(Recommendation).filter_by(user_id=user.id).order_by(Recommendation.id.desc()).first()
    assert row.volume_json["duration_min"] == 58.0 and not row.proposal_json.get("code_trimmed")


def test_chat_day_volume_respects_other_planned_days(capped_world, db_session):
    """Остаток недели 10 км, на другой день уже назначено 6 км → сегодня не больше ≈4.5 км:
    просьба 60 мин (≈8.6 км) урезана; отменённый той же репликой день объём освобождает."""
    from src.utils.timeutils import WEEKDAYS_RU_SHORT
    user, today = capped_world
    other = today + timedelta(days=2)
    _plan_row(db_session, user.id, other, workout_type="easy", duration=42.0, predicted_km=6.0)
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=_turn(60, workout_type="easy"))])
    reply = orchestrator.handle_chat(user.id, "сегодня час", db=db_session, llm=llm)
    assert "⚠️ Объём урезан до" in reply.text and "6.0 уже назначено на другие дни" in reply.text
    # Та же просьба с отменой другого дня — объём свободен, урезания нет
    user2 = _unique_user(db_session)
    _plan_row(db_session, user2.id, other, workout_type="easy", duration=42.0, predicted_km=6.0)
    turn = dict(_turn(60, workout_type="easy"), unavailable_days_ahead=[2])
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=turn)])
    reply = orchestrator.handle_chat(user2.id, "сегодня час, послезавтра не смогу", db=db_session, llm=llm)
    assert "Объём урезан" not in reply.text
    assert WEEKDAYS_RU_SHORT[other.weekday()] in reply.text          # отмена дня записана


def test_reminder_does_not_rewrite_plan_row_342(capped_world, db_session):
    """#342: «напомни план» → LLM возвращает то же назначение long 50 (hint 50) → короткая строка,
    новой строки нет (раньше порог 60 мин переименовывал в easy и перезаписывал строку)."""
    user, today = capped_world
    rec = _plan_row(db_session, user.id, today)
    n_before = db_session.query(Recommendation).filter_by(user_id=user.id).count()
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=_turn(50))])
    reply = orchestrator.handle_chat(user.id, "напомни план на сегодня", db=db_session, llm=llm)
    assert "без изменений" in reply.text and "Изменил план" not in reply.text
    assert db_session.query(Recommendation).filter_by(user_id=user.id).count() == n_before
    db_session.refresh(rec)
    assert rec.workout_type == "long"


def test_morning_caps_plan_row_by_fresh_week_numbers(capped_world, db_session):
    """Решение владельца 16.09.2026: утро сверяет и plan-строку с потолками — длительная 72 мин
    (≈10.3 км) при потолке 8.4 → adjusted 58 мин с заметкой; в пределах — confirmed без дубля."""
    user, today = capped_world
    confirm = {"message": "Идём по плану.", "proposal": None, "followup_question": None,
               "log_suggestion": None}
    ok_row = _plan_row(db_session, user.id, today)                      # 50 мин — в пределах
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=confirm)])
    reply = orchestrator.handle_chat(user.id, "утренний вердикт", db=db_session, llm=llm, kind="morning")
    assert "урезан" not in reply.text
    db_session.refresh(ok_row)
    assert ok_row.status == "confirmed"
    # Новая (более поздняя) plan-строка выше потолка → утро режет её по свежим числам недели
    rec = _plan_row(db_session, user.id, today, duration=72.0, predicted_km=10.3)
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=confirm)])
    reply = orchestrator.handle_chat(user.id, "утренний вердикт", db=db_session, llm=llm, kind="morning")
    assert "⚠️ Длительная урезана до 58 мин" in reply.text and "Изменил план" in reply.text
    adjusted = db_session.query(Recommendation).filter_by(user_id=user.id, status="adjusted").one()
    assert adjusted.volume_json["duration_min"] == 58.0
    db_session.refresh(rec)
    assert rec.status == "planned"


# --- #343: сегменты не откатывают потолок длительности safety ---

def test_segments_do_not_revert_safety_duration_cap(db_session):
    """Боль → max_duration 40; предложение 60 мин с сегментами на 55 → длительность 40, структура
    снята (раньше сумма сегментов возвращала 55 после clamp)."""
    user = _unique_user(db_session)
    signals = {"hrv_status": "normal", "rhr_status": "normal", "recovery_pct": 90, "ati_cti_ratio": 1.0,
               "acwr_ratio": 1.0, "consecutive_hard_days": 0, "pain_level": 3, "pain_days": 1}
    state = AthleteState(user_id=user.id, as_of=date.today(), data_confidence=0.9,
                         recovery_hours_left=0.0, signals=signals)
    proposal = WorkoutProposal(workout_type="easy", target_zone=2, duration_min=60, segments=[
        WorkoutSegment(role="warmup", amount_value=10, target_zone=1),
        WorkoutSegment(role="steady", amount_value=30, target_zone=2),
        WorkoutSegment(role="work", amount_kind="sec", amount_value=20, repeat=5, target_zone=4,
                       recovery=RecoverySpec(duration_min=2.0)),
        WorkoutSegment(role="cooldown", amount_value=3, target_zone=1)])
    p = prescriber.finalize(proposal, state, db=db_session, persist=False, source="llm")
    assert p.safety.max_duration_min == 40 and p.volume["duration_min"] == 40
    assert not p.target.get("segments")
    assert any(r.decision == "структура снята" for r in p.rationale)


# --- #341: база сравнения план vs факт ---

def test_plan_for_session_keeps_original_plan_as_baseline(capped_world, db_session):
    """План 50 мин, чат переписал на 72, факт 71 мин → baseline = плановая строка, флаг перевыполнения."""
    from src.analysis.session_metrics import FLAG_PLAN_VOLUME
    from src.services.workout_insights_context import _plan_for_session
    from src.services.workout_insights import get_or_compute
    from tests.helpers import build_training_session
    from src.domain.models.base import utcnow
    user, today = capped_world
    plan = _plan_row(db_session, user.id, today)
    chat = Recommendation(user_id=user.id, for_date=today, workout_type="long", status="confirmed",
                          target_json={"max_zone": 2}, volume_json={"duration_min": 72.0}, source="llm")
    db_session.add(chat)
    db_session.commit()
    session = build_training_session(db_session, user.id, total_distance_km=10.1, duration_minutes=71.0,
                                     training_type="long", avg_heart_rate=133, begin_ts=utcnow())
    got = _plan_for_session(user.id, session, db=db_session)
    assert got["duration_min"] == 72.0 and got["baseline"]["duration_min"] == 50.0
    assert got["baseline"]["recommendation_id"] == plan.id
    computed = get_or_compute(user.id, session.id, db=db_session)
    pva = computed["plan_vs_actual"]
    assert pva["baseline"]["volume_ratio"] == 1.42 and FLAG_PLAN_VOLUME in pva["flags"]
    # Недельная сверка видит переторгованный день
    review = planning.week_plan_review(user.id, db=db_session)
    day = next(d for d in review["days"] if d["date"] == today.isoformat())
    assert day["changed_in_chat"] is True and day["planned_min_original"] == 50.0
    assert review["changed_in_chat"] == 1


def test_finalize_with_caps_without_targets_is_plain_finalize(db_session):
    user = _unique_user(db_session)
    state = AthleteState(user_id=user.id, as_of=date.today(), data_confidence=0.5,
                         recovery_hours_left=0.0, signals={})
    p, notes = finalize_with_caps(WorkoutProposal(workout_type="easy", target_zone=2, duration_min=200),
                                  state, db=db_session, now=None or __import__("datetime").datetime.now(
                                      __import__("datetime").timezone.utc), source="llm", targets=None)
    assert notes == [] and p.volume["duration_min"] in (200.0, None) or p.workout_type == "rest"


# --- Кэп частоты: лишний беговой день сверх run_days_max (17.09.2026, решение владельца — мягко) ---

THU = date(2026, 9, 17)   # чт: фиксированная дата — тесты чистых функций датонезависимы


def test_run_days_used_counts_each_date_once():
    """Факт ∪ план множеством дат: день с пробежкой и живой строкой не удваивается; целевой день вне счёта."""
    t = _targets(THU, done_dates=["2026-09-14", "2026-09-16"])            # пн, ср — факт
    planned = {date(2026, 9, 16), date(2026, 9, 19)}                        # ср (уже бегал) и сб — план
    assert run_days_used(t, planned) == 3                                   # пн, ср, сб
    assert run_days_used(t, planned, when=date(2026, 9, 19)) == 2           # сб — целевой день
    assert run_days_used(_targets(THU), set()) == 0


def test_cap_run_days_downgrades_extra_day_to_short_easy():
    """Дни исчерпаны, день не из плана → long 60 со структурой становится easy 30 без сегментов и темпа."""
    p = WorkoutProposal(workout_type="long", target_zone=3, duration_min=60, distance_km=8.6,
                        target_pace_min_km=6.5, segments=_strides_long())
    capped, note = cap_run_days(p, _prescription(60, when=THU), _targets(THU, run_days_max=4),
                                run_days_used=4, plan_day=False)
    assert capped.workout_type == "easy" and capped.target_zone == 2 and capped.duration_min == 30
    assert capped.segments == [] and capped.target_pace_min_km is None and capped.distance_km == 4.3
    assert capped.code_trimmed is True and any("лишний беговой день" in r for r in capped.rationale)
    assert "⚠️ Беговые дни недели исчерпаны (4 из 4)" in note and "long 60 мин" in note


def test_cap_run_days_silent_when_days_remain_plan_day_or_outside_week():
    p = WorkoutProposal(workout_type="easy", target_zone=2, duration_min=45)
    t = _targets(THU, run_days_max=4)
    assert cap_run_days(p, _prescription(45, when=THU), t, run_days_used=3, plan_day=False) == (None, None)
    assert cap_run_days(p, _prescription(45, when=THU), t, run_days_used=4, plan_day=True) == (None, None)
    assert cap_run_days(p, _prescription(45, when=THU + timedelta(days=10)), t,
                        run_days_used=4, plan_day=False) == (None, None)
    assert cap_run_days(p, _prescription(45, when=THU), _targets(THU),          # без run_days_max
                        run_days_used=9, plan_day=False) == (None, None)


def test_cap_run_days_already_short_easy_gets_only_note():
    p = WorkoutProposal(workout_type="easy", target_zone=2, duration_min=25)
    capped, note = cap_run_days(p, _prescription(25, when=THU, workout_type="easy"),
                                _targets(THU, run_days_max=4), run_days_used=4, plan_day=False)
    assert capped is None and "исчерпаны (4 из 4)" in note


def _occupy_week(db, user_id, today, n):
    """Занять n беговых дней недели кроме сегодня: прошедшие — фактом (done_dates), будущие — строками
    плана. Датонезависимо: в любой день недели других дней шесть."""
    monday = today - timedelta(days=today.weekday())
    others = [monday + timedelta(days=i) for i in range(7) if monday + timedelta(days=i) != today][:n]
    done = []
    for d in others:
        if d < today:
            done.append(d.isoformat())
        else:
            _plan_row(db, user_id, d, workout_type="easy", duration=40.0, predicted_km=5.7)
    return done


def _freq_targets(today, done, run_days_max):
    return _targets(today, run_days_max=run_days_max, rest_days_min=7 - run_days_max, done_dates=done,
                    target_km=40.0, remaining_km=30.0)


def test_chat_run_on_rest_day_downgraded_when_week_days_exhausted(capped_world, db_session, monkeypatch):
    """«Хочу сегодня побегать» в день без строки (плановый отдых) при исчерпанных беговых днях →
    карточка лёгкие 30 мин, строка «⚠️ Беговые дни недели исчерпаны», строка proposed с code_trimmed."""
    user, today = capped_world
    done = _occupy_week(db_session, user.id, today, 3)
    monkeypatch.setattr(planning, "week_targets", lambda *a, **k: _freq_targets(today, done, 3))
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=_turn(45, workout_type="easy"))])
    reply = orchestrator.handle_chat(user.id, "хочу сегодня побегать", db=db_session, llm=llm)
    assert "⚠️ Беговые дни недели исчерпаны (3 из 3)" in reply.text and "easy 45 мин" in reply.text
    row = (db_session.query(Recommendation).filter_by(user_id=user.id, for_date=today)
           .order_by(Recommendation.id.desc()).first())
    assert row.workout_type == "easy" and row.volume_json["duration_min"] == 30.0
    assert row.status == "proposed" and row.proposal_json["code_trimmed"] is True
    # повторная просьба «а можно 40?» — строка proposed день не освобождает, кэп держится
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=_turn(40, workout_type="easy"))])
    reply = orchestrator.handle_chat(user.id, "а можно 40 минут?", db=db_session, llm=llm)
    assert "Беговые дни недели исчерпаны" in reply.text


def test_chat_run_on_free_day_passes_without_note(capped_world, db_session, monkeypatch):
    """Дни не исчерпаны → просьба проходит без заметки и без урезания."""
    user, today = capped_world
    done = _occupy_week(db_session, user.id, today, 3)
    monkeypatch.setattr(planning, "week_targets", lambda *a, **k: _freq_targets(today, done, 4))
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=_turn(45, workout_type="easy"))])
    reply = orchestrator.handle_chat(user.id, "хочу сегодня побегать", db=db_session, llm=llm)
    assert "Беговые дни" not in reply.text
    row = (db_session.query(Recommendation).filter_by(user_id=user.id, for_date=today)
           .order_by(Recommendation.id.desc()).first())
    assert row.volume_json["duration_min"] == 45.0 and not row.proposal_json.get("code_trimmed")


def test_chat_plan_day_exempt_from_run_days_cap(capped_world, db_session, monkeypatch):
    """Плановый день (planned) при исчерпанных беговых днях кэп частоты не трогает — каркас недели
    защищает enforce_run_days, а не safety ad-hoc пути."""
    user, today = capped_world
    done = _occupy_week(db_session, user.id, today, 3)
    _plan_row(db_session, user.id, today)                                    # long 50, planned
    monkeypatch.setattr(planning, "week_targets", lambda *a, **k: _freq_targets(today, done, 3))
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=_turn(50))])
    reply = orchestrator.handle_chat(user.id, "напомни план", db=db_session, llm=llm)
    assert "Беговые дни" not in reply.text and "без изменений" in reply.text
