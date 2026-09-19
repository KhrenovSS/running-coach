# Кэпы дня считаются по неделе, КОТОРОЙ ПРИНАДЛЕЖИТ ДЕНЬ (инцидент 19.09.2026).
#
# В воскресенье `plan_window` уходит на следующую неделю (это нужно `/plan` в 19:00), и утренний
# вердикт мерил сегодняшнюю длительную потолком следующей недели: 75 → 46 мин при здоровом
# остатке текущей. Здесь: флаг current_week, гвард по границам недели в cap_long_run и регрессия
# самого сценария. (Day caps must measure the day's own week.)
from datetime import date, timedelta

from src.coach import day_caps, planning, prescriber
from src.coach.config import PLAN_TODAY_CUTOFF_HOUR
from src.coach.contracts import Prescription, SafetyVerdict, WorkoutProposal
from src.coach.planning_safety import cap_long_run
from src.coach.planning_window import plan_window, week_bounds
from tests.coach.conftest import _unique_user
from tests.helpers import build_training_session

SUNDAY = date(2026, 9, 20)
MONDAY = date(2026, 9, 14)          # понедельник ТОЙ ЖЕ недели
PACE = 7.0


def _prescription(duration_min, when):
    return Prescription(safety=SafetyVerdict(), workout_type="long", when=when,
                        volume={"duration_min": float(duration_min)},
                        predicted={"pace_min_km": PACE, "distance_km": round(duration_min / PACE, 1)})


def _fake_predict(p, state, *, db):
    """Детерминированный ориентир темпа 7:00/км (как в test_day_caps)."""
    if p.workout_type == "rest":
        return {}
    d = p.volume.get("duration_min") or 0
    return {"pace_min_km": PACE, "distance_km": round(d / PACE, 1)}


def _proposal(duration_min):
    return WorkoutProposal(workout_type="long", target_zone=2, duration_min=duration_min)


def _targets(week_start: date, **over):
    t = {"week_start": week_start.isoformat(), "plan_scope": "rest_of_week",
         "target_km": 28.9, "done_km": 15.1, "remaining_km": 13.8,
         "long_run_km_max": 11.6, "long_run_max_pct": 0.40, "long_run_min_max": 150.0}
    t.update(over)
    return t


# --- окно планирования ---

def test_plan_window_current_week_keeps_sunday_in_its_own_week():
    """Флаг current_week: в вс окно — остаток ЭТОЙ недели (только сегодня), не следующая."""
    assert plan_window(SUNDAY, False, current_week=True) == (MONDAY, 0, 0)
    assert plan_window(SUNDAY, True, current_week=True) == (MONDAY, 1, 0)      # уже бегали
    assert plan_window(SUNDAY, False, PLAN_TODAY_CUTOFF_HOUR, current_week=True) == (MONDAY, 1, 0)


def test_plan_window_without_flag_unchanged():
    """Без флага (`/plan`, воскресный джоб) — прежнее поведение: следующая неделя целиком."""
    assert plan_window(SUNDAY, False) == (SUNDAY + timedelta(days=1), 1, 7)


def test_week_bounds_reads_targets():
    assert week_bounds(_targets(MONDAY)) == (MONDAY, SUNDAY)
    assert week_bounds({}) is None


# --- гвард в cap_long_run ---

def test_cap_long_run_skips_day_outside_targets_week():
    """День вне недели targets → кэп не применяем (иначе потолок чужой недели)."""
    targets = _targets(SUNDAY + timedelta(days=1), long_run_km_max=6.6)   # следующая неделя
    capped, note = cap_long_run(_proposal(75), _prescription(75, SUNDAY), targets)
    assert capped is None and note is None


def test_cap_long_run_still_caps_inside_its_week():
    """Внутри своей недели кэп работает как раньше."""
    targets = _targets(MONDAY, long_run_km_max=6.6)
    capped, note = cap_long_run(_proposal(75), _prescription(75, SUNDAY), targets)
    assert capped is not None and capped.duration_min < 75 and "урезана" in note


# --- регрессия: воскресный вердикт не режет длительную ---

