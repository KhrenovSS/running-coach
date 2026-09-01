# Тесты F4/M3.1: LTHR по пайплайну анализа — классификация, process_trackpoints,
# резолверы latest_lthr/latest_ltsp, workout_insights (зоны по LTHR-лестнице).
# (F4/M3.1: LTHR through the analysis pipeline — classification gates, zone ladder,
# freshness-window resolvers, insights integration.)

from datetime import date, timedelta

import pytest

from src.analysis import process_trackpoints
from src.analysis.classify import classify_training
from src.analysis.utils import serialize_trackpoints
from src.services.repositories import latest_lthr, latest_ltsp
from src.services.workout_insights import upsert_workout_insights
from tests.helpers import (build_daily_metrics, build_recovery_trackpoints,
                           build_trackpoints, build_training_session, make_user)

_seq = iter(range(88000, 88999))  # свой диапазон (94xxx занят test_hr_max)


def _user(db, **kw):
    n = next(_seq)
    return make_user(db, chat_id=n, email=f"lthr-{n}@example.com", **kw)


# --- classify_training: гейты от LTHR вместо %max_hr ---

def _classify(avg_hr, lthr=None, **kw):
    """Минимальные аргументы easy-кандидата: Z2 доминирует, без осцилляций."""
    args = dict(var_count=0, time_in_zone={2: 24.0, 3: 6.0},
                total_duration_min=30.0, max_hr=180, z4_plus_segments=[],
                avg_hr=avg_hr, segments_len=5, avg_pace=5.5, lthr=lthr)
    args.update(kw)
    return classify_training(**args)


class TestClassifyLthrGates:
    def test_avg140_easy_only_with_lthr(self):
        """avg_hr=140 при max_hr=180: fallback-гейт easy 135 → tempo;
        с LTHR=160 гейт 0.89·160=142.4 → easy."""
        assert _classify(140)[0] == 'tempo'
        assert _classify(140, lthr=160)[0] == 'easy'

    def test_recovery_gate_widens_with_lthr(self):
        """avg_hr=127: fallback recovery-гейт 126 → easy; с LTHR=160 гейт
        0.81·160=129.6 (и темп >6) → recovery."""
        assert _classify(127, avg_pace=6.5)[0] == 'easy'
        assert _classify(127, lthr=160, avg_pace=6.5)[0] == 'recovery'

    def test_interval_confirmation_requires_avg_at_lthr(self):
        """Осцилляции без HR-корреляции: fallback подтверждает avg ≥ 0.87·max
        (156.6) → interval при 158; с LTHR=165 порог = сам LTHR → не interval."""
        kw = dict(time_in_zone={3: 15.0, 4: 15.0}, oscillation_count=4,
                  hr_correlated=False, var_count=4)
        assert _classify(158, **kw)[0] == 'interval'
        assert _classify(158, lthr=165, **kw)[0] == 'tempo'

    def test_invalid_lthr_keeps_fallback_gates(self):
        """Невалидный lthr (выше max_hr) → прежние %max_hr-гейты."""
        assert _classify(140, lthr=200)[0] == 'tempo'


# --- process_trackpoints: lthr прокинут до классификации и зон сегментов ---

class TestProcessTrackpointsLthr:
    @pytest.fixture(autouse=True)
    def _no_weather(self, monkeypatch):
        # офлайн: погодный API не дёргаем (offline: no weather API calls)
        monkeypatch.setattr("src.analysis.fetch_weather", lambda *a, **k: None)

    @staticmethod
    def _easy_tps():
        # Ровный бег HR=140, 40 мин, темп 5.8 — без осцилляций и Z4
        return build_recovery_trackpoints(base_pace=5.8, duration_min=40.0,
                                          hr=140, max_hr=180)

    def test_easy_run_classified_easy_only_with_lthr(self):
        """HR 140 при max_hr 180: без lthr avg выше easy-гейта 135 → tempo;
        с lthr=160 гейт 142.4 → easy."""
        tps = self._easy_tps()
        base = process_trackpoints(tps, tps[0]['time'], max_hr=180, pace_gap=1.0)
        with_lthr = process_trackpoints(tps, tps[0]['time'], max_hr=180,
                                        pace_gap=1.0, lthr=160)
        assert base is not None and with_lthr is not None
        assert base['training_type'] == 'tempo'
        assert with_lthr['training_type'] == 'easy'

    def test_segment_zones_follow_lthr_ladder(self):
        """Зоны сегментов: HR 140 → Z2 по fallback (≤144), Z3 от LTHR 156 (>138.84)."""
        tps = self._easy_tps()
        base = process_trackpoints(tps, tps[0]['time'], max_hr=180, pace_gap=1.0)
        with_lthr = process_trackpoints(tps, tps[0]['time'], max_hr=180,
                                        pace_gap=1.0, lthr=156)
        base_zones = [s['zone'] for s in base['segments_json'] if s.get('zone')]
        lthr_zones = [s['zone'] for s in with_lthr['segments_json'] if s.get('zone')]
        assert base_zones and all(z == 2 for z in base_zones)
        assert lthr_zones and all(z == 3 for z in lthr_zones)


