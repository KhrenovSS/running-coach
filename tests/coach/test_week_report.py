# Недельный отчёт C8.1: детерминированные числа недели и предвыбор сигналов
# (Weekly report numbers & pre-selected signals) — src/coach/week_report.py
from datetime import date, datetime, time, timedelta, timezone

from src.coach.week_report import compute_week_report
from src.models import Recommendation, TrainingFeedback, WorkoutInsight
from tests.coach.conftest import _unique_user
from tests.helpers import build_training_session


def _last_full_week():
    """(week_start, sunday) — прошлая полная неделя пн–вс относительно сегодня (UTC)."""
    today = datetime.now(timezone.utc).date()
    ws = today - timedelta(days=today.weekday()) - timedelta(days=7)
    return ws, ws + timedelta(days=6)


def _at(d: date, hh: int = 8, mm: int = 0) -> datetime:
    return datetime.combine(d, time(hh, mm), tzinfo=timezone.utc)


def _insight(db, user_id, session_id, **computed):
    db.add(WorkoutInsight(user_id=user_id, session_id=session_id, status="done",
                          computed_json=computed))


def test_buckets_by_local_date_across_midnight(db_session):
    """Пробежка в вс 22:30 UTC = пн 01:30 МСК → уходит в СЛЕДУЮЩУЮ неделю (не UTC-корзина)."""
    user = _unique_user(db_session)                       # Europe/Moscow
    ws, sunday = _last_full_week()
    # вс 22:30 UTC перед началом недели → локально пн ws → в этой неделе
    build_training_session(db_session, user.id, total_distance_km=5.0, duration_minutes=30,
                           training_type="easy", begin_ts=_at(ws - timedelta(days=1), 22, 30))
    # вс 22:30 UTC в конце недели → локально пн следующей → НЕ в этой неделе
    build_training_session(db_session, user.id, total_distance_km=7.0, duration_minutes=40,
                           training_type="easy", begin_ts=_at(sunday, 22, 30))
    r = compute_week_report(user.id, db=db_session, week_start=ws, today=sunday)
    assert r["this"]["runs"] == 1 and r["this"]["km"] == 5.0
    assert r["week_in_progress"] is False
    assert len(r["series"]) == 6 and r["series"][-1]["week_start"] == ws.isoformat()


def test_easy_share_from_zones_with_segment_fallback_and_load(db_session):
    """Доля лёгкого ВРЕМЕНИ: посекундные зоны из разбора + сегментный fallback; баллы нагрузки."""
    user = _unique_user(db_session)
    ws, sunday = _last_full_week()
    s1 = build_training_session(db_session, user.id, total_distance_km=6.0, duration_minutes=40,
                                training_type="easy", begin_ts=_at(ws))
    _insight(db_session, user.id, s1.id, time_in_zones={
        "available": True, "minutes": {"z1": 10.0, "z2": 20.0, "z3": 10.0, "z4": 0.0, "z5": 0.0}})
    # без разбора: сегмент avg_hr 130 при max_hr 177 → Z2, 30 мин
    build_training_session(db_session, user.id, total_distance_km=5.0, duration_minutes=30,
                           training_type="easy", begin_ts=_at(ws + timedelta(days=2)),
                           segments_json=[{"avg_hr": 130, "duration_min": 30.0}])
    db_session.commit()
    r = compute_week_report(user.id, db=db_session, week_start=ws, today=sunday)
    this = r["this"]
    assert this["easy_time_share"] == round(60 / 70, 2)          # (10+20+30)/70
    assert this["load_points"] == round(10 * 0.2 + 20 * 0.25 + 10 * 0.5 + 30 * 0.25)
    assert this["runs"] == 2 and this["km"] == 11.0
    assert this["long_run_share"] == round(6.0 / 11.0, 2)


def test_efficiency_mean_and_highlight(db_session):
    """Экономичность = среднее delta_bpm разборов; ≤ −2 при n≥2 → highlight efficiency_gain."""
    user = _unique_user(db_session)
    ws, sunday = _last_full_week()
    for i, delta in enumerate((-3.0, -1.0)):
        s = build_training_session(db_session, user.id, total_distance_km=5.0,
                                   duration_minutes=30, training_type="easy",
                                   begin_ts=_at(ws + timedelta(days=i)))
        _insight(db_session, user.id, s.id, hr_vs_baseline={"delta_bpm": delta})
    db_session.commit()
    r = compute_week_report(user.id, db=db_session, week_start=ws, today=sunday)
    assert r["this"]["efficiency_delta_bpm"] == -2.0 and r["this"]["efficiency_n"] == 2
    assert "efficiency_gain" in {h["key"] for h in r["highlights"]}
    assert "efficiency" not in " ".join(r["missing"])


