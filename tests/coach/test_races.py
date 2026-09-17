# Календарь целевых стартов и периодизация (#243 ч.1, 17.09.2026): хранение в params_json, факты из
# CoachTurn.races, потолок объёма по дистанции, фазы по неделям до старта, размещение старта в плане.
# Даты — от фиксированного today (#328/#332). (Race calendar + periodization tests.)
from datetime import date, datetime, timedelta, timezone

import pytest

from src.coach import race_plan, races
from src.coach.config import (
    RACE_HORIZON_WEEKS,
    RACE_RATIONALE,
    RACE_TAPER_VOLUME_PCT,
    RACE_VOLUME_DEFAULT_CEILING_KM,
    RACE_VOLUME_HARD_CAP_KM,
    RACE_WEEK_VOLUME_PCT,
)
from src.coach.contracts import Prescription, SafetyVerdict, WorkoutProposal, WorkoutSegment
from src.coach.llm.schemas import CoachTurn, RaceReport
from src.coach import lthr_field
from src.models import UserModel
from tests.coach.conftest import _unique_user

TODAY = date(2026, 9, 17)                       # чт
NOW = datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc)
MONDAY = date(2026, 9, 14)


def _race(d: date, km: float = 21.1, label: str = "ПМ", status: str = "active", rid: int = 1) -> dict:
    return {"id": rid, "date": d.isoformat(), "distance_km": km, "label": label, "status": status}


# --- схема ---

def test_turn_schema_accepts_races_and_rejects_bad_date():
    turn = CoachTurn(message="ок", races=[{"status": "add", "date": "05-12", "distance_km": 21.1}])
    assert turn.races[0].status == "add" and turn.races[0].date == "05-12"
    assert CoachTurn(message="ок").races is None
    with pytest.raises(ValueError):
        RaceReport(status="add", date="12 мая", distance_km=21.1)
    with pytest.raises(ValueError):
        RaceReport(status="add", date="05-12", distance_km=500)


# --- resolve_race_date ---

def test_resolve_race_date_iso_month_day_and_days_ahead():
    assert races.resolve_race_date(RaceReport(status="add", date="2027-05-12"), TODAY) == date(2027, 5, 12)
    assert races.resolve_race_date(RaceReport(status="add", date="05-12"), TODAY) == date(2027, 5, 12)  # уже прошло → +1 год
    assert races.resolve_race_date(RaceReport(status="add", date="11-15"), TODAY) == date(2026, 11, 15)
    assert races.resolve_race_date(RaceReport(status="add", days_ahead=7), TODAY) == TODAY + timedelta(days=7)
    for bad in (RaceReport(status="add", date="2026-01-01"),                   # прошлое
                RaceReport(status="add", days_ahead=366),                      # дальше года
                RaceReport(status="add", date="05-12", days_ahead=3),          # дважды
                RaceReport(status="add")):                                     # пусто
        with pytest.raises(ValueError):
            races.resolve_race_date(bad, TODAY)


# --- record_race: add / cancel / expire ---

def test_record_race_add_cancel_and_lazy_done(db_session):
    user = _unique_user(db_session)
    text = races.record_race(RaceReport(status="add", date="11-15", distance_km=21.1, label="Осенний ПМ"),
                             user.id, db=db_session, now=NOW)
    assert text.startswith("Записал старт: 15.11 · Осенний ПМ (21.1 км)") and "ориентир пика ~55 км/нед" in text
    active = races.active_races(user.id, db=db_session, today=TODAY)
    assert len(active) == 1 and active[0]["distance_km"] == 21.1
    # дубль по дате обновляет, не плодит
    races.record_race(RaceReport(status="add", date="11-15", distance_km=10.0), user.id, db=db_session, now=NOW)
    active = races.active_races(user.id, db=db_session, today=TODAY)
    assert len(active) == 1 and active[0]["distance_km"] == 10.0 and active[0]["label"] == "10 км"
    # второй старт; неоднозначная отмена → перечисление, ничего не снято
    races.record_race(RaceReport(status="add", days_ahead=3, distance_km=5.0), user.id, db=db_session, now=NOW)
    assert len(races.active_races(user.id, db=db_session, today=TODAY)) == 2
    text = races.record_race(RaceReport(status="cancel"), user.id, db=db_session, now=NOW)
    assert text.startswith("Уточни, какой старт снять") and len(races.active_races(user.id, db=db_session, today=TODAY)) == 2
    # отмена по дистанции — однозначна
    text = races.record_race(RaceReport(status="cancel", distance_km=5.0), user.id, db=db_session, now=NOW)
    assert text.startswith("Снял старт") and [r["distance_km"] for r in races.active_races(user.id, db=db_session, today=TODAY)] == [10.0]
    # прошедший старт гаснет при следующей записи (lazy done), active его не отдаёт и до этого
    later = NOW + timedelta(days=70)
    assert races.active_races(user.id, db=db_session, today=later.date()) == []
    races.record_race(RaceReport(status="add", days_ahead=20, distance_km=10.0), user.id, db=db_session, now=later)
    stored = db_session.query(UserModel).filter_by(user_id=user.id).first().params_json["races"]
    assert {r["status"] for r in stored} == {"done", "cancelled", "active"}


