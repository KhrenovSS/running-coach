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
