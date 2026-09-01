# Тесты M4 (F5/F6, METRICS_GUIDE §11): структура недели, детренированность,
# downhill-нагрузка + интеграция с workout_insights (schema v7).
# (Weekly structure / detraining / downhill tests + insights integration.)

from datetime import date, timedelta

import pytest

from src.analysis.gap import downhill_block
from src.analysis.utils import serialize_trackpoints
from src.analysis.week_structure import (
    FLAG_HARD_DAYS_TOO_CLOSE,
    FLAG_POST_RACE_RECOVERY,
    detraining,
    is_quality_session,
    week_structure,
)
from src.domain.models.base import utcnow
from src.services.workout_insights import (
    INSIGHTS_SCHEMA_VERSION,
    compute_workout_metrics,
    upsert_workout_insights,
)
from tests.helpers import (
    build_trackpoints,
    build_training_feedback,
    build_training_session,
    make_user,
)

D = date(2026, 9, 1)  # опорная дата сессии (reference session date)


def _row(days_ago: int, ttype: str, km: float = 8.0, avg_hr: int | None = None) -> dict:
    return {"date": D - timedelta(days=days_ago), "type": ttype,
            "km": km, "avg_hr": avg_hr}


# --- is_quality_session: матрица (quality-day classification matrix) -----------

@pytest.mark.parametrize("ttype,avg_hr,max_hr,lthr,expected", [
    ("interval", None, None, None, True),      # interval — всегда качественная
    ("race", 120, 180, 156, True),             # race — всегда, даже с низким HR
    ("tempo", 149, None, 156, True),           # 149 ≥ 0.95·156 = 148.2
    ("tempo", 145, None, 156, False),          # 145 < 148.2 — «мягкое» tempo
    ("tempo", None, 180, 156, True),           # незнание HR = осторожность
    ("easy", 165, 180, 156, False),            # easy — никогда
    ("tempo", 153, 180, None, True),           # fallback: 153 ≥ 0.85·180 = 153
    ("tempo", 150, 180, None, False),          # 150 < 153
    ("tempo", 150, None, None, True),          # ни lthr, ни max_hr → осторожность
    (None, None, None, None, False),           # неизвестный тип — не качественная
])
def test_is_quality_session_matrix(ttype, avg_hr, max_hr, lthr, expected):
    assert is_quality_session(ttype, avg_hr, max_hr, lthr) is expected


# --- week_structure: интервал между качественными и лимит за неделю ------------

def test_quality_one_day_after_quality_flags():
    """Качественная через 1 день после качественной → hard_days_too_close."""
    history = [_row(1, "interval"), _row(0, "interval")]
    ws = week_structure(history, D, "interval")
    assert ws["available"] is True
    assert ws["session_is_quality"] is True
    assert ws["days_since_prev_quality"] == 1
    assert ws["quality_days_7d"] == 2
    assert FLAG_HARD_DAYS_TOO_CLOSE in ws["flags"]


def test_quality_two_days_gap_no_flag():
    """Ровно QUALITY_MIN_GAP_DAYS=2 дня между качественными → флага нет."""
    history = [_row(2, "interval"), _row(0, "interval")]
    ws = week_structure(history, D, "interval")
    assert ws["days_since_prev_quality"] == 2
    assert ws["flags"] == []


def test_four_quality_days_in_week_flags():
    """4 качественных за 7 дней (интервал соблюдён) → флаг по количеству."""
    history = [_row(6, "interval"), _row(4, "interval"),
               _row(2, "interval"), _row(0, "interval")]
    ws = week_structure(history, D, "interval")
    assert ws["quality_days_7d"] == 4
    assert ws["days_since_prev_quality"] == 2      # интервал сам по себе ок
    assert FLAG_HARD_DAYS_TOO_CLOSE in ws["flags"]


def test_easy_session_among_frequent_quality_no_flag():
    """Сама сессия лёгкая → правило качественных дней к ней не применяется."""
    history = [_row(3, "interval"), _row(2, "interval"),
               _row(1, "interval"), _row(0, "easy")]
    ws = week_structure(history, D, "easy")
    assert ws["session_is_quality"] is False
    assert "days_since_prev_quality" not in ws
    assert ws["flags"] == []