def test_record_race_without_distance_asks_and_writes_nothing(db_session):
    user = _unique_user(db_session)
    text = races.record_race(RaceReport(status="add", date="11-15"), user.id, db=db_session, now=NOW)
    assert "На какой дистанции" in text and races.races_state(user.id, db=db_session) == []
    text = races.record_race(RaceReport(status="add", date="2026-01-01", distance_km=10), user.id, db=db_session, now=NOW)
    assert "уже прошла" in text and races.races_state(user.id, db=db_session) == []
    text = races.record_race(RaceReport(status="add", days_ahead=6, distance_km=21.1), user.id, db=db_session, now=NOW)
    assert "уже на этой неделе" in text
    text = races.record_race(RaceReport(status="add", days_ahead=10, distance_km=42.2), user.id, db=db_session, now=NOW)
    assert "через неделю: тейпер" in text


def test_context_block_facts_only():
    block = races.context_block([_race(TODAY + timedelta(days=10), 21.1, "")], TODAY)
    assert block == [{"label": "полумарафон", "date": (TODAY + timedelta(days=10)).isoformat(),
                      "distance_km": 21.1, "days_ahead": 10, "weeks_ahead": 1}]
    assert races.context_block([], TODAY) is None


# --- потолок по дистанции ---

def test_volume_ceiling_by_distance_and_hard_cap():
    assert race_plan.volume_ceiling_km(5.0) == 40.0 and race_plan.volume_ceiling_km(10.0) == 50.0
    assert race_plan.volume_ceiling_km(21.1) == 55.0 and race_plan.volume_ceiling_km(42.2) == 65.0
    assert race_plan.volume_ceiling_km(100.0) <= RACE_VOLUME_HARD_CAP_KM
    assert race_plan.volume_ceiling_km(None) == RACE_VOLUME_DEFAULT_CEILING_KM


# --- goal_for_week: фазы ---

def test_goal_phases_by_weeks_to_race():
    ref, prev = 30.0, 26.0
    no_race = race_plan.goal_for_week([], week_start=MONDAY, prev_km=prev, ref_peak_km=ref)
    assert no_race["phase"] == "base" and no_race["volume_cap_km"] == RACE_VOLUME_DEFAULT_CEILING_KM
    week = race_plan.goal_for_week([_race(MONDAY + timedelta(days=5), 21.1)], week_start=MONDAY, prev_km=prev, ref_peak_km=ref)
    assert week["phase"] == "race_week" and week["hard_days_cap"] == 0
    assert week["volume_cap_km"] == round(max(ref * RACE_WEEK_VOLUME_PCT, 21.1), 1) == 21.1   # марафон/ПМ не влезают в 55 %
    taper = race_plan.goal_for_week([_race(MONDAY + timedelta(days=8), 10.0)], week_start=MONDAY, prev_km=prev, ref_peak_km=ref)
    assert taper["phase"] == "taper" and taper["hard_days_cap"] == 1
    assert taper["volume_cap_km"] == round(ref * RACE_TAPER_VOLUME_PCT, 1)
    build = race_plan.goal_for_week([_race(MONDAY + timedelta(weeks=12), 21.1)], week_start=MONDAY, prev_km=prev, ref_peak_km=ref)
    assert build["phase"] == "build" and build["weeks_to_race"] == 12 and build["hard_days_cap"] is None
    assert build["literature_peak_km"] == 55.0 and build["volume_cap_km"] == 55.0 and not build["peak_capped_by_date"]
    far = race_plan.goal_for_week([_race(MONDAY + timedelta(weeks=RACE_HORIZON_WEEKS + 1), 42.2)], week_start=MONDAY, prev_km=prev, ref_peak_km=ref)
    assert far["phase"] == "base" and far["volume_cap_km"] == RACE_VOLUME_DEFAULT_CEILING_KM   # марафон за горизонтом потолок не задаёт


