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
    from src.coach.config import long_run_max_pct
    assert t["long_run_km_max"] == round(t["target_km"] * long_run_max_pct(
        t["target_km"], t["run_days_max"]), 1)
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
    # #320: сверяем ПРОШЛУЮ полную неделю — дни фиксированы и всегда в прошлом
    # (в понедельник «сегодня» и «вчера» текущей недели совпадали → строки перекрывались)
    week_start = today - timedelta(days=today.weekday() + 7)
    s = build_training_session(db_session, user.id, total_distance_km=8.0,
                               begin_ts=utcnow() - timedelta(days=today.weekday() + 7))
    done_rec = Recommendation(user_id=user.id, for_date=week_start,
                              workout_type="easy", status="confirmed",
                              linked_session_id=s.id)
    missed_rec = Recommendation(user_id=user.id, for_date=week_start + timedelta(days=1),
                                workout_type="long", status="planned")
    db_session.add_all([done_rec, missed_rec])
    db_session.commit()

    review = planning.week_plan_review(user.id, db=db_session, week_start=week_start)
    assert review is not None
    assert review["done"] == 1
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
    # #319: вечером (час ≥ PLAN_TODAY_CUTOFF_HOUR) день 0 уходит даже без пробежки
    from src.coach.config import PLAN_TODAY_CUTOFF_HOUR
    assert plan_window(date(2026, 9, 2), False, PLAN_TODAY_CUTOFF_HOUR) == (date(2026, 8, 31), 1, 4)
    assert plan_window(date(2026, 9, 2), False, PLAN_TODAY_CUTOFF_HOUR - 1) == (date(2026, 8, 31), 0, 4)
    assert plan_window(date(2026, 9, 5), False, 21) == (date(2026, 8, 31), 1, 1)   # сб вечер → только вс
    assert plan_window(date(2026, 8, 30), False, 21) == (date(2026, 8, 31), 1, 7)  # вс — как раньше


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


def test_week_targets_long_run_hold_after_share_flag(db_session):
    """#289: на прошлой неделе long_run_share_high → потолок длительной = её факт, не растёт."""
    from src.models import WorkoutInsight

    user = _unique_user(db_session)
    build_training_session(db_session, user.id, total_distance_km=15.0,
                           begin_ts=utcnow() - timedelta(days=9))
    long = build_training_session(db_session, user.id, total_distance_km=9.0,
                                  training_type="long", begin_ts=utcnow() - timedelta(days=3))
    build_training_session(db_session, user.id, total_distance_km=5.0,
                           begin_ts=utcnow() - timedelta(days=2))
    db_session.add(WorkoutInsight(user_id=user.id, session_id=long.id, status="done",
                                  computed_json={"flags": ["long_run_share_high"]}))
    db_session.commit()
    t = planning.week_targets(user.id, db=db_session)
    assert t["long_run_hold"] is True
    assert t["long_run_km_max"] <= 9.0
    assert t["detraining_return"] is False and t["hard_days_max"] == 1


def test_week_targets_detraining_return_ceiling(db_session):
    """#289: пауза ≥ 14 дней → объём ≤ 65% пика 8 недель, качественных нет."""
    from src.coach.config import DETRAINING_RETURN_VOLUME_PCT

    user = _unique_user(db_session)
    _week_of_km(db_session, user.id, 30.0, 4)
    _week_of_km(db_session, user.id, 24.0, 3)
    # #320: ровно 14 дней (тот же день недели) — сессия не попадает в корзину пиковой недели
    # (15 дней в понедельник = воскресенье 3-й недели назад → пик 24+8 вместо 30)
    build_training_session(db_session, user.id, total_distance_km=8.0,
                           begin_ts=utcnow() - timedelta(days=14))
    t = planning.week_targets(user.id, db=db_session)
    assert t["detraining_return"] is True and t["days_off"] >= 14
    assert t["target_km"] <= round(30.0 * DETRAINING_RETURN_VOLUME_PCT, 1)
    assert t["hard_days_max"] == 0 and t["remaining_hard_days_max"] == 0


