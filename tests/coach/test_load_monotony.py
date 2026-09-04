# Монотонность/страйн Фостера (P0 #308, 04.09.2026) — src/coach/load_monotony.py
from datetime import timedelta

from src.coach.load_monotony import monotony_from_daily, monotony_window
from src.domain.models.base import utcnow
from src.models import WorkoutInsight
from src.utils.timeutils import user_now
from tests.coach.conftest import _unique_user
from tests.helpers import build_training_session


def test_monotony_math():
    flat = monotony_from_daily([10, 10, 10, 10, 10, 10, 0])       # 6 одинаковых дней + отдых
    assert flat["trained_days"] == 6 and flat["monotony"] > 2.0
    assert flat["strain"] == round(60 * flat["monotony"], 1)
    varied = monotony_from_daily([20, 0, 10, 0, 30, 0, 5])
    assert varied["monotony"] < 1.5
    assert monotony_from_daily([0] * 7)["monotony"] is None
    assert monotony_from_daily([])["trained_days"] == 0
    assert monotony_from_daily([10] * 7)["monotony"] is None      # SD=0 → не определено


def test_monotony_window_from_insights(db_session):
    """Дневные баллы — из зон разборов; 6 одинаковых дней из 7 → monotony ≈ 2.45 → high."""
    user = _unique_user(db_session)
    today = user_now(user).date()
    for i in range(6):
        s = build_training_session(db_session, user.id, training_type="easy",
                                   begin_ts=utcnow() - timedelta(days=i + 1))
        db_session.add(WorkoutInsight(user_id=user.id, session_id=s.id, status="done",
                                      computed_json={"time_in_zones": {
                                          "available": True,
                                          "minutes": {"z1": 5.0, "z2": 30.0, "z3": 0.0,
                                                      "z4": 0.0, "z5": 0.0}}}))
    db_session.commit()
    m = monotony_window(user.id, db=db_session, today=today)
    assert m["trained_days"] == 6 and m["total"] == round(6 * (5 * 0.2 + 30 * 0.25), 1)
    assert m["monotony"] > 2.0 and m["high"] is True