def test_goal_reachable_peak_capped_by_date_and_multi_race_horizon():
    # 3 недели до ПМ от 26 км: growth_weeks = ceil(2 × 0.75) = 2 → 26 × 1.21 = 31.5 < 55 → честный пик
    g = race_plan.goal_for_week([_race(MONDAY + timedelta(weeks=3), 21.1)], week_start=MONDAY, prev_km=26.0, ref_peak_km=30.0)
    assert g["peak_capped_by_date"] is True and g["reachable_peak_km"] == 31.5 == g["volume_cap_km"]
    # неделя −2 — пиковая, не плоская: growth_weeks ≥ 1
    g2 = race_plan.goal_for_week([_race(MONDAY + timedelta(weeks=2), 10.0)], week_start=MONDAY, prev_km=26.0, ref_peak_km=30.0)
    assert g2["phase"] == "build" and g2["volume_cap_km"] > 26.0
    # 10 км через 6 недель и марафон через 16 → потолок марафона (65), тейпер — от ближайшего
    two = race_plan.goal_for_week([_race(MONDAY + timedelta(weeks=6), 10.0, rid=1),
                                   _race(MONDAY + timedelta(weeks=16), 42.2, rid=2)],
                                  week_start=MONDAY, prev_km=50.0, ref_peak_km=52.0)
    assert two["literature_peak_km"] == 65.0 and two["next_race"]["distance_km"] == 10.0 and two["weeks_to_race"] == 6
    # старт до планируемой недели (уже прошёл) не считается
    past = race_plan.goal_for_week([_race(MONDAY - timedelta(days=1), 10.0)], week_start=MONDAY, prev_km=26.0, ref_peak_km=30.0)
    assert past["phase"] == "base" and past["next_race"] is None
    # без истории объёма в тейпере капа нет (не режем в ноль)
    empty = race_plan.goal_for_week([_race(MONDAY + timedelta(days=8), 10.0)], week_start=MONDAY, prev_km=0.0, ref_peak_km=0.0)
    assert empty["phase"] == "taper" and empty["volume_cap_km"] is None


# --- place_race / header ---

def test_place_race_replaces_day_drops_llm_race_and_eases_day_before():
    items = [WorkoutProposal(workout_type="easy", target_zone=2, duration_min=40, for_days_ahead=1),
             WorkoutProposal(workout_type="tempo", target_zone=4, duration_min=40, for_days_ahead=5,
                             segments=[WorkoutSegment(role="work", amount_value=10, target_zone=4)]),
             WorkoutProposal(workout_type="race", target_zone=4, duration_min=60, for_days_ahead=3),   # чужой race от LLM
             WorkoutProposal(workout_type="long", target_zone=2, duration_min=70, for_days_ahead=6)]
    race = _race(MONDAY + timedelta(days=5), 21.1, "ПМ")
    out, placed = race_plan.place_race(items, race=race, days_ahead=6, allowed=list(range(1, 8)))
    assert placed == 6 and [it.for_days_ahead for it in out] == [1, 5, 6]
    day6 = out[-1]
    assert day6.workout_type == "race" and day6.distance_km == 21.1 and day6.rationale[0] == RACE_RATIONALE
    assert race_plan.is_race_proposal(day6)
    day5 = out[1]
    assert day5.workout_type == "easy" and day5.duration_min == 30 and day5.segments == []   # накануне — лёгкий
    # качество в другой день недели старта — тоже лёгкий, но своей длительности
    mid = [WorkoutProposal(workout_type="interval", target_zone=5, duration_min=50, for_days_ahead=2)]
    out2, _ = race_plan.place_race(mid, race=race, days_ahead=6, allowed=list(range(1, 8)))
    assert out2[0].workout_type == "easy" and out2[0].duration_min == 50 and out2[0].target_zone == 2
    # тест ПАНО (race с TEST_RATIONALE) не считается чужим race — остаётся
    kept, _ = race_plan.place_race([lthr_field.test_proposal(2)], race=race, days_ahead=6, allowed=list(range(1, 8)))
    assert [it.for_days_ahead for it in kept] == [2, 6]
    # день вне окна → без изменений и None
    same, none = race_plan.place_race(items, race=race, days_ahead=6, allowed=[1, 2, 3])
    assert none is None and len(same) == len(items)


def test_header_suffix_and_mark_race():
    nxt = {"label": "ПМ", "date": "2026-11-15", "distance_km": 21.1}
    assert race_plan.header_suffix({"phase": "race_week", "next_race": nxt}) == "неделя старта (ПМ 15.11)"
    assert race_plan.header_suffix({"phase": "taper", "next_race": nxt}) == "тейпер · старт ПМ 15.11"
    assert race_plan.header_suffix({"phase": "build", "next_race": nxt, "weeks_to_race": 3, "peak_capped_by_date": True,
                                    "reachable_peak_km": 31.5, "literature_peak_km": 55.0}) \
        == "до старта 3 нед (ПМ 15.11) · пик к старту ~32 км (литература 55)"
    assert race_plan.header_suffix({"phase": "maintenance", "volume_cap_km": 55.0}) == "объём на потолке ~55 км — прогресс в качество"
    assert race_plan.header_suffix({"phase": "base"}) is None and race_plan.header_suffix(None) is None
    p = Prescription(safety=SafetyVerdict(), workout_type="easy", when=TODAY, target={"max_zone": 2})
    races.mark_race(p, race_plan.race_proposal(_race(TODAY, 21.1, "ПМ"), 0), _race(TODAY, 21.1, "ПМ"))
    assert p.target["race"] == {"id": 1, "label": "ПМ", "distance_km": 21.1}   # маркер и на понижённый тип
    p2 = Prescription(safety=SafetyVerdict(), workout_type="easy", when=TODAY, target={})
    races.mark_race(p2, WorkoutProposal(workout_type="easy"), _race(TODAY))
    assert "race" not in p2.target