# --- P1 04.09.2026: #220 локальные недели, #292/#305 строка утра, #294 доступность, #295 потолок ---

def test_local_week_volumes_full_weeks_with_zero_gaps(db_session):
    """#220: полные недели пн–вс по локальной дате, пустые недели — нулями, без обрезки."""
    from datetime import datetime, time, timezone as tz

    from src.coach.planning_window import local_week_volumes, monday_of
    from src.utils.timeutils import user_now

    user = _unique_user(db_session)                       # Europe/Moscow
    today = user_now(user).date()
    this_monday = monday_of(today)
    # вс 22:30 UTC перед прошлой неделей = пн 01:30 МСК → в прошлую неделю
    build_training_session(db_session, user.id, total_distance_km=6.0,
                           begin_ts=datetime.combine(this_monday - timedelta(days=8), time(22, 30),
                                                     tzinfo=tz.utc))
    build_training_session(db_session, user.id, total_distance_km=4.0,
                           begin_ts=datetime.combine(this_monday - timedelta(days=4), time(8),
                                                     tzinfo=tz.utc))
    weeks = local_week_volumes(user.id, db=db_session, today=today, weeks=3)
    assert [w["week_start"] for w in weeks] == [this_monday - timedelta(weeks=3),
                                                this_monday - timedelta(weeks=2),
                                                this_monday - timedelta(weeks=1)]
    assert weeks[-1] == {"week_start": this_monday - timedelta(weeks=1), "total_km": 10.0,
                         "session_count": 2}
    assert weeks[0]["total_km"] == 0.0 and weeks[0]["session_count"] == 0


def test_morning_confirms_latest_row_including_proposed(db_session):
    """#292/#305: план дня = последняя действующая строка (proposed из чата), не старая planned."""
    from src.coach.state import assess_state
    from src.models import Recommendation
    from src.utils.timeutils import user_now

    user = _unique_user(db_session)
    now = user_now(user)
    old = Recommendation(user_id=user.id, for_date=now.date(), workout_type="tempo",
                         status="planned", target_json={"max_zone": 3}, volume_json={"duration_min": 45.0})
    new = Recommendation(user_id=user.id, for_date=now.date(), workout_type="easy",
                         status="proposed", target_json={"max_zone": 2}, volume_json={"duration_min": 30.0})
    db_session.add_all([old, new])
    db_session.commit()
    state = assess_state(user.id, db=db_session)
    p, mode, row = planning.confirm_or_adjust_morning(None, user.id, state, db=db_session, now=now)
    assert row.id == new.id and mode == "confirmed" and p.workout_type == "easy"
    db_session.refresh(old); db_session.refresh(new)
    assert new.status == "confirmed" and old.status == "planned"


def test_availability_persists_and_filters_plan_window(db_session):
    """#294: окно доступности (дни недели) хранится в params_json и вычитается из days_ahead_allowed;
    отменённые подопечным даты не входят в окно и переживают supersede_future_rows."""
    from src.coach.state import assess_state
    from src.models import Recommendation
    from src.utils.timeutils import user_now

    user = _unique_user(db_session)
    _week_of_km(db_session, user.id, 20.0, 2)
    _week_of_km(db_session, user.id, 22.0, 1)
    assert planning.set_availability(user.id, db=db_session, weekdays=[0, 1, 2, 3]) == {"weekdays": [0, 1, 2, 3]}
    assert planning.availability(user.id, db=db_session)["weekdays"] == [0, 1, 2, 3]
    now = user_now(user)
    # отмена конкретного дня через cancel_days (маркер) — на ближайший понедельник
    d_mon = (7 - now.date().weekday()) % 7 or 7
    planning.cancel_days([d_mon], user.id, assess_state(user.id, db=db_session), db=db_session, now=now)
    t = planning.week_targets(user.id, db=db_session)
    mon_date = now.date() + timedelta(days=d_mon)
    from src.coach.planning_window import plan_window
    _, first, last = plan_window(now.date(), trained_today=False)
    expected = [d for d in range(first, last + 1)
                if (now.date() + timedelta(days=d)).weekday() in (0, 1, 2, 3)
                and now.date() + timedelta(days=d) != mon_date]
    assert t["days_ahead_allowed"] == expected          # может быть [] среди недели пт–вс
    assert t["availability"]["weekday_names"] == ["Пн", "Вт", "Ср", "Чт"]
    from datetime import date as _d
    ws = _d.fromisoformat(t["week_start"])
    if ws <= mon_date <= ws + timedelta(days=6):        # отмена внутри планируемой недели
        assert mon_date.isoformat() in t["availability"]["unavailable_dates"]
    assert t["remaining_run_days_max"] <= len(t["days_ahead_allowed"])
    # перепланирование не гасит отмену подопечного
    planning.supersede_future_rows(user.id, db=db_session, from_date=now.date())
    rest = db_session.query(Recommendation).filter_by(user_id=user.id, for_date=mon_date).one()
    assert rest.status == "adjusted"
    assert planning.set_availability(user.id, db=db_session, weekdays=[]) == {"weekdays": None}


