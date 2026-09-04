# Тесты детерминированного планирования недели (Weekly planning math tests)
from datetime import timedelta

from src.coach import planning
from src.coach.config import CYCLE_3_1, LOAD_PROGRESSION
from src.domain.models.base import utcnow
from src.models import UserModel
from tests.coach.conftest import _unique_user
from tests.helpers import build_training_session


def _week_of_km(db, user_id, km, weeks_ago):
    """Одна тренировка на km в неделе N недель назад (one run per past week)."""
    build_training_session(db, user_id, total_distance_km=km,
                           begin_ts=utcnow() - timedelta(weeks=weeks_ago))


def _set_meta(db, user_id, **meta):
    um = db.query(UserModel).filter(UserModel.user_id == user_id).first()
    if um is None:
        um = UserModel(user_id=user_id, params_json={})
        db.add(um)
    params = dict(um.params_json or {})
    params["week_plan"] = meta
    um.params_json = params
    db.commit()


def test_targets_build_progression_capped(db_session):
    """Build-неделя: target ≤ prev_km × (1 + 10%)."""
    user = _unique_user(db_session)
    _week_of_km(db_session, user.id, 20.0, 2)
    _week_of_km(db_session, user.id, 22.0, 1)
    t = planning.week_targets(user.id, db=db_session)
    pct = LOAD_PROGRESSION["max_weekly_increase_pct"] / 100
    assert t["phase"] == "build"
    assert abs(t["target_km"] - 22.0 * (1 + pct)) < 0.2
    assert t["low_history"] is False
    # потолки от target_km
    assert t["quality_z4_km_max"] <= t["target_km"] * 0.08 + 0.11
    assert t["long_run_km_max"] == round(t["target_km"] * 0.30, 1)
    assert t["hard_days_max"] == 1


def test_targets_deload_on_week_4(db_session):
    """4-я неделя мезоцикла → deload от пика (guide 60: 75%)."""
    user = _unique_user(db_session)
    _week_of_km(db_session, user.id, 25.0, 2)
    _week_of_km(db_session, user.id, 28.0, 1)
    _set_meta(db_session, user.id, mesocycle_week=3, phase="build",
              week_start="2000-01-01", last_build_km=28.0)
    t = planning.week_targets(user.id, db=db_session)
    assert t["mesocycle_week"] == 4
    assert t["phase"] == "deload"
    assert abs(t["target_km"] - 28.0 * CYCLE_3_1["deload_volume_pct"]) < 0.2


def test_targets_post_deload_resumes_from_build(db_session):
    """Первая build-неделя после deload — от последней build-недели, не от deload."""
    user = _unique_user(db_session)
    _week_of_km(db_session, user.id, 30.0, 2)
    _week_of_km(db_session, user.id, 21.0, 1)   # факт deload-недели
    _set_meta(db_session, user.id, mesocycle_week=4, phase="deload",
              week_start="2000-01-01", last_build_km=30.0)
    t = planning.week_targets(user.id, db=db_session)
    assert t["mesocycle_week"] == 1
    assert t["phase"] == "build"
    assert t["target_km"] == 30.0                # база цикла, не 21 × 1.1


def test_mesocycle_replan_idempotent(db_session):
    """Replan той же недели не двигает счётчик мезоцикла."""
    user = _unique_user(db_session)
    _week_of_km(db_session, user.id, 20.0, 1)
    t1 = planning.week_targets(user.id, db=db_session)
    planning.advance_mesocycle(user.id, db=db_session, targets=t1)
    t2 = planning.week_targets(user.id, db=db_session)   # та же неделя
    assert t2["mesocycle_week"] == t1["mesocycle_week"]
    assert t2["week_start"] == t1["week_start"]


def test_targets_low_history_conservative(db_session):
    """< 2 недель истории → без прогрессии, low_history=true."""
    user = _unique_user(db_session)
    _week_of_km(db_session, user.id, 15.0, 1)
    t = planning.week_targets(user.id, db=db_session)
    assert t["low_history"] is True
    assert t["target_km"] == 15.0


