# Тесты сборки AthleteState (DEV_PLAN §10)
from datetime import timedelta

from src.coach.skills.base import SKILL_KEYS
from src.coach.state import _week_signals, assess_state
from src.domain.models.base import utcnow
from src.utils.timeutils import user_now
from tests.coach.conftest import _unique_user
from tests.helpers import build_daily_metrics, build_training_session


def test_assess_state_full_fixture(athlete_with_history, db_session):
    state = assess_state(athlete_with_history.id, db=db_session)
    assert state.user_id == athlete_with_history.id
    assert set(state.skills) == set(SKILL_KEYS)
    assert state.as_of is not None
    assert state.readiness_score is not None and 0 <= state.readiness_score <= 100
    assert state.fatigue_score is not None and 0 <= state.fatigue_score <= 100
    assert state.injury_risk is not None and 0 <= state.injury_risk <= 1
    assert state.last_workout is not None and state.last_workout["type"] == "easy"
    # Время суток для LLM: локальное время старта + пояс (local start time + zone)
    assert state.last_workout["started_at_local"] is not None
    assert state.last_workout["tz"] == "Europe/Moscow"
    # Честность: сна/стресса в данных нет — LLM обязан это видеть
    assert "sleep" in state.missing and "stress" in state.missing
    # 4 RPE из 36 в проде; в фикстуре 0 из 5 → rpe тоже missing
    assert "rpe" in state.missing


def test_assess_state_empty_user_never_raises(empty_user, db_session):
    """Пустая БД → None-скоры и unknown-скиллы, без исключений (no-data contract)."""
    state = assess_state(empty_user.id, db=db_session)
    assert state.readiness_score is None
    assert state.fatigue_score is None
    assert state.data_confidence == 0.0
    assert state.as_of is None
    assert state.last_workout is None
    assert all(s.status == "unknown" for s in state.skills.values())


def test_data_confidence_grows_with_history(db_session):
    """data_confidence растёт с историей: 3 дня << CONFIDENCE_MIN_DAYS → низкая."""
    user = _unique_user(db_session)
    today = utcnow().date()
    for i in range(3):
        build_daily_metrics(db_session, user.id, metric_date=today - timedelta(days=i))
    sparse = assess_state(user.id, db=db_session)
    assert 0.0 < sparse.data_confidence < 0.5


def test_zone_balance_shape(athlete_with_history, db_session):
    """zone_balance либо пуст (нет сегментов), либо суммируется к ~1.0."""
    state = assess_state(athlete_with_history.id, db=db_session)
    if state.zone_balance:
        assert abs(state.zone_balance["z1_z2"] + state.zone_balance["z3_plus"] - 1.0) < 0.02


# --- _week_signals (M4.1/M4.3): сырьё правил 12–14 p1_safety ---------------------

def test_week_signals_interval_yesterday(db_session):
    """Интервальная вчера → days_since_quality=1, days_off=1, гонки нет."""
    user = _unique_user(db_session)
    build_training_session(db_session, user.id, training_type="interval",
                           begin_ts=utcnow() - timedelta(days=1))
    today = user_now(user).date()
    sig = _week_signals(user.id, today, user, db=db_session)
    assert sig["days_since_quality"] == 1
    assert sig["quality_days_7d"] == 1
    assert sig["days_off"] == 1
    assert sig["post_race_days_left"] == 0


def test_week_signals_race_yesterday(db_session):
    """Гонка 9 км вчера → required=3 лёгких дня, осталось 2; гонка качественная."""
    user = _unique_user(db_session)
    build_training_session(db_session, user.id, training_type="race",
                           total_distance_km=9.0,
                           begin_ts=utcnow() - timedelta(days=1))
    today = user_now(user).date()
    sig = _week_signals(user.id, today, user, db=db_session)
    assert sig["post_race_days_left"] == 2         # ceil(9/3) − 1
    assert sig["days_since_quality"] == 1


def test_week_signals_soft_tempo_not_quality(db_session):
    """Tempo с avg_hr ниже 95% LTHR (150 < 0.95·170) — не качественный день."""
    user = _unique_user(db_session)
    build_daily_metrics(db_session, user.id, metric_date=utcnow().date())  # lthr=170
    build_training_session(db_session, user.id, training_type="tempo",
                           avg_heart_rate=150,
                           begin_ts=utcnow() - timedelta(days=1))
    today = user_now(user).date()
    sig = _week_signals(user.id, today, user, db=db_session)
    assert sig["days_since_quality"] is None
    assert sig["quality_days_7d"] == 0
    assert sig["days_off"] == 1


def test_week_signals_empty_user_defaults(db_session):
    """Без тренировок → None/0-дефолты (правила 12–14 будут молчать)."""
    user = _unique_user(db_session)
    sig = _week_signals(user.id, user_now(user).date(), user, db=db_session)
    assert sig == {"days_since_quality": None, "quality_days_7d": 0,
                   "post_race_days_left": 0, "days_off": None}


def test_assess_state_signals_include_week_signals(athlete_with_history, db_session):
    """assess_state кладёт недельные сигналы в signals: interval 6 дней назад, длительная
    4 дня назад — тоже качественный день (решение владельца 04.09.2026, гайд 45);
    tempo фикстуры «мягкое» (avg_hr 150 < 0.95·170), сегодня easy → days_off=0."""
    state = assess_state(athlete_with_history.id, db=db_session)
    assert state.signals["days_since_quality"] == 4
    assert state.signals["quality_days_7d"] == 2
    assert "hard_share_7d" in state.signals
    assert state.signals["days_off"] == 0
    assert state.signals["post_race_days_left"] == 0


# --- Свежесть боли (фикс 02.09.2026): stale-отметка не блокирует ------------------