# --- 06.09.2026: потолок длительной держит код (cap_long_run) ---

def _long_prescription(distance_km):
    from src.coach.contracts import Prescription, SafetyVerdict
    return Prescription(safety=SafetyVerdict(), workout_type="long",
                        volume={"duration_min": 70.0},
                        predicted={"pace_min_km": 7.0, "distance_km": distance_km} if distance_km else {})


def test_cap_long_run_trims_to_km_ceiling():
    """70 мин ≈ 10 км при потолке 8,4 км → 58 мин, заметка про 30 % недели."""
    from src.coach.contracts import WorkoutProposal
    from src.coach.planning_safety import cap_long_run
    proposal = WorkoutProposal(workout_type="long", target_zone=2, duration_min=70, for_days_ahead=7)
    targets = {"long_run_km_max": 8.4, "long_run_min_max": 150.0, "long_run_hold": False}
    capped, note = cap_long_run(proposal, _long_prescription(10.0), targets)
    assert capped is not None and capped.duration_min == 58      # floor(70 × 8.4 / 10)
    assert capped.for_days_ahead == 7 and proposal.duration_min == 70   # копия, вход не мутирует
    assert "Длительная урезана до 58 мин" in note and "≈8.3 км" in note
    assert "потолок 30 % недельного объёма" in note


def test_cap_long_run_within_tolerance_untouched():
    """8,6 км при потолке 8,4 + допуск 0,3 — не трогаем (шум оценки темпа)."""
    from src.coach.contracts import WorkoutProposal
    from src.coach.planning_safety import cap_long_run
    proposal = WorkoutProposal(workout_type="long", target_zone=2, duration_min=60)
    targets = {"long_run_km_max": 8.4, "long_run_min_max": 150.0}
    assert cap_long_run(proposal, _long_prescription(8.6), targets) == (None, None)
    # Не длительная — вообще не рассматриваем
    easy = WorkoutProposal(workout_type="easy", target_zone=2, duration_min=200)
    assert cap_long_run(easy, _long_prescription(20.0), targets) == (None, None)


def test_cap_long_run_minutes_only_without_pace_history():
    """Нет оценки темпа → км-потолок честно не применяем, только 150 мин."""
    from src.coach.contracts import WorkoutProposal
    from src.coach.planning_safety import cap_long_run
    targets = {"long_run_km_max": 8.4, "long_run_min_max": 150.0}
    ok = WorkoutProposal(workout_type="long", target_zone=2, duration_min=120)
    assert cap_long_run(ok, _long_prescription(None), targets) == (None, None)
    too_long = WorkoutProposal(workout_type="long", target_zone=2, duration_min=170)
    capped, note = cap_long_run(too_long, _long_prescription(None), targets)
    assert capped.duration_min == 150 and "не дольше 150 мин" in note and "≈" not in note