def test_week_plan_review_done_missed(db_session):
    """Сверка недели: выполненные (linked) и пропущенные плановые дни."""
    from src.models import Recommendation

    user = _unique_user(db_session)
    today = planning.user_now(user).date()
    week_start = today - timedelta(days=today.weekday())
    s = build_training_session(db_session, user.id, total_distance_km=8.0,
                               begin_ts=utcnow())
    done_rec = Recommendation(user_id=user.id, for_date=today,
                              workout_type="easy", status="confirmed",
                              linked_session_id=s.id)
    missed_rec = Recommendation(user_id=user.id,
                                for_date=max(week_start, today - timedelta(days=1)),
                                workout_type="long", status="planned")
    db_session.add_all([done_rec, missed_rec])
    db_session.commit()

    review = planning.week_plan_review(user.id, db=db_session)
    assert review is not None
    assert review["done"] == 1
    if missed_rec.for_date < today:                       # пн — дни совпадают
        assert review["missed"] == 1
    assert planning.week_plan_review(_unique_user(db_session).id,
                                     db=db_session) is None


def test_run_days_cap_adaptive():
    """Потолок беговых дней: max за прошлые недели + 1, в границах [3, 6]."""
    assert planning.run_days_cap([]) == 3                 # нет истории → пол
    assert planning.run_days_cap([1]) == 3                # 1+1 < пола
    assert planning.run_days_cap([2, 4]) == 5             # 4+1 (решение владельца 02.09)
    assert planning.run_days_cap([6, 5]) == 6             # потолок
    assert planning.run_days_cap([7]) == 6


def test_week_targets_expose_run_days(db_session):
    """week_targets отдаёт run_days_max/rest_days_min — факты для LLM."""
    user = _unique_user(db_session)
    for w in (1, 2):
        for _ in range(4):
            _week_of_km(db_session, user.id, 5.0, w)
    t = planning.week_targets(user.id, db=db_session)
    assert t["run_days_max"] == 5
    assert t["rest_days_min"] == 2


def test_enforce_run_days_drops_shortest_easy():
    """Обрезка до потолка: уходят самые короткие лёгкие, каркас (long/tempo) остаётся."""
    from src.coach.contracts import WorkoutProposal as WP

    items = [WP(workout_type="easy", target_zone=2, duration_min=30, for_days_ahead=1),
             WP(workout_type="tempo", target_zone=3, duration_min=45, for_days_ahead=2),
             WP(workout_type="recovery", target_zone=1, duration_min=25, for_days_ahead=3),
             WP(workout_type="easy", target_zone=2, duration_min=40, for_days_ahead=4),
             WP(workout_type="easy", target_zone=2, duration_min=35, for_days_ahead=5),
             WP(workout_type="easy", target_zone=2, duration_min=50, for_days_ahead=6),
             WP(workout_type="long", target_zone=2, duration_min=70, for_days_ahead=7)]
    kept, dropped = planning.enforce_run_days(items, 5)
    assert dropped == 2
    assert [it.for_days_ahead for it in kept] == [1, 2, 4, 5, 7] or \
           [it.for_days_ahead for it in kept] == [2, 4, 5, 6, 7]
    assert {it.workout_type for it in kept} >= {"tempo", "long"}
    assert not any(it.duration_min == 25 for it in kept)   # самый короткий ушёл первым
    same, zero = planning.enforce_run_days(items[:4], 5)
    assert zero == 0 and same == items[:4]


def test_supersede_future_rows_only_unlinked_future(db_session):
    """Гасятся только будущие строки без факта; прошлые и связанные — нетронуты."""
    from src.models import Recommendation

    user = _unique_user(db_session)
    today = planning.user_now(user).date()
    s = build_training_session(db_session, user.id, total_distance_km=5.0,
                               begin_ts=utcnow() + timedelta(days=2))
    future = Recommendation(user_id=user.id, for_date=today + timedelta(days=1),
                            workout_type="easy", status="planned")
    past = Recommendation(user_id=user.id, for_date=today - timedelta(days=1),
                          workout_type="easy", status="planned")
    linked = Recommendation(user_id=user.id, for_date=today + timedelta(days=2),
                            workout_type="long", status="planned", linked_session_id=s.id)
    db_session.add_all([future, past, linked])
    db_session.commit()

    n = planning.supersede_future_rows(user.id, db=db_session,
                                       from_date=today + timedelta(days=1))
    assert n == 1
    for r in (future, past, linked):
        db_session.refresh(r)
    assert future.status == "superseded"
    assert past.status == "planned" and linked.status == "planned"