def test_stale_pain_becomes_context_not_blocker(db_session):
    """Боль 5/10 отмечена 3 дня назад (> PAIN_FRESH_DAYS=2) → value=None,
    status ok, факт в message/evidence; правила 8–9 p1_safety молчат."""
    from src.coach.config import PAIN_FRESH_DAYS, PAIN_STOP_LEVEL
    from src.coach.rules.p1_safety import evaluate_safety
    from src.coach.skills import pain
    from src.models import WellnessReport

    user = _unique_user(db_session)
    stale_day = utcnow().date() - timedelta(days=PAIN_FRESH_DAYS + 1)
    db_session.add(WellnessReport(user_id=user.id, report_date=stale_day,
                                  pain_level=PAIN_STOP_LEVEL))
    db_session.commit()

    res = pain.evaluate(user.id, db=db_session)
    assert res.status == "ok"
    assert res.value is None                       # не сырьё для правил 8–9
    assert "устарела" in res.message
    assert "спроси про колено" in res.message       # LLM получает контекст
    assert "stale=True" in res.evidence
    assert res.as_of == stale_day

    state = assess_state(user.id, db=db_session)
    assert state.signals["pain_level"] is None
    assert state.signals["pain_days"] == 0
    verdict = evaluate_safety(state)
    assert verdict.allow_training is True
    assert "pain_stop" not in verdict.triggered
    assert "pain_caution" not in verdict.triggered


def test_fresh_pain_boundary_still_blocks(db_session):
    """Отметка ровно PAIN_FRESH_DAYS назад — ещё свежая: 5/10 → danger,
    в signals доезжает и запрещает тренировку (прежнее поведение)."""
    from src.coach.config import PAIN_FRESH_DAYS, PAIN_STOP_LEVEL
    from src.coach.rules.p1_safety import evaluate_safety
    from src.coach.skills import pain
    from src.models import WellnessReport

    user = _unique_user(db_session)
    db_session.add(WellnessReport(
        user_id=user.id,
        report_date=utcnow().date() - timedelta(days=PAIN_FRESH_DAYS),
        pain_level=PAIN_STOP_LEVEL))
    db_session.commit()

    res = pain.evaluate(user.id, db=db_session)
    assert res.status == "danger"
    assert res.value == PAIN_STOP_LEVEL
    verdict = evaluate_safety(assess_state(user.id, db=db_session))
    assert verdict.allow_training is False
    assert "pain_stop" in verdict.triggered


# --- Сигнал сна (#254): только скриншот за СЕГОДНЯ --------------------------------

def test_sleep_signal_from_todays_metrics(db_session):
    """DailyMetrics за сегодня (локально) со сном → signals['sleep_duration_min']."""
    user = _unique_user(db_session)
    today = user_now(user).date()
    build_daily_metrics(db_session, user.id, metric_date=today,
                        sleep_duration_min=340)
    state = assess_state(user.id, db=db_session)
    assert state.signals["sleep_duration_min"] == 340
    assert "sleep" not in state.missing


def test_sleep_signal_none_for_yesterdays_row(db_session):
    """Свежайшая строка метрик — вчерашняя → сигнал сна None (не наказываем
    за отсутствие сегодняшнего скриншота)."""
    user = _unique_user(db_session)
    yesterday = user_now(user).date() - timedelta(days=1)
    build_daily_metrics(db_session, user.id, metric_date=yesterday,
                        sleep_duration_min=340)
    state = assess_state(user.id, db=db_session)
    assert state.signals["sleep_duration_min"] is None


def test_week_signals_long_run_counts_as_quality(db_session):
    """Длительная вчера → days_since_quality=1 (день после длительной — лёгкий, гайд 45)."""
    user = _unique_user(db_session)
    build_training_session(db_session, user.id, training_type="long", avg_heart_rate=135,
                           begin_ts=utcnow() - timedelta(days=1))
    today = user_now(user).date()
    sig = _week_signals(user.id, today, user, db=db_session)
    assert sig["days_since_quality"] == 1 and sig["quality_days_7d"] == 1
    # часовая «easy» по ярлыку классификатора — тоже длительная (LONG_RUN_MIN_MINUTES)
    user2 = _unique_user(db_session)
    build_training_session(db_session, user2.id, training_type="easy", duration_minutes=62,
                           avg_heart_rate=135, begin_ts=utcnow() - timedelta(days=1))
    assert _week_signals(user2.id, today, user2, db=db_session)["days_since_quality"] == 1


def test_hard_share_7d_signal(db_session):
    """Доля Z3+ за 7 дней из зон по сегментам; мало минут (< 60) → None."""
    user = _unique_user(db_session)             # max_hr 177 → 165 = Z4+, 130 = Z2
    build_training_session(db_session, user.id, training_type="easy",
                           begin_ts=utcnow() - timedelta(days=1),
                           segments_json=[{"avg_hr": 130, "duration_min": 20.0}])
    assert assess_state(user.id, db=db_session).signals["hard_share_7d"] is None
    build_training_session(db_session, user.id, training_type="tempo",
                           begin_ts=utcnow() - timedelta(days=2),
                           segments_json=[{"avg_hr": 165, "duration_min": 30.0},
                                          {"avg_hr": 130, "duration_min": 20.0}])
    state = assess_state(user.id, db=db_session)
    assert state.signals["hard_share_7d"] == round(30 / 70, 2)


def test_state_signals_carry_p0_closures(athlete_with_history, db_session):
    """#289/#308: сигналы правил 17–20 присутствуют в state.signals."""
    sig = assess_state(athlete_with_history.id, db=db_session).signals
    assert sig["easy_too_hard_7d"] == 0
    assert sig["quality_volume_exceeded_recent"] is False
    assert sig["downhill_load_recent"] is False
    assert "monotony_7d" in sig and "trained_days_7d" in sig
