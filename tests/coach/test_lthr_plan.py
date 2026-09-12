# Полевой тест ПАНО в плане недели (M3.2, 12.09.2026): lthr_test_due в week_targets и размещение
# теста кодом первым качественным днём (chat_id — счётчик tests/coach/conftest._seq, 92xxx).
from datetime import datetime, timedelta, timezone

from src.coach import lthr_field, planning
from src.coach.llm.client import LLMResponse
from src.coach.weekly_plan import generate_weekly_plan
from src.models import Recommendation
from tests.coach.conftest import _unique_user
from tests.coach.fakes import ScriptedLLM
from tests.coach.test_weekly_plan import PLAN_TURN, _sunday
from tests.helpers import build_daily_metrics, build_training_session
from src.utils.timeutils import user_now


def _stable_athlete(db):
    """5 полных недель по 3 лёгких (пн/ср/пт) + текущая неделя до сегодня, 14 дней хороших метрик → stable."""
    user = _unique_user(db)
    today = user_now(user).date()
    for i in range(28):      # 28 дней метрик: иначе ACWR по training_load = 2.0 (хроника обрезана)
        build_daily_metrics(db, user.id, metric_date=today - timedelta(days=i),
                            avg_sleep_hrv=65.0, rhr=54, vo2max=50.0, recovery_pct=90, lthr=156)
    monday = today - timedelta(days=today.weekday())
    days = {today - timedelta(days=1)}
    for w in range(0, 6):
        ws = monday - timedelta(weeks=w)
        days |= {ws + timedelta(days=off) for off in (0, 2, 4)}
    for d in sorted(d for d in days if d < today):
        build_training_session(db, user.id, total_distance_km=7.0, duration_minutes=45.0,
                               training_type="easy", avg_heart_rate=132,
                               begin_ts=datetime(d.year, d.month, d.day, 9, tzinfo=timezone.utc))
    return user


def test_week_targets_lthr_test_due_only_when_stable_and_no_field(db_session):
    user = _stable_athlete(db_session)
    t = planning.week_targets(user.id, db=db_session, today=_sunday(user).date())
    assert t["athlete_status"] == "stable" and t["lthr_test_due"] is True
    lthr_field.set_field_lthr(user.id, 158, db=db_session, method="manual", now=datetime.now(timezone.utc))
    t2 = planning.week_targets(user.id, db=db_session, today=_sunday(user).date())
    assert t2["lthr_test_due"] is False
    fresh = _unique_user(db_session)      # без истории → не stable → теста нет
    assert planning.week_targets(fresh.id, db=db_session)["lthr_test_due"] is False


def test_weekly_plan_places_lthr_test_on_quality_day(db_session):
    user = _stable_athlete(db_session)
    turn = dict(PLAN_TURN, weekly_plan=[
        {"workout_type": "easy", "target_zone": 2, "duration_min": 40, "for_days_ahead": 1},
        {"workout_type": "tempo", "target_zone": 3, "duration_min": 40, "for_days_ahead": 3},
        {"workout_type": "easy", "target_zone": 2, "duration_min": 40, "for_days_ahead": 5},
        {"workout_type": "long", "target_zone": 2, "duration_min": 70, "for_days_ahead": 7},
    ])
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=turn)])
    sunday = _sunday(user)
    text = generate_weekly_plan(user.id, db=db_session, llm=llm, now=sunday)
    assert text is not None and "Тест ПАНО" in text and "полевой тест ПАНО" in text
    rows = {(r.for_date - sunday.date()).days: r for r in db_session.query(Recommendation).filter_by(
        user_id=user.id, status="planned").all()}
    test_row = rows[3]
    assert test_row.workout_type == "race" and test_row.target_json.get("lthr_test") is True
    segs = test_row.target_json.get("segments") or []
    assert [s["role"] for s in segs] == ["warmup", "work", "cooldown"] and segs[1]["amount_value"] == 30
    assert rows[7].workout_type == "long" and rows[1].workout_type == "easy"
    # промпт видел флаг
    assert '"lthr_test_due": true' in str(llm.calls[0])
    # утренний re-clamp: строка того же дня остаётся с маркером (target не трогаем при confirmed)
    proposal = planning._proposal_from_row(test_row)
    assert proposal.workout_type == "race" and len(proposal.segments) == 3