def test_plan_window_sunday_and_midweek():
    """Вс → следующая неделя 1..7; будни → остаток текущей: с 0 (не бегали) или 1 (бегали)."""
    from datetime import date

    from src.coach.planning_window import plan_window

    assert plan_window(date(2026, 8, 30), False) == (date(2026, 8, 31), 1, 7)   # вс
    assert plan_window(date(2026, 8, 30), True) == (date(2026, 8, 31), 1, 7)
    assert plan_window(date(2026, 9, 2), False) == (date(2026, 8, 31), 0, 4)    # ср, не бегали
    assert plan_window(date(2026, 9, 2), True) == (date(2026, 8, 31), 1, 4)     # ср, бегали
    assert plan_window(date(2026, 9, 5), False) == (date(2026, 8, 31), 0, 1)    # сб


def test_week_done_counts_by_local_date_and_quality(db_session):
    """week_done: км/пробежки недели по локальной дате, качество по пульсу, «бегали сегодня»."""
    from datetime import datetime, timezone

    from src.coach.planning_window import monday_of, week_done

    user = _unique_user(db_session)
    today = planning.user_now(user).date()
    monday = monday_of(today)
    anchor = datetime.combine(monday, datetime.min.time(), tzinfo=timezone.utc)
    build_training_session(db_session, user.id, total_distance_km=5.4, training_type="easy",
                           avg_heart_rate=137, begin_ts=anchor + timedelta(hours=9))
    build_training_session(db_session, user.id, total_distance_km=6.0, training_type="interval",
                           avg_heart_rate=165, begin_ts=anchor + timedelta(hours=9)
                           + timedelta(days=(today - monday).days))            # сегодня
    build_training_session(db_session, user.id, total_distance_km=9.0, training_type="long",
                           begin_ts=anchor - timedelta(days=3))                # прошлая неделя

    done = week_done(user.id, db=db_session, week_start=monday, today=today)
    assert done["runs"] == 2 and abs(done["km"] - 11.4) < 0.05
    assert done["quality_runs"] == 1                       # interval — всегда качество
    assert done["trained_today"] is True


def test_week_targets_midweek_exposes_remaining(db_session):
    """Среди недели: plan_scope=rest_of_week, окно, remaining_* с вычетом сделанного."""
    from datetime import datetime, timezone

    from src.coach.planning_window import monday_of

    user = _unique_user(db_session)
    real_today = planning.user_now(user).date()
    wed = real_today + timedelta(days=((2 - real_today.weekday()) % 7 or 7))   # будущая среда
    monday = monday_of(wed)
    anchor = datetime.combine(monday, datetime.min.time(), tzinfo=timezone.utc)
    for w in (1, 2):                                                           # история: 4 пробежки/нед
        for _ in range(4):
            _week_of_km(db_session, user.id, 5.0, w)
    build_training_session(db_session, user.id, total_distance_km=5.0, training_type="easy",
                           avg_heart_rate=135, begin_ts=anchor + timedelta(hours=9))   # пн

    t = planning.week_targets(user.id, db=db_session, today=wed)
    assert t["plan_scope"] == "rest_of_week"
    assert t["week_start"] == monday.isoformat()
    assert t["days_ahead_allowed"] == [0, 1, 2, 3, 4]      # в среду не бегали
    assert t["done_runs"] == 1 and abs(t["done_km"] - 5.0) < 0.05
    assert t["remaining_run_days_max"] == t["run_days_max"] - 1
    assert abs(t["remaining_km"] - max(0.0, t["target_km"] - 5.0)) < 0.05

    sunday = monday - timedelta(days=1)
    full = planning.week_targets(user.id, db=db_session, today=sunday)
    assert full["plan_scope"] == "week" and full["days_ahead_allowed"] == list(range(1, 8))
    assert full["done_km"] == 0.0 and full["remaining_km"] == full["target_km"]


