# Тесты сервиса физио-метрик (workout insights service tests) — DEV_PLAN §9 D2

import json
from datetime import timedelta

from src.analysis.utils import serialize_trackpoints
from src.config.constants import HEAT_TEMP_THRESHOLD_C
from src.domain.models.base import utcnow
from src.models import UserModel
from src.services.repositories_insights import InsightRepository
from src.services.workout_insights import (
    INSIGHTS_SCHEMA_VERSION,
    ensure_baseline,
    expected_pace_at_hr,
    get_or_compute,
    refresh_hr_pace_baseline,
    upsert_workout_insights,
)
from tests.helpers import build_trackpoints, build_training_session, make_user

_seq = iter(range(93000, 93999))


def _user(db):
    n = next(_seq)
    return make_user(db, chat_id=n, email=f"insights-{n}@example.com")


def _session_with_track(db, user_id, *, duration_min=45.0, hr=140, base_pace=6.0,
                        hr_drift_bpm=0.0, grade_pct=0.0, ttype='easy', **kw):
    tps = build_trackpoints('long', duration_min=duration_min, base_pace=base_pace,
                            hr=hr, hr_drift_bpm=hr_drift_bpm, grade_pct=grade_pct)
    dist_km = tps[-1]['dist'] / 1000.0
    return build_training_session(
        db, user_id, total_distance_km=round(dist_km, 2),
        duration_minutes=duration_min, training_type=ttype,
        trackpoints_json=serialize_trackpoints(tps), **kw)


def test_full_cycle_computed_json_valid(db_session):
    """Полный цикл: сессия с треком → upsert → все секции валидны и JSON-сериализуемы."""
    user = _user(db_session)
    s = _session_with_track(db_session, user.id, hr_drift_bpm=20,
                            avg_temperature=HEAT_TEMP_THRESHOLD_C + 4)
    computed = upsert_workout_insights(user.id, s.id, db=db_session)
    assert computed["schema_version"] == INSIGHTS_SCHEMA_VERSION
    assert computed["drift"]["applicable"] is True
    assert computed["drift"]["flag"] == "high"
    assert computed["gap"]["available"] is True
    assert computed["heat"]["heat_flag"] is True
    assert "decoupling_high" in computed["flags"]
    assert "heat" in computed["flags"]
    json.dumps(computed)  # сериализуемость для JSON-колонки и промпта
    row = InsightRepository.for_session(user.id, s.id, db=db_session)
    assert row.computed_json["drift"]["flag"] == "high"
    assert row.schema_version == INSIGHTS_SCHEMA_VERSION


def test_gap_per_km_rows_carry_km_len_m(db_session):
    """F0 #278/#283 (schema v5): строки per_km несут фактическую длину строки —
    полные км ≈ 1000 м, хвост короче; сводный темп взвешен дистанцией."""
    assert INSIGHTS_SCHEMA_VERSION >= 5   # анти-даунгрейд: v5 = km_len_m в per_km
    user = _user(db_session)
    s = _session_with_track(db_session, user.id, duration_min=45.0, base_pace=6.0)
    computed = upsert_workout_insights(user.id, s.id, db=db_session)
    gap = computed["gap"]
    assert gap["available"] is True
    rows = gap["per_km"]
    assert all("km_len_m" in r for r in rows)
    assert all(950 <= r["km_len_m"] <= 1050 for r in rows[:-1])  # полные км
    # 45' по 6:00 → 7.5 км: хвостовая строка ~500 м, не полный км
    assert rows[-1]["km_len_m"] < 600
    # взвешенное дистанцией среднее = Σ(pace·len)/Σlen
    expected = (sum(r["pace_min_km"] * r["km_len_m"] for r in rows)
                / sum(r["km_len_m"] for r in rows))
    assert abs(gap["avg_pace_min_km"] - expected) <= 0.01


def test_legacy_session_without_trackpoints(db_session):
    """Legacy-сессия без трекпоинтов → минимальный dict, без исключений."""
    user = _user(db_session)
    s = build_training_session(db_session, user.id, training_type='easy')
    computed = upsert_workout_insights(user.id, s.id, db=db_session)
    assert computed["drift"] == {**computed["drift"], "applicable": False,
                                 "reason": "no_trackpoints"}
    assert computed["gap"]["available"] is False
    assert computed["flags"] == []


