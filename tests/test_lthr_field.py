# Полевой ПАНО (M3.2, 12.09.2026): хранение в params_json, приоритет над Coros в latest_lthr,
# is_due по статусу, протокол теста и его размещение в плане. Диапазон chat_id 85xxx (см. docs/TESTING.md).
from datetime import date, datetime, timedelta, timezone

from src.coach import lthr_field
from src.coach.contracts import WorkoutProposal, WorkoutSegment
from src.coach.training_status import PHASE_STABILIZING, PHASE_STABLE
from src.domain.models.audit import AuditEvent
from src.models import UserModel
from src.services.repositories import field_lthr, latest_lthr
from tests.helpers import build_daily_metrics, make_user

_uid = iter(range(85000, 85999))


def _user(db, max_hr=180):
    n = next(_uid)
    return make_user(db, chat_id=n, email=f"lthr{n}@example.com", max_hr=max_hr)


def test_field_lthr_overrides_coros_and_expires(db_session):
    user = _user(db_session)
    build_daily_metrics(db_session, user.id, metric_date=date.today(), lthr=156)
    assert latest_lthr(user.id, db=db_session) == 156                      # Coros
    now = datetime.now(timezone.utc)
    rec = lthr_field.set_field_lthr(user.id, 161, db=db_session, method="manual", now=now)
    assert rec["value"] == 161 and rec["method"] == "manual"
    assert field_lthr(user.id, db=db_session) == 161
    assert latest_lthr(user.id, db=db_session) == 161                      # поле главнее
    # аудит записан
    ev = db_session.query(AuditEvent).filter(AuditEvent.user_id == user.id).order_by(
        AuditEvent.id.desc()).first()
    assert ev is not None and "lthr_field" in str(ev.metadata_json)
    # устарело (> LTHR_FIELD_MAX_AGE_DAYS) → снова Coros
    um = db_session.query(UserModel).filter(UserModel.user_id == user.id).first()
    params = dict(um.params_json)
    params["lthr_field"] = {**params["lthr_field"],
                            "measured_at": (date.today() - timedelta(days=200)).isoformat()}
    um.params_json = params
    db_session.commit()
    assert field_lthr(user.id, db=db_session) is None
    assert latest_lthr(user.id, db=db_session) == 156


def test_valid_value_and_is_due(db_session):
    user = _user(db_session, max_hr=180)
    assert lthr_field.valid_value(158, 180) and not lthr_field.valid_value(185, 180)
    assert not lthr_field.valid_value(90, 180) and lthr_field.valid_value(158, None)
    assert lthr_field.is_due(user.id, db=db_session, phase=PHASE_STABLE) is True
    assert lthr_field.is_due(user.id, db=db_session, phase=PHASE_STABILIZING) is False
    lthr_field.set_field_lthr(user.id, 158, db=db_session, method="test30",
                              now=datetime.now(timezone.utc))
    assert lthr_field.is_due(user.id, db=db_session, phase=PHASE_STABLE) is False


def test_test_proposal_protocol_and_place_test():
    p = lthr_field.test_proposal(3)
    assert p.workout_type == "race" and p.for_days_ahead == 3 and p.duration_min == 55
    assert [s.role for s in p.segments] == ["warmup", "work", "cooldown"]
    assert p.segments[1].amount_value == 30 and p.segments[1].target_zone == 4
    assert "30 мин" in p.segments[1].effort
    assert lthr_field.is_test_proposal(p) and not lthr_field.is_test_proposal(None)

    easy = WorkoutProposal(workout_type="easy", duration_min=40, for_days_ahead=1)
    tempo = WorkoutProposal(workout_type="tempo", target_zone=3, duration_min=40, for_days_ahead=3)
    long_ = WorkoutProposal(workout_type="long", duration_min=70, for_days_ahead=6)
    out, day = lthr_field.place_test([easy, tempo, long_])
    assert day == 3 and out[1].workout_type == "race" and out[0] is easy and out[2] is long_
    # нет качественных: первый лёгкий с for_days_ahead ≥ quality_from_day, не длительная
    strides = WorkoutProposal(workout_type="easy", duration_min=40, for_days_ahead=2,
                              segments=[WorkoutSegment(role="work", amount_kind="sec", amount_value=20)])
    easy4 = WorkoutProposal(workout_type="easy", duration_min=40, for_days_ahead=4)
    out, day = lthr_field.place_test([easy, strides, easy4, long_], quality_from_day=2)
    assert day == 4 and out[2].workout_type == "race" and out[1] is strides
    out, day = lthr_field.place_test([long_], quality_from_day=None)
    assert day is None and out == [long_]


def test_zone_ceilings_text():
    txt = lthr_field.zone_ceilings_text(180, 158)
    assert txt.startswith("Z1 до 127") and "Z2 до 140" in txt


# ---------- расчёт по треку и insights (M3.2, шаг 5c) ----------

def _test_track(work_hr=160, warm_hr=130, cool_hr=120, drift=0, dt=10.0, gap_min=None):
    """55 мин: разминка 15 (warm_hr) → работа 30 (work_hr, линейный дрейф с 10-й мин) → заминка 10."""
    times, hrs, dists = [], [], []
    t, d = 0.0, 0.0
    while t <= 55 * 60:
        m = t / 60.0
        if m < 15:
            hr, pace = warm_hr, 7.0
        elif m < 45:
            frac = max(0.0, min(1.0, (m - 25) / 20.0))     # дрейф между 10-й и 30-й минутой отрезка
            hr, pace = work_hr + drift * frac, 5.5
        else:
            hr, pace = cool_hr, 7.5
        if gap_min is not None and gap_min <= m < gap_min + 3:
            hr = None                                    # дропаут пульса 3 минуты
        times.append(t); hrs.append(None if hr is None else int(round(hr)))
        d += 1000.0 / (pace * 60.0) * dt; dists.append(d)
        t += dt
    return times, hrs, dists


