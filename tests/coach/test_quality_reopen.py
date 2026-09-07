# 07.09.2026: план недели применял сегодняшний вердикт ко всем дням — правило 17 (лёгкие слишком
# быстро, окно 7 дней) прогнозируется по датам флагов, качество открывается среди недели.
from datetime import date, timedelta, timezone

from src.coach.config import EASY_TOO_HARD_WEEK_FLAGS
from src.coach.contracts import ReasoningStep, SafetyVerdict
from src.coach.planning_safety import (
    apply_safety_to_targets,
    easy_too_hard_counts_by_day,
    project_state,
    quality_reopens_at,
)
from src.domain.models.base import utcnow
from tests.coach.test_safety_clamp import _state


def _now():
    return utcnow().replace(tzinfo=timezone.utc) if utcnow().tzinfo is None else utcnow()


def test_counts_by_day_projects_flags_leaving_the_window():
    now = _now()
    flags = [now - timedelta(days=6), now - timedelta(days=5), now - timedelta(days=4)]
    counts = easy_too_hard_counts_by_day(flags, now=now)
    assert counts[0] == 3 and counts[1] == 3          # −6 ещё в окне (now+1−7 = −6)
    assert counts[2] == 2 and counts[3] == 1 and counts[4] == 0
    # naive-время из SQLite трактуется как UTC
    naive = [t.replace(tzinfo=None) for t in flags]
    assert easy_too_hard_counts_by_day(naive, now=now)[0] == 3


def test_quality_reopens_when_counter_falls_below_threshold():
    now = _now()
    flags = [now - timedelta(days=6), now - timedelta(days=5)]
    counts = easy_too_hard_counts_by_day(flags, now=now)
    state = _state(easy_too_hard_7d=counts[0])
    assert counts[0] == EASY_TOO_HARD_WEEK_FLAGS
    assert quality_reopens_at(state, counts, now=now, days=[0, 1, 2, 3, 4]) == 2   # −5 выходит
    # Окно короче — не открывается
    assert quality_reopens_at(state, counts, now=now, days=[0, 1]) is None
    # Другое правило (не прогнозируемое) держит блок на всё окно
    blocked = _state(easy_too_hard_7d=counts[0], hrv_status="low")
    assert quality_reopens_at(blocked, counts, now=now, days=[0, 1, 2, 3, 4]) is None
    # project_state меняет только счётчик
    assert project_state(state, counts, 3).signals["easy_too_hard_7d"] == 0
    assert project_state(state, counts, 9) is state


def test_apply_safety_partial_keeps_quality_day():
    verdict = SafetyVerdict(max_zone=2, allowed_types=("rest", "recovery", "easy", "long"),
                            triggered=["easy_runs_too_hard"],
                            reasons=[ReasoningStep(rule="p1_safety", decision="",
                                                   reason="2 лёгких слишком быстро")])
    base = {"hard_days_max": 1, "remaining_hard_days_max": 1, "quality_z3_km_max": 2.5,
            "quality_z4_km_max": 2.0, "target_km": 27.9, "prev_week_km": 25.4}
    partial = apply_safety_to_targets(base, verdict, quality_from_days_ahead=3)
    assert partial["hard_days_max"] == 1 and partial["remaining_hard_days_max"] == 1
    assert partial["quality_z3_km_max"] == 2.5
    assert partial["quality_allowed_from_days_ahead"] == 3
    assert partial["quality_blocked_by_safety"] == "2 лёгких слишком быстро"
    assert partial["target_km"] == 25.4 and partial["volume_held_by_safety"] is True
    full = apply_safety_to_targets(base, verdict)
    assert full["hard_days_max"] == 0 and "quality_allowed_from_days_ahead" not in full


def test_weekly_plan_places_tempo_after_rule17_clears(db_session):
    """Интеграция: два флага 6 и 5 дней назад → сегодня интенсив закрыт, с дня +2 открыт.
    Темповая на +1 режется в лёгкую, темповая на +3 остаётся; шапка называет день."""
    from src.coach.llm.client import LLMResponse
    from src.coach.weekly_plan import generate_weekly_plan
    from src.models import Recommendation, WorkoutInsight
    from src.utils.timeutils import user_now
    from tests.coach.conftest import _unique_user
    from tests.coach.fakes import ScriptedLLM
    from tests.helpers import build_daily_metrics, build_training_session

    user = _unique_user(db_session)
    now = user_now(user)
    # Якорь — будущая среда 09:00 (окно 0..4), флаги относительно неё
    days = (2 - now.weekday()) % 7 or 7
    wed = (now + timedelta(days=days)).replace(hour=9, minute=0, second=0, microsecond=0)
    today = utcnow().date()
    for i in range(28):   # здоровый фон 4 недели: восстановление высокое, ACWR ≈ 1
        build_daily_metrics(db_session, user.id, metric_date=today - timedelta(days=i),
                            avg_sleep_hrv=65.0, rhr=54, vo2max=50.0, recovery_pct=95)
    for back in (8, 11, 15, 18, 22, 25, 29, 32):   # 4 недели ровной истории → ACWR ≈ 1
        build_training_session(db_session, user.id, total_distance_km=6.0, duration_minutes=42.0,
                               training_type="easy", avg_heart_rate=130,
                               begin_ts=wed - timedelta(days=back))
    for back in (6, 5):
        s = build_training_session(db_session, user.id, total_distance_km=5.0,
                                   duration_minutes=35.0, training_type="easy",
                                   avg_heart_rate=137, begin_ts=wed - timedelta(days=back))
        db_session.add(WorkoutInsight(user_id=user.id, session_id=s.id, status="done",
                                      computed_json={"flags": ["easy_run_too_hard"]}))
    db_session.commit()

    turn = {"message": "Темповую возвращаем с пятницы.", "proposal": None,
            "followup_question": None, "log_suggestion": None, "weekly_plan": [
                {"workout_type": "tempo", "target_zone": 3, "duration_min": 40, "for_days_ahead": 1},
                {"workout_type": "tempo", "target_zone": 3, "duration_min": 40, "for_days_ahead": 3},
            ]}
    llm = ScriptedLLM([LLMResponse(stop_reason="end_turn", parsed=turn)])
    text = generate_weekly_plan(user.id, db=db_session, llm=llm, now=wed)
    assert text is not None
    rows = {(r.for_date - wed.date()).days: r for r in db_session.query(Recommendation).filter_by(
        user_id=user.id, status="planned").all()}
    assert rows[1].workout_type == "easy" and rows[1].clamped          # до открытия — режется
    assert rows[3].workout_type == "tempo" and not rows[3].clamped     # после — остаётся
    reopen = wed.date() + timedelta(days=2)
    assert f"интенсив не раньше" in text and f"{reopen:%d.%m}" in text
    assert "разгрузка по safety" in text
    assert '"quality_allowed_from_days_ahead": 2' in str(llm.calls[0])