def test_get_or_compute_recomputes_stale_schema(db_session):
    """Устаревший schema_version в БД → get_or_compute пересчитывает."""
    user = _user(db_session)
    s = _session_with_track(db_session, user.id)
    InsightRepository.upsert(user.id, s.id, db=db_session,
                             computed={"schema_version": 0}, schema_version=0)
    computed = get_or_compute(user.id, s.id, db=db_session)
    assert computed["schema_version"] == INSIGHTS_SCHEMA_VERSION


def test_get_or_compute_returns_stored(db_session):
    """Актуальная запись возвращается как есть (без пересчёта)."""
    user = _user(db_session)
    s = _session_with_track(db_session, user.id)
    first = upsert_workout_insights(user.id, s.id, db=db_session)
    again = get_or_compute(user.id, s.id, db=db_session)
    assert again == first  # идемпотентно (включая computed_at — не пересчитан)


def test_ownership_enforced(db_session):
    """Чужая сессия → None."""
    user, stranger = _user(db_session), _user(db_session)
    s = _session_with_track(db_session, user.id)
    assert upsert_workout_insights(stranger.id, s.id, db=db_session) is None


def test_baseline_accumulates_and_preserves_initiative(db_session):
    """Baseline появляется после накопления steady-сессий; initiative не затёрт."""
    user = _user(db_session)
    um = UserModel(user_id=user.id, params_json={"initiative": "low"})
    db_session.add(um)
    db_session.commit()
    # 6 длинных easy-сессий с разными темпами (нужна дисперсия по x для OLS)
    # × ~7 км-точек (первый км исключается) > 30 точек; HR по закону 190−8·pace
    for i in range(6):
        pace = 5.5 + i * 0.2
        s = _session_with_track(db_session, user.id, duration_min=50.0,
                                base_pace=pace, hr=round(190 - 8 * pace),
                                ttype='easy',
                                begin_ts=utcnow() - timedelta(days=i * 3))
        upsert_workout_insights(user.id, s.id, db=db_session)
    db_session.expire_all()
    um = db_session.query(UserModel).filter_by(user_id=user.id).first()
    baseline = (um.params_json or {}).get("hr_pace_baseline")
    assert baseline is not None
    assert baseline["b"] < 0
    assert baseline["n_sessions"] >= 5
    assert um.params_json["initiative"] == "low"  # merge, не перезапись


def test_ensure_baseline_bootstraps_missing_insights(db_session):
    """Прод-кейс 26.08: insights пусты → ensure_baseline досчитывает их по
    steady-сессиям окна и строит линию; повторный вызов — из хранилища."""
    user = _user(db_session)
    for i in range(6):
        pace = 5.5 + i * 0.2
        _session_with_track(db_session, user.id, duration_min=50.0,
                            base_pace=pace, hr=round(190 - 8 * pace),
                            ttype='easy',
                            begin_ts=utcnow() - timedelta(days=i * 3))
    from src.models import WorkoutInsight
    assert db_session.query(WorkoutInsight).filter_by(
        user_id=user.id).count() == 0
    baseline = ensure_baseline(user.id, db=db_session)
    assert baseline is not None
    assert baseline["b"] < 0
    assert baseline["n_sessions"] >= 5
    # идемпотентность: второй вызов возвращает сохранённое, не пересчитывает
    assert ensure_baseline(user.id, db=db_session) == baseline