def test_cap_long_run_mentions_hold():
    """long_run_hold (доля длительной превышена на прошлой неделе) — дополнение в заметке."""
    from src.coach.contracts import WorkoutProposal
    from src.coach.planning_safety import cap_long_run
    proposal = WorkoutProposal(workout_type="long", target_zone=2, duration_min=70, distance_km=10.0)
    targets = {"long_run_km_max": 8.4, "long_run_min_max": 150.0, "long_run_hold": True}
    capped, note = cap_long_run(proposal, _long_prescription(10.0), targets)
    assert capped.distance_km == 8.4 and capped.duration_min == 58
    assert "длительная не растёт после прошлой недели" in note


# --- 06.09.2026: потолок объёма недели (cap_week_volume) и плоский объём в safety-разгрузку ---

def _plan_items_and_prescriptions(spec):
    """spec: [(type, minutes, est_km)] → (items, prescriptions с predicted)."""
    from src.coach.contracts import Prescription, SafetyVerdict, WorkoutProposal
    items, pres = [], []
    for i, (t, minutes, km) in enumerate(spec):
        items.append(WorkoutProposal(workout_type=t, target_zone=2, duration_min=minutes,
                                     for_days_ahead=i + 1))
        pres.append(Prescription(safety=SafetyVerdict(), workout_type=t,
                                 volume={"duration_min": float(minutes)},
                                 predicted={"pace_min_km": 7.0, "distance_km": km} if km else {}))
    return items, pres


def test_cap_week_volume_scales_easy_days_only():
    """Инцидент 06.09.2026: сумма ≈ 30 км при цели 27,9 → лёгкие ужаты пропорционально,
    длительная не тронута, заметка про +10 %."""
    from src.coach.planning_safety import cap_week_volume
    items, pres = _plan_items_and_prescriptions(
        [("easy", 35, 5.0), ("easy", 42, 6.0), ("easy", 40, 5.7), ("easy", 35, 5.0), ("long", 58, 8.3)])
    targets = {"target_km": 27.9, "prev_week_km": 25.4}
    new, note = cap_week_volume(items, pres, targets)
    assert new is not None and new[4] is items[4]                 # длительная — тот же объект
    scaled_min = [it.duration_min for it in new[:4]]
    assert all(n < o for n, o in zip(scaled_min, [35, 42, 40, 35]))
    est = sum(km * n / o for (_, o, km), n in zip(
        [("easy", 35, 5.0), ("easy", 42, 6.0), ("easy", 40, 5.7), ("easy", 35, 5.0)], scaled_min)) + 8.3
    assert est <= 27.9 + 0.3
    assert "Объём недели урезан до ~28 км" in note and "+10 %" in note and "25.4" in note
    assert items[0].duration_min == 35                            # вход не мутирует


def test_cap_week_volume_within_tolerance_and_floor():
    from src.coach.planning_safety import cap_week_volume
    items, pres = _plan_items_and_prescriptions([("easy", 40, 5.7), ("long", 60, 8.6)])
    assert cap_week_volume(items, pres, {"target_km": 14.0}) == (None, None)   # 14.3 ≤ 14×1.05
    # Пол PLAN_EASY_MIN_MINUTES: цель заведомо ниже — лёгкий не режется ниже пола
    from src.coach.config import PLAN_EASY_MIN_MINUTES
    items, pres = _plan_items_and_prescriptions([("easy", 40, 5.7), ("long", 60, 8.6)])
    new, note = cap_week_volume(items, pres, {"target_km": 9.0, "prev_week_km": 8.0})
    assert new[0].duration_min == PLAN_EASY_MIN_MINUTES and new[1] is items[1]
    # Только длительная/качество — ужимать нечего
    items, pres = _plan_items_and_prescriptions([("long", 90, 12.9)])
    assert cap_week_volume(items, pres, {"target_km": 9.0}) == (None, None)


def test_cap_week_volume_rest_of_week_uses_remaining():
    from src.coach.planning_safety import cap_week_volume
    items, pres = _plan_items_and_prescriptions([("easy", 40, 5.7), ("easy", 40, 5.7)])
    targets = {"target_km": 28.0, "plan_scope": "rest_of_week", "remaining_km": 6.0, "done_km": 22.0}
    new, note = cap_week_volume(items, pres, targets)
    assert new is not None and all(it.duration_min < 40 for it in new)