# --- week_structure: восстановление после гонки (post-race recovery) -----------

def test_post_race_violated_when_quality_too_soon():
    """Гонка 10 км 2 дня назад + качественная сегодня → нарушение (нужно 4 дня)."""
    history = [_row(2, "race", km=10.0), _row(0, "interval")]
    ws = week_structure(history, D, "interval")
    pr = ws["post_race"]
    assert pr["required_easy_days"] == 4           # ceil(10/3)
    assert pr["days_elapsed"] == 2
    assert FLAG_POST_RACE_RECOVERY in ws["flags"]
    # интервал race→interval = 2 дня — правило близости при этом молчит
    assert FLAG_HARD_DAYS_TOO_CLOSE not in ws["flags"]


def test_post_race_ok_after_enough_easy_days():
    """Через 5 дней после гонки 10 км (нужно 4) → нарушения нет."""
    history = [_row(5, "race", km=10.0), _row(0, "interval")]
    ws = week_structure(history, D, "interval")
    assert ws["post_race"]["days_elapsed"] == 5
    assert FLAG_POST_RACE_RECOVERY not in ws["flags"]


def test_week_structure_no_date_degrades():
    assert week_structure([_row(1, "interval")], None, "interval") == \
        {"available": False, "reason": "no_date"}


# --- detraining: пауза перед тренировкой (layoff before the session) -----------

def test_detraining_seven_days_off_flags_with_vdot_drop():
    history = [_row(7, "easy"), _row(0, "easy")]
    dt = detraining(history, D)
    assert dt["available"] is True
    assert dt["days_off"] == 7
    assert dt["flag"] is True
    assert dt["expected_vdot_drop_pct"] == pytest.approx(0.6)  # (7-5)·0.3


def test_detraining_three_days_off_silent():
    dt = detraining([_row(3, "easy"), _row(0, "easy")], D)
    assert dt["days_off"] == 3
    assert dt["flag"] is False
    assert "expected_vdot_drop_pct" not in dt


def test_detraining_no_history_degrades():
    assert detraining([_row(0, "easy")], D) == \
        {"available": False, "reason": "no_history"}
    assert detraining([], None) == {"available": False, "reason": "no_date"}


# --- downhill_block: объём крутых спусков (steep-descent volume) ----------------

def test_downhill_steep_descent_half_run_flags():
    """Половина дистанции — спуск 5% (круче порога -3%) → доля 0.5, флаг."""
    dists = [i * 100.0 for i in range(101)]        # 10 км, шаг 100 м
    alts = [500.0 - min(i, 50) * 5.0 for i in range(101)]  # −5 м/100 м, потом ровно
    block = downhill_block(dists, alts)
    assert block["available"] is True
    assert block["downhill_km"] == pytest.approx(5.0)
    assert block["downhill_share_pct"] == pytest.approx(0.5)
    assert block["flag"] is True


def test_downhill_flat_run_no_flag():
    dists = [i * 100.0 for i in range(101)]
    block = downhill_block(dists, [150.0] * 101)
    assert block["available"] is True
    assert block["downhill_km"] == 0.0
    assert block["flag"] is False


def test_downhill_degrades_without_altitude():
    dists = [i * 100.0 for i in range(101)]
    assert downhill_block(dists, None) == \
        {"available": False, "reason": "no_altitude"}
    assert downhill_block([0.0], [150.0]) == \
        {"available": False, "reason": "no_altitude"}


def test_downhill_degrades_without_forward_distance():
    """Дистанция не растёт → честная деградация no_distance."""
    assert downhill_block([100.0, 100.0, 90.0], [150.0, 145.0, 140.0]) == \
        {"available": False, "reason": "no_distance"}


# --- Интеграция workout_insights (schema v7) ------------------------------------

_seq = iter(range(89000, 89999))  # 95xxx занят test_stage0_fixes (shared in-memory DB)