def test_concerns_volume_jump_long_run_and_pain(db_session):
    """Скачок объёма > 10%, длительная > 30% недели, день с болью → concerns."""
    user = _unique_user(db_session)
    ws, sunday = _last_full_week()
    prev_ws = ws - timedelta(days=7)
    build_training_session(db_session, user.id, total_distance_km=10.0, duration_minutes=60,
                           training_type="easy", begin_ts=_at(prev_ws))
    long = build_training_session(db_session, user.id, total_distance_km=13.0,
                                  duration_minutes=80, training_type="long", begin_ts=_at(ws))
    build_training_session(db_session, user.id, total_distance_km=2.0, duration_minutes=12,
                           training_type="easy", begin_ts=_at(ws + timedelta(days=3)))
    db_session.add(TrainingFeedback(user_id=user.id, session_id=long.id, rating=6,
                                    pain_level=3, created_at=_at(ws, 10)))
    db_session.commit()
    r = compute_week_report(user.id, db=db_session, week_start=ws, today=sunday)
    keys = {c["key"] for c in r["concerns"]}
    assert {"volume_jump", "long_run_share_high", "pain_days"} <= keys
    assert r["prev"]["km"] == 10.0 and r["this"]["pain_days"] == 1
    assert r["avg_prev"] == {"km": 10.0, "weeks": 1}
    assert not any(h["key"] == "volume_step_ok" for h in r["highlights"])


def test_plan_complete_highlight_and_empty_week(db_session):
    """План выполнен полностью → highlight; неделя без пробежек → concern no_runs."""
    user = _unique_user(db_session)
    ws, sunday = _last_full_week()
    s = build_training_session(db_session, user.id, total_distance_km=5.0, duration_minutes=30,
                               training_type="easy", begin_ts=_at(ws))
    db_session.add(Recommendation(user_id=user.id, for_date=ws, workout_type="easy",
                                  status="confirmed", linked_session_id=s.id))
    db_session.commit()
    adherence = {"planned": 1, "done": 1, "missed": 0, "adjusted": 0}
    r = compute_week_report(user.id, db=db_session, week_start=ws, today=sunday,
                            adherence=adherence)
    assert "plan_complete" in {h["key"] for h in r["highlights"]}

    empty = compute_week_report(user.id, db=db_session, week_start=ws + timedelta(days=7),
                                today=sunday + timedelta(days=7))
    assert empty["this"]["runs"] == 0 and empty["highlights"] == []
    assert [c["key"] for c in empty["concerns"]] == ["no_runs"]
    in_progress = compute_week_report(user.id, db=db_session, week_start=ws + timedelta(days=7),
                                      today=ws + timedelta(days=9))
    assert in_progress["week_in_progress"] is True and in_progress["concerns"] == []


def test_load_ratio_prefers_watch_ati_cti(db_session):
    """Острая/хроническая — ATI/CTI часов на конец недели; без них и без нагрузки → None."""
    from tests.helpers import build_daily_metrics

    user = _unique_user(db_session)
    ws, sunday = _last_full_week()
    none = compute_week_report(user.id, db=db_session, week_start=ws, today=sunday)
    assert none["acwr"] is None and any(m.startswith("acwr") for m in none["missing"])
    build_daily_metrics(db_session, user.id, metric_date=sunday, ati=44.0, cti=40.0)
    r = compute_week_report(user.id, db=db_session, week_start=ws, today=sunday)
    assert r["acwr"] == 1.1


def test_week_report_monotony_concern(db_session):
    """#308: 6 одинаковых дней недели (один отдых) → monotony ≈ 2.45 и concern monotony_high."""
    user = _unique_user(db_session)
    ws, sunday = _last_full_week()
    for i in range(6):
        s = build_training_session(db_session, user.id, total_distance_km=5.0, duration_minutes=35,
                                   training_type="easy", begin_ts=_at(ws + timedelta(days=i)))
        _insight(db_session, user.id, s.id, time_in_zones={
            "available": True, "minutes": {"z1": 5.0, "z2": 30.0, "z3": 0.0, "z4": 0.0, "z5": 0.0}})
    db_session.commit()
    r = compute_week_report(user.id, db=db_session, week_start=ws, today=sunday)
    assert r["this"]["trained_days"] == 6 and r["this"]["monotony"] > 2.0
    assert "monotony_high" in {c["key"] for c in r["concerns"]}