def test_expected_pace_at_hr_from_band_median(db_session):
    """Эмпирический темп на пульсе: медиана км-точек полосы, без экстраполяции.

    Сессии по закону HR = 190 − 8·pace (темпы 5.5..6.5 → HR 138..146).
    Потолок 144 → полоса HR 134..144 → темпы ≈5.75..6.5, медиана внутри.
    Инцидент смоука 26.08: инверсия OLS давала 3:49/км бегуну с лёгким 8:00.
    """
    user = _user(db_session)
    for i in range(6):
        pace = 5.5 + i * 0.2
        _session_with_track(db_session, user.id, duration_min=50.0,
                            base_pace=pace, hr=round(190 - 8 * pace),
                            ttype='easy',
                            begin_ts=utcnow() - timedelta(days=i * 3))
    est = expected_pace_at_hr(user.id, 144, db=db_session)   # бутстрап внутри
    assert est is not None
    assert 5.5 <= est["pace_min_km"] <= 6.6   # в диапазоне реальных темпов полосы
    assert est["n_points"] >= 5
    # пульс, на котором пользователь не бегал → честный None
    assert expected_pace_at_hr(user.id, 110, db=db_session) is None


def test_ensure_baseline_few_data_returns_none(db_session):
    """Одна сессия → бутстрап не выдаёт ложную точность (None, без исключений)."""
    user = _user(db_session)
    _session_with_track(db_session, user.id, ttype='easy', begin_ts=utcnow())
    assert ensure_baseline(user.id, db=db_session) is None


def test_baseline_absent_with_few_sessions(db_session):
    """2 сессии → baseline отсутствует (мало данных, не ложная точность)."""
    user = _user(db_session)
    for i in range(2):
        s = _session_with_track(db_session, user.id, ttype='easy',
                                begin_ts=utcnow() - timedelta(days=i))
        upsert_workout_insights(user.id, s.id, db=db_session)
    baseline = refresh_hr_pace_baseline(user.id, db=db_session)
    assert baseline is None
    um = db_session.query(UserModel).filter_by(user_id=user.id).first()
    assert "hr_pace_baseline" not in (um.params_json or {})


def test_m1_blocks_present_and_easy_discipline_flag(db_session):
    """M1 (METRICS_GUIDE §4): computed v2 содержит новые блоки; лёгкая,
    пробежанная в Z3+, ловит easy_run_too_hard детерминированно."""
    user = _user(db_session)
    # hr=150 при max_hr=177 → Z3: вся «лёгкая» выше Z2
    s = _session_with_track(db_session, user.id, hr=150, ttype='easy')
    computed = upsert_workout_insights(user.id, s.id, db=db_session)
    for key in ("time_in_zones", "easy_discipline", "pace_stability",
                "hr_stability", "load_points", "quality_volume",
                "long_run", "cadence", "rpe", "warmup"):
        assert key in computed, key
    assert computed["time_in_zones"]["available"] is True
    assert computed["easy_discipline"]["flag"] is True
    assert "easy_run_too_hard" in computed["flags"]
    assert computed["load_points"]["available"] is True
    # ровный синтетический темп → стабильность считается и не флагуется
    assert computed["pace_stability"]["available"] is True
    assert computed["pace_stability"]["flag"] is False
    assert computed["hr_stability"]["available"] is True
    # drift v2: чистый дрейф в bpm присутствует
    assert "drift_bpm" in computed["drift"]
    json.dumps(computed)


def test_m1_week_km_feeds_long_run_share(db_session):
    """Единственная длительная в неделе → доля ≈100% → long_run_share_high."""
    user = _user(db_session)
    s = _session_with_track(db_session, user.id, ttype='long')
    computed = upsert_workout_insights(user.id, s.id, db=db_session)
    lr = computed["long_run"]
    assert lr["applicable"] is True
    assert lr["share_of_week"] > 0.9
    assert "long_run_share_high" in computed["flags"]


def test_plan_vs_actual_links_recommendation(db_session):
    """M2.2: назначение на локальную дату сессии → блок plan_vs_actual в computed,
    linked_session_id заполняется (колонка жила мёртвой с C4)."""
    from src.models import Recommendation

    user = _user(db_session)
    s = _session_with_track(db_session, user.id, hr=150, ttype='easy')
    rec = Recommendation(user_id=user.id, for_date=s.begin_ts.date(),
                         workout_type="easy",
                         target_json={"max_zone": 2},
                         volume_json={"duration_min": 40.0},
                         status="proposed", source="llm")
    db_session.add(rec)
    db_session.commit()

    computed = upsert_workout_insights(user.id, s.id, db=db_session)
    pva = computed["plan_vs_actual"]
    assert pva["available"] is True
    assert pva["type_match"] is True
    # факт весь в Z3 (hr=150) при плане Z2 → интенсивность превышена
    assert pva["pct_above_planned_zone"] > 0.9
    assert "plan_intensity_exceeded" in computed["flags"]
    db_session.refresh(rec)
    assert rec.linked_session_id == s.id