def test_latest_rows_for_dates_skips_superseded(db_session):
    """Последняя действующая строка на дату; superseded не видна (для строки «было: …»)."""
    from datetime import date

    from src.models import Recommendation

    user = _unique_user(db_session)
    d = date(2026, 9, 6)
    db_session.add_all([
        Recommendation(user_id=user.id, for_date=d, workout_type="long", status="proposed",
                       volume_json={"duration_min": 80.0}),
        Recommendation(user_id=user.id, for_date=d, workout_type="easy", status="superseded",
                       volume_json={"duration_min": 30.0}),
    ])
    db_session.commit()
    rows = planning.latest_rows_for_dates(user.id, db=db_session, dates=[d, date(2026, 9, 5)])
    assert set(rows) == {d} and rows[d].workout_type == "long"
    assert planning.latest_rows_for_dates(user.id, db=db_session, dates=[]) == {}


def test_week_plan_review_include_today_counts_missed(db_session):
    """Отчёт вс 19:00: сегодняшний невыполненный плановый день — пропущен (include_today)."""
    from src.models import Recommendation
    from src.utils.timeutils import user_now

    user = _unique_user(db_session)
    today = user_now(user).date()
    db_session.add(Recommendation(user_id=user.id, for_date=today, workout_type="easy",
                                  status="planned", volume_json={"duration_min": 30.0}))
    db_session.commit()
    week_start = today - timedelta(days=today.weekday())
    default = planning.week_plan_review(user.id, db=db_session, week_start=week_start)
    closing = planning.week_plan_review(user.id, db=db_session, week_start=week_start,
                                        include_today=True)
    assert default["missed"] == 0 and closing["missed"] == 1
    assert closing["planned"] == 1 and closing["week_start"] == week_start.isoformat()


def test_cancel_days_marks_athlete_unavailable(db_session):
    """cancel_days пишет маркер в proposal_json.rationale; blocked_by_unavailable его видит,
    reopen_days гасит; строка отдыха без маркера не блокирует."""
    from datetime import date as _date

    from src.coach.state import assess_state
    from src.coach.turn_context import is_athlete_unavailable
    from src.models import Recommendation
    from src.utils.timeutils import user_now

    user = _unique_user(db_session)
    now = user_now(user)
    state = assess_state(user.id, db=db_session)
    planning.cancel_days([1], user.id, state, db=db_session, now=now)
    when = now.date() + timedelta(days=1)
    row = db_session.query(Recommendation).filter_by(user_id=user.id, for_date=when).one()
    assert is_athlete_unavailable(row) and row.workout_type == "rest"
    assert "бегать не сможешь" in planning.blocked_by_unavailable(user.id, db=db_session, when=when)
    assert planning.blocked_by_unavailable(user.id, db=db_session,
                                           when=when + timedelta(days=1)) is None
    line = planning.reopen_days([1], user.id, db=db_session, now=now)
    assert "Снял отдых" in line
    db_session.refresh(row)
    assert row.status == "superseded"
    assert planning.reopen_days([1], user.id, db=db_session, now=now) == ""


def test_week_done_uses_effective_type(db_session):
    """week_done считает качество по effective_training_type (override учитывается)."""
    from src.coach.planning_window import week_done
    from src.utils.timeutils import user_now

    user = _unique_user(db_session)
    today = user_now(user).date()
    build_training_session(db_session, user.id, training_type="easy", avg_heart_rate=130,
                           training_type_override="interval", begin_ts=utcnow())
    done = week_done(user.id, db=db_session, week_start=today - timedelta(days=today.weekday()),
                     today=today)
    assert done["runs"] == 1 and done["quality_runs"] == 1