def _user(db):
    n = next(_seq)
    return make_user(db, chat_id=n, email=f"week-{n}@example.com")


def _session_with_track(db, user_id, *, ttype="easy", duration_min=45.0, **kw):
    tps = build_trackpoints("long", duration_min=duration_min, base_pace=6.0, hr=140)
    dist_km = tps[-1]["dist"] / 1000.0
    return build_training_session(
        db, user_id, total_distance_km=round(dist_km, 2),
        duration_minutes=duration_min, training_type=ttype,
        trackpoints_json=serialize_trackpoints(tps), **kw)


def test_insights_week_structure_and_session_rpe(db_session):
    """Интервальная вчера + интервальная сегодня → hard_days_too_close в
    week_structure и в общем computed.flags; session_rpe = RPE × минуты."""
    assert INSIGHTS_SCHEMA_VERSION >= 7   # анти-даунгрейд: v7 = M4-блоки
    user = _user(db_session)
    build_training_session(db_session, user.id, training_type="interval",
                           begin_ts=utcnow() - timedelta(days=1))
    s = _session_with_track(db_session, user.id, ttype="interval",
                            begin_ts=utcnow())
    build_training_feedback(db_session, s.id, user.id, rating=6)

    computed = upsert_workout_insights(user.id, s.id, db=db_session)
    ws = computed["week_structure"]
    assert ws["available"] is True
    assert ws["session_is_quality"] is True
    assert ws["days_since_prev_quality"] == 1
    assert FLAG_HARD_DAYS_TOO_CLOSE in ws["flags"]
    assert FLAG_HARD_DAYS_TOO_CLOSE in computed["flags"]
    # Foster session-RPE: усилие × минуты, независимо от Coros
    sr = computed["session_rpe"]
    assert sr["available"] is True
    assert sr["rpe"] == 6
    assert sr["load_au"] == round(6 * 45.0)
    # соседние M4-блоки посчитаны и не флагуют на ровном треке
    assert computed["detraining"] == {"available": True, "days_off": 1,
                                      "flag": False}
    assert computed["downhill"]["available"] is True
    assert computed["downhill"]["flag"] is False


def test_insights_session_rpe_degrades_without_feedback(db_session):
    """Без RPE-фидбека → честная деградация no_rpe, флагов M4 нет."""
    user = _user(db_session)
    s = _session_with_track(db_session, user.id, ttype="easy")
    computed = upsert_workout_insights(user.id, s.id, db=db_session)
    assert computed["session_rpe"] == {"available": False, "reason": "no_rpe"}
    assert computed["week_structure"]["session_is_quality"] is False
    assert computed["week_structure"]["flags"] == []


def test_insights_downhill_gated_by_gps_unreliable(db_session):
    """gps_unreliable → downhill честно недоступен (дистанции — мусор)."""
    user = _user(db_session)
    s = _session_with_track(
        db_session, user.id, ttype="easy",
        gps_quality={"unreliable": True,
                     "distance": {"quality": "estimate", "estimated_km": 6.0}})
    computed = compute_workout_metrics(s, max_hr=177)
    assert computed["downhill"] == {"available": False,
                                    "reason": "gps_unreliable"}


def test_insights_no_trackpoints_branch_still_checks_week(db_session):
    """Legacy-сессия без трекпоинтов: week_structure/detraining всё равно
    считаются из истории, флаг близости качественных попадает в flags."""
    user = _user(db_session)
    build_training_session(db_session, user.id, training_type="interval",
                           begin_ts=utcnow() - timedelta(days=1))
    s = build_training_session(db_session, user.id, training_type="interval",
                               begin_ts=utcnow())
    computed = upsert_workout_insights(user.id, s.id, db=db_session)
    assert computed["week_structure"]["available"] is True
    assert FLAG_HARD_DAYS_TOO_CLOSE in computed["week_structure"]["flags"]
    assert FLAG_HARD_DAYS_TOO_CLOSE in computed["flags"]
    assert computed["detraining"]["days_off"] == 1
    assert computed["downhill"] == {"available": False,
                                    "reason": "no_trackpoints"}