def test_plan_vs_actual_absent_without_recommendation(db_session):
    user = _user(db_session)
    s = _session_with_track(db_session, user.id)
    computed = upsert_workout_insights(user.id, s.id, db=db_session)
    assert computed["plan_vs_actual"]["available"] is False
    assert computed["plan_vs_actual"]["reason"] == "no_plan"


def test_gps_unreliable_gates_pace_blocks_keeps_hr(db_session):
    """v4: GPS недостоверен → pace-производные блоки честно недоступны с
    reason='gps_unreliable', HR-блоки (time_in_zones) считаются; флаг — первым."""
    from src.services.workout_insights import compute_workout_metrics

    user = _user(db_session)
    s = _session_with_track(
        db_session, user.id, hr=140,
        gps_quality={"unreliable": True,
                     "distance": {"quality": "estimate", "estimated_km": 6.5}})
    computed = compute_workout_metrics(
        s, max_hr=177, plan={"type": "easy", "max_zone": 3, "duration_min": 45})

    assert computed["inputs"]["gps_quality"]["unreliable"] is True
    assert computed["gap"] == {"available": False, "reason": "gps_unreliable"}
    assert computed["drift"]["applicable"] is False
    assert computed["drift"]["reason"] == "gps_unreliable"
    assert computed["hr_vs_baseline"]["reason"] == "gps_unreliable"
    assert computed["pace_stability"] == {"available": False,
                                          "reason": "gps_unreliable"}
    assert computed["quality_volume"] == {"available": False,
                                          "reason": "gps_unreliable"}
    # HR-производные метрики не гейтятся (HR-derived blocks still computed)
    assert computed["time_in_zones"]["available"] is True
    assert computed["hr_stability"]["available"] is True
    # объём в plan_vs_actual помечен «по оценке» (volume marked as estimate)
    assert computed["plan_vs_actual"]["distance_quality"] == "estimate"
    assert "gps_unreliable" in computed["flags"]
    assert computed["flags"][0] == "gps_unreliable"
    json.dumps(computed)


def test_gps_reliable_does_not_gate(db_session):
    """unreliable=False → gap/pace_stability считаются как обычно."""
    from src.services.workout_insights import compute_workout_metrics

    user = _user(db_session)
    s = _session_with_track(db_session, user.id,
                            gps_quality={"unreliable": False})
    computed = compute_workout_metrics(s, max_hr=177)
    assert computed["gap"]["available"] is True
    assert computed["pace_stability"]["available"] is True
    assert "gps_unreliable" not in computed["flags"]


def test_interval_recovery_from_laps_poor_hrr_flags(db_session):
    """F3 (schema v6): интервальная со структурными лапами и слабым падением HR →
    interval_recovery по лапам, флаг poor_interval_recovery в computed.flags;
    строка сохраняется через upsert (полный БД-путь, max_hr пользователя 177)."""
    from tests.helpers_intervals import (build_hrr_trackpoints, build_laps,
                                         interval_workout)

    assert INSIGHTS_SCHEMA_VERSION >= 6   # анти-даунгрейд: v6 = interval_recovery
    user = _user(db_session)
    # rest_end=135: хвост отдыха уходит в Z2 при max_hr=177 — граница
    # отдых→работа честно пропускается гейтом зоны
    segs, meta = interval_workout(drop60=6, rest_end=135)
    s = build_training_session(
        db_session, user.id, training_type='interval',
        total_distance_km=4.0, duration_minutes=22.0,
        trackpoints_json=build_hrr_trackpoints(segs),
        laps_json=build_laps(meta))
    computed = upsert_workout_insights(user.id, s.id, db=db_session)
    ir = computed["interval_recovery"]
    assert ir["available"] is True
    assert ir["source"] == "laps"
    assert ir["reps"] == 4
    assert ir["flag"] is True
    assert "poor_interval_recovery" in computed["flags"]
    json.dumps(computed)
    row = InsightRepository.for_session(user.id, s.id, db=db_session)
    assert row.computed_json["interval_recovery"]["flag"] is True