# --- Резолверы latest_lthr / latest_ltsp (окно 45 дней, NULL пропускается) ---

class TestLatestLthrLtsp:
    def test_fresh_row_returns_values(self, db_session):
        user = _user(db_session)
        build_daily_metrics(db_session, user.id, lthr=162, ltsp=321.0)
        assert latest_lthr(user.id, db=db_session) == 162
        assert latest_ltsp(user.id, db=db_session) == 321.0

    def test_stale_row_returns_none(self, db_session):
        """Строка старше 45 дней → None (устаревший порог не используем)."""
        user = _user(db_session)
        build_daily_metrics(db_session, user.id,
                            metric_date=date.today() - timedelta(days=46),
                            lthr=150, ltsp=330.0)
        assert latest_lthr(user.id, db=db_session) is None
        assert latest_ltsp(user.id, db=db_session) is None

    def test_null_values_skipped(self, db_session):
        """Свежая строка с NULL не затеняет более старую ненулевую."""
        user = _user(db_session)
        build_daily_metrics(db_session, user.id,
                            metric_date=date.today() - timedelta(days=3),
                            lthr=158, ltsp=325.0)
        build_daily_metrics(db_session, user.id, metric_date=date.today(),
                            lthr=None, ltsp=None)
        assert latest_lthr(user.id, db=db_session) == 158
        assert latest_ltsp(user.id, db=db_session) == 325.0

    def test_no_rows_returns_none(self, db_session):
        user = _user(db_session)
        assert latest_lthr(user.id, db=db_session) is None
        assert latest_ltsp(user.id, db=db_session) is None


# --- workout_insights: upsert резолвит lthr → time_in_zones по LTHR-лестнице ---

class TestInsightsUseLthr:
    @staticmethod
    def _session(db, user_id):
        # Ровный бег HR=140, 30 мин: Z2 по fallback (max_hr=180), Z3 от LTHR 156
        tps = build_trackpoints('long', duration_min=30.0, base_pace=6.2, hr=140)
        dist_km = tps[-1]['dist'] / 1000.0
        return build_training_session(
            db, user_id, total_distance_km=round(dist_km, 2),
            duration_minutes=30.0, training_type='easy',
            trackpoints_json=serialize_trackpoints(tps))

    def test_time_in_zones_from_lthr_ladder(self, db_session):
        """DailyMetrics(lthr=156) → HR 140 попадает в Z3, а не в Z2."""
        user = _user(db_session, max_hr=180)
        build_daily_metrics(db_session, user.id, lthr=156)
        s = self._session(db_session, user.id)
        computed = upsert_workout_insights(user.id, s.id, db=db_session)
        tz = computed["time_in_zones"]
        assert tz["available"] is True
        assert tz["minutes"]["z3"] > 25
        assert tz["minutes"]["z2"] == 0

    def test_time_in_zones_fallback_without_lthr(self, db_session):
        """Без DailyMetrics — прежняя %max_hr-лестница: HR 140 → Z2."""
        user = _user(db_session, max_hr=180)
        s = self._session(db_session, user.id)
        computed = upsert_workout_insights(user.id, s.id, db=db_session)
        tz = computed["time_in_zones"]
        assert tz["available"] is True
        assert tz["minutes"]["z2"] > 25
        assert tz["minutes"]["z3"] == 0