def test_apply_safety_holds_volume_flat():
    """Решение владельца 06.09.2026: интенсив закрыт → цель объёма = прошлая неделя,
    потолок длительной пересчитан, флаг для шапки/промпта."""
    from src.coach.contracts import ReasoningStep, SafetyVerdict
    from src.coach.planning_safety import apply_safety_to_targets
    verdict = SafetyVerdict(max_zone=2, allowed_types=("rest", "recovery", "easy", "long"),
                            reasons=[ReasoningStep(rule="p1_safety", decision="", reason="перекос")])
    base = {"hard_days_max": 1, "quality_z3_km_max": 5.6, "quality_z4_km_max": 2.8,
            "target_km": 27.9, "prev_week_km": 25.4, "long_run_km_max": 8.4,
            "plan_scope": "rest_of_week", "done_km": 10.0, "remaining_km": 17.9,
            "run_days_max": 5, "rest_days_min": 2, "prev_week_runs_max": 4,
            "remaining_run_days_max": 3, "done_runs": 2, "days_ahead_allowed": [0, 1, 2, 3, 4]}
    out = apply_safety_to_targets(base, verdict)
    assert out["target_km"] == 25.4 and out["volume_held_by_safety"] is True
    # 07.09.2026: при малом объёме доля длительной 40 % → потолок 8.4 остаётся (≤ 25.4 × 0.40)
    assert out["long_run_km_max"] == 8.4 and out["long_run_max_pct"] == 0.40
    assert out["remaining_km"] == 15.4
    # 07.09.2026: объём плоский → беговых дней не больше, чем в прошлые недели (4, не 5)
    assert out["run_days_max"] == 4 and out["rest_days_min"] == 3
    assert out["remaining_run_days_max"] == 2                     # 4 − 2 сделанных
    # Без истории (prev 0) объём не трогаем
    out2 = apply_safety_to_targets({**base, "prev_week_km": 0.0}, verdict)
    assert out2["target_km"] == 27.9 and "volume_held_by_safety" not in out2


def test_cap_week_volume_keeps_structured_days_and_leaves_trail():
    """06.09.2026: день с сегментами не масштабируется (иначе 39 мин при сегментах на 42);
    урезанные копии несут след «урезано кодом» в rationale."""
    from src.coach.contracts import WorkoutSegment
    from src.coach.planning_safety import cap_week_volume
    items, pres = _plan_items_and_prescriptions(
        [("easy", 40, 5.7), ("easy", 42, 6.0), ("easy", 40, 5.7), ("long", 58, 8.3)])
    items[1].segments.append(WorkoutSegment(role="work", amount_kind="sec", amount_value=20,
                                            repeat=5, target_zone=3))
    new, note = cap_week_volume(items, pres, {"target_km": 22.0, "prev_week_km": 22.0})
    assert new is not None
    assert new[1] is items[1] and new[3] is items[3]             # структурный и длительная — нетронуты
    assert new[0].duration_min < 40 and new[2].duration_min < 40
    assert any(r.startswith("урезано кодом: 40 →") for r in new[0].rationale)
    assert items[0].rationale == []                              # вход не мутирует


def test_cap_long_run_structured_only_warns_and_trail_on_plain():
    from src.coach.contracts import WorkoutProposal, WorkoutSegment
    from src.coach.planning_safety import cap_long_run
    targets = {"long_run_km_max": 8.4, "long_run_min_max": 150.0}
    structured = WorkoutProposal(workout_type="long", target_zone=2, duration_min=70,
                                 segments=[WorkoutSegment(role="steady", amount_value=70, target_zone=2)])
    capped, note = cap_long_run(structured, _long_prescription(10.0), targets)
    assert capped is None and "структура задана" in note
    plain = WorkoutProposal(workout_type="long", target_zone=2, duration_min=70,
                            rationale=["единственная длительная"])
    capped, _ = cap_long_run(plain, _long_prescription(10.0), targets)
    assert capped.rationale[0] == "единственная длительная"
    assert capped.rationale[-1].startswith("урезано кодом: 70 → 58 мин")