def test_lthr_from_test_finds_steady_block():
    from src.analysis.lthr_test import lthr_from_test
    times, hrs, dists = _test_track(work_hr=160, drift=3)
    out = lthr_from_test(times, hrs, dists, max_hr=185)
    assert out["available"] and out["quality"] == "ok"
    assert 160 <= out["lthr"] <= 163                     # средний пульс последних 20 мин отрезка
    assert 14.5 <= out["window_start_min"] <= 16.0        # окно нашло рабочий отрезок
    assert out["drift_bpm"] is not None and out["drift_bpm"] <= 8
    assert 320 <= out["pace_s_km"] <= 340                 # ~5:30/км


def test_lthr_from_test_rough_and_degradations():
    from src.analysis.lthr_test import lthr_from_test
    times, hrs, dists = _test_track(work_hr=150, drift=15)
    out = lthr_from_test(times, hrs, dists, max_hr=185)
    assert out["available"] and out["quality"] == "rough" and out["drift_bpm"] > 8
    # слишком короткая запись
    assert lthr_from_test(times[:100], hrs[:100], dists[:100], max_hr=185)["reason"] == "too_short"
    # нет пульса
    assert lthr_from_test(times, [None] * len(times), dists, max_hr=185)["reason"] == "no_hr"
    # число вне разумного (выше max_hr)
    assert lthr_from_test(times, hrs, dists, max_hr=140)["reason"] == "insane_value"
    # дропаут 3 мин в первой трети отрезка → покрытие окна 27/30 = 0.9, последние 20 мин целы
    times, hrs, dists = _test_track(work_hr=160, gap_min=17)
    assert lthr_from_test(times, hrs, dists, max_hr=185)["available"]
    # дропаут внутри последних 20 минут → покрытие 17/20 < 0.9 → результата нет
    times, hrs, dists = _test_track(work_hr=160, gap_min=35)
    assert lthr_from_test(times, hrs, dists, max_hr=185)["reason"] == "low_hr_coverage"


def test_insights_lthr_block_only_on_test_day(db_session):
    from src.analysis.utils import serialize_trackpoints
    from src.services.workout_insights import compute_workout_metrics
    from tests.helpers import build_training_session
    user = _user(db_session)
    times, hrs, dists = _test_track()
    from datetime import datetime as _dt
    t0 = _dt(2026, 9, 20, 8, 0, tzinfo=timezone.utc)
    tps = [{"time": (t0 + timedelta(seconds=t)).isoformat(), "hr": h, "dist": d, "alt": 150.0,
            "lat": 55.75, "lon": 37.62, "cad": 170} for t, h, d in zip(times, hrs, dists)]
    s = build_training_session(db_session, user.id, training_type="race", avg_heart_rate=150,
                               duration_minutes=55.0, total_distance_km=round(dists[-1] / 1000, 2),
                               trackpoints_json=serialize_trackpoints(tps), begin_ts=t0)
    plain = compute_workout_metrics(s, max_hr=185, lthr=156, plan={"type": "race", "lthr_test": False})
    assert plain["lthr_test"] == {"available": False, "reason": "not_a_test_day"}
    test = compute_workout_metrics(s, max_hr=185, lthr=156, plan={"type": "race", "lthr_test": True})
    assert test["lthr_test"]["available"] and 158 <= test["lthr_test"]["lthr"] <= 162


def test_plan_for_session_carries_test_marker(db_session):
    from datetime import datetime as _dt
    from src.models import Recommendation
    from src.services.workout_insights_context import _plan_for_session
    from tests.helpers import build_training_session
    user = _user(db_session)
    day = date.today()
    db_session.add(Recommendation(user_id=user.id, for_date=day, workout_type="race", status="planned",
                                  target_json={"max_zone": 4, "lthr_test": True}, volume_json={"duration_min": 55}))
    db_session.commit()
    s = build_training_session(db_session, user.id, training_type="race",
                               begin_ts=_dt.combine(day, _dt.min.time(), tzinfo=timezone.utc).replace(hour=9))
    plan = _plan_for_session(user.id, s, db=db_session)
    assert plan and plan["lthr_test"] is True and plan["type"] == "race"


def test_review_followup_sends_card_with_buttons(db_session, monkeypatch):
    from src.coach import orchestrator
    from src.services import telegram_notify as tn
    from src.services import workout_insights as wi
    user = _user(db_session)
    sent = []
    monkeypatch.setattr(tn, "telegram_notify",
                        lambda user_id, text, reply_markup=None: sent.append((text, reply_markup)))
    monkeypatch.setattr(wi, "get_or_compute",
                        lambda uid, sid, *, db: {"lthr_test": {"available": True, "lthr": 159, "quality": "ok",
                                                               "pace_s_km": 330, "drift_bpm": 2.0}})
    build_daily_metrics(db_session, user.id, metric_date=date.today(), lthr=156)
    text = orchestrator.lthr_test_followup(user.id, 1, db=db_session)
    assert text and "159" in text and "якорь 156" in text and "5:30/км" in text
    assert sent and sent[0][1]["inline_keyboard"][0][0]["callback_data"] == "lthr:set:159"
    # не тест — тишина
    monkeypatch.setattr(wi, "get_or_compute", lambda uid, sid, *, db: {"lthr_test": {"available": False}})
    assert orchestrator.lthr_test_followup(user.id, 1, db=db_session) is None and len(sent) == 1