def _history(db_session, user):
    """Прошлая неделя ~26 км и три пробежки текущей (пн/вт/чт) — как на проде 14–20.09."""
    for day, km in ((7, 5.7), (5, 5.9), (4, 4.6), (2, 10.1)):        # 07–13.09
        build_training_session(db_session, user.id, training_type="easy", total_distance_km=km,
                               duration_minutes=km * PACE, begin_ts=_ts(MONDAY - timedelta(days=day)))
    for day, km in ((6, 4.7), (5, 6.0), (3, 4.4)):                   # пн/вт/чт текущей
        build_training_session(db_session, user.id, training_type="easy", total_distance_km=km,
                               duration_minutes=km * PACE, begin_ts=_ts(SUNDAY - timedelta(days=day)))


def test_day_targets_on_sunday_describe_current_week(db_session):
    """Регрессия: ad-hoc числа недели в воскресенье — про ТЕКУЩУЮ неделю.

    До фикса `day_targets` отдавал следующую неделю (week_start = 21.09, target 16.6,
    потолок длительной 6.6 км) — и ею мерился сегодняшний день.
    """
    user = _unique_user(db_session)
    _history(db_session, user)
    targets = day_caps.day_targets(user.id, SafetyVerdict(), db=db_session,
                                   now=_dt(SUNDAY, 9, 30))
    assert targets["week_start"] == MONDAY.isoformat()
    assert targets["done_runs"] == 3 and targets["done_km"] > 14
    assert targets["long_run_km_max"] == round(targets["target_km"] * targets["long_run_max_pct"], 1)
    # потолок текущей недели ≈ 10.5 км: 75 мин (≈10.7 км) проходят в допуск LONG_RUN_CAP_TOLERANCE_KM,
    # тогда как у следующей недели он был бы 6.6 км
    assert targets["long_run_km_max"] > 10.0


def test_sunday_long_run_is_not_trimmed_by_next_week(db_session, monkeypatch):
    """Регрессия 19.09.2026 end-to-end: длительная по плану в вс остаётся 75 мин.

    До фикса тот же вызов давал 75 → 46 мин («потолок 40 % недельного объёма» — следующей недели).
    """
    monkeypatch.setattr(prescriber, "predict_volume", _fake_predict)
    user = _unique_user(db_session)
    _history(db_session, user)
    state = _state(user.id, SUNDAY)
    targets = day_caps.day_targets(user.id, SafetyVerdict(), db=db_session, now=_dt(SUNDAY, 9, 30))
    presc, notes = day_caps.finalize_with_caps(_proposal(75), state, db=db_session,
                                               now=_dt(SUNDAY, 9, 30), source="plan",
                                               targets=targets)
    assert presc.volume["duration_min"] == 75 and notes == []


def test_weekday_long_run_still_capped(db_session, monkeypatch):
    """Будний день: потолок недели работает как раньше (кэп не потерян)."""
    monkeypatch.setattr(prescriber, "predict_volume", _fake_predict)
    user = _unique_user(db_session)
    state = _state(user.id, SUNDAY - timedelta(days=2))
    targets = _targets(MONDAY, long_run_km_max=6.6, remaining_km=6.6)
    presc, notes = day_caps.finalize_with_caps(_proposal(75), state, db=db_session,
                                               now=_dt(SUNDAY - timedelta(days=2), 9, 30),
                                               source="plan", targets=targets)
    assert presc.volume["duration_min"] < 75 and notes


# --- helpers ---

def _ts(day: date):
    from datetime import datetime, timezone
    return datetime(day.year, day.month, day.day, 8, 0, tzinfo=timezone.utc)


def _dt(day: date, hour: int, minute: int):
    from datetime import datetime
    return datetime(day.year, day.month, day.day, hour, minute)


def _state(user_id: int, when: date):
    """Чистое состояние: safety не вмешивается, проверяем именно кэпы объёма."""
    from src.coach.contracts import AthleteState
    signals = {"hrv_status": "normal", "rhr_status": "normal", "recovery_pct": 90,
               "ati_cti_ratio": 1.0, "acwr_ratio": 1.0, "consecutive_hard_days": 0}
    return AthleteState(user_id=user_id, as_of=when, data_confidence=0.9,
                        recovery_hours_left=0.0, signals=signals)