def test_interval_recovery_laps_survive_gps_unreliable(db_session):
    """gps_unreliable гейтит pace-блоки, но HRR по лапам (время+пульс) считается;
    fallback-осцилляции при этом отключены (dists не передаются)."""
    from src.services.workout_insights import compute_workout_metrics
    from tests.helpers_intervals import (build_hrr_trackpoints, build_laps,
                                         interval_workout)

    user = _user(db_session)
    segs, meta = interval_workout(drop60=25)   # нормальное восстановление
    s = build_training_session(
        db_session, user.id, training_type='interval',
        total_distance_km=4.0, duration_minutes=22.0,
        trackpoints_json=build_hrr_trackpoints(segs),
        laps_json=build_laps(meta),
        gps_quality={"unreliable": True,
                     "distance": {"quality": "estimate", "estimated_km": 4.0}})
    computed = compute_workout_metrics(s, max_hr=180)
    assert computed["gap"] == {"available": False, "reason": "gps_unreliable"}
    ir = computed["interval_recovery"]
    assert ir["available"] is True
    assert ir["source"] == "laps"
    assert ir["flag"] is False
    assert "gps_unreliable" in computed["flags"]
    assert "poor_interval_recovery" not in computed["flags"]


def test_zone_anchor_visibility(db_session):
    """1d (02.09): inputs.zone_anchor = 'lthr' при валидном LTHR, 'max_hr' при
    отсутствии/невалидности — тихий fallback %max_hr теперь наблюдаем."""
    from src.services.workout_insights import compute_workout_metrics

    user = _user(db_session)
    s = _session_with_track(db_session, user.id)
    anchor = lambda **kw: compute_workout_metrics(s, **kw)["inputs"]["zone_anchor"]
    assert anchor(max_hr=177, lthr=170) == "lthr"
    assert anchor(max_hr=177, lthr=None) == "max_hr"
    assert anchor(max_hr=177, lthr=180) == "max_hr"      # lthr ≥ max_hr — невалиден
    assert anchor(max_hr=177, lthr=95) == "max_hr"       # ниже санити-минимума
    # ветка без трекпоинтов: якорь проставлен и в раннем выходе
    legacy = build_training_session(db_session, user.id, training_type='easy')
    got = compute_workout_metrics(legacy, max_hr=177, lthr=170)
    assert got["inputs"]["zone_anchor"] == "lthr"


def test_baseline_and_data_check_reexports_alive():
    """Рефактор F3: baseline вынесен в insights_baseline, device/lap_check —
    в analysis/data_checks; старые импорты из workout_insights живы (реэкспорт)."""
    from src.analysis import data_checks
    from src.services import insights_baseline, workout_insights

    for name in ("ensure_baseline", "expected_hr_at_pace",
                 "expected_pace_at_hr", "refresh_hr_pace_baseline"):
        assert getattr(workout_insights, name) is getattr(insights_baseline, name)
    assert workout_insights.device_check is data_checks.device_check
    assert workout_insights.lap_check is data_checks.lap_check


def test_plan_vs_actual_ignores_superseded_recommendation(db_session):
    """Погашенная перепланированием строка не линкуется к факту (02.09.2026)."""
    from src.models import Recommendation

    user = _user(db_session)
    s = _session_with_track(db_session, user.id, hr=150, ttype='easy')
    stale = Recommendation(user_id=user.id, for_date=s.begin_ts.date(),
                           workout_type="tempo", target_json={"max_zone": 3},
                           volume_json={"duration_min": 45.0},
                           status="superseded", source="llm")
    db_session.add(stale)
    db_session.commit()

    computed = upsert_workout_insights(user.id, s.id, db=db_session)
    assert computed["plan_vs_actual"]["available"] is False
    db_session.refresh(stale)
    assert stale.linked_session_id is None
