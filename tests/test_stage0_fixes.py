# Тесты Этапа 0 ремедиации (Stage 0 remediation tests):
# 1) /stats бота — агрегаты через sqlalchemy.func (раньше db.func → AttributeError)
# 2) reanalyze — колонка users.interval_min_phase_distance_m существует, пересчёт работает
# 3) performance — Float-колонка, дробная градация −2..+2 не теряется

import pytest
from sqlalchemy import Float

from src.analysis.utils import serialize_trackpoints
from src.domain.models import DailyMetrics
from src.services.reanalyze import reanalyze_training
from src.services.recovery_view import readiness_structured
from src.telegram.handlers.stats import StatsPages
from tests.helpers import (
    build_daily_metrics,
    build_trackpoints,
    build_training_session,
    make_user,
)


def _user(db, n: int):
    # In-memory БД живёт между тестами файла — email/chat_id должны быть уникальны
    # (In-memory DB persists across tests in a file — email/chat_id must be unique)
    return make_user(db, chat_id=95000 + n, email=f"stage0_{n}@example.com")


class TestStatsPages:
    def test_overview_aggregates_distance_and_duration(self, db_session):
        # До фикса падало AttributeError на db.func при первом же /stats
        # (Before the fix: AttributeError on db.func at the first /stats call)
        user = _user(db_session, 1)
        build_training_session(db_session, user.id, total_distance_km=10.0, duration_minutes=50.0)
        build_training_session(db_session, user.id, total_distance_km=5.0, duration_minutes=25.0)

        text = StatsPages(user).get_page("all")

        assert "Всего тренировок: 2" in text
        assert "15.0 км" in text
        assert "1ч 15м" in text

    def test_overview_empty_db_does_not_crash(self, db_session):
        user = _user(db_session, 2)
        text = StatsPages(user).get_page("all")
        assert "Всего тренировок: 0" in text

    def test_period_page_renders(self, db_session):
        user = _user(db_session, 3)
        build_training_session(db_session, user.id)
        text = StatsPages(user).get_page("week")
        assert isinstance(text, str) and text


class TestReanalyze:
    def test_reanalyze_recomputes_from_stored_trackpoints(self, db_session):
        # До фикса падало AttributeError: у User не было interval_min_phase_distance_m
        # (Before the fix: AttributeError — User had no interval_min_phase_distance_m)
        user = _user(db_session, 4)
        tps = build_trackpoints(training_type='tempo', distance_km=8.0)
        session = build_training_session(
            db_session, user.id,
            begin_ts=tps[0]['time'],
            trackpoints_json=serialize_trackpoints(tps),
        )

        result = reanalyze_training(db_session, session.id, user.id)

        assert result is not None
        assert result['training_type']
        db_session.refresh(session)
        # сырой ярлык — в training_type_auto; итоговый может быть переразмечен резолвером по плану (04.09.2026)
        assert session.training_type_auto == result['training_type']

    def test_reanalyze_respects_user_phase_distance_threshold(self, db_session):
        # Новая колонка читается как пользовательский порог (New column is read as user threshold)
        user = _user(db_session, 5)
        user.interval_min_phase_distance_m = 150
        db_session.commit()

        tps = build_trackpoints(training_type='interval')
        session = build_training_session(
            db_session, user.id,
            begin_ts=tps[0]['time'],
            trackpoints_json=serialize_trackpoints(tps),
        )

        result = reanalyze_training(db_session, session.id, user.id)
        assert result is not None


class TestPerformanceFloat:
    def test_performance_column_is_float(self):
        # Гвард от регрессии типа: Integer в PG округлял float −2..+2 от Coros
        # (Type regression guard: Integer rounded Coros float −2..+2 in PG)
        assert isinstance(DailyMetrics.__table__.c.performance.type, Float)

    def test_fractional_performance_round_trip(self, db_session):
        user = _user(db_session, 6)
        dm = build_daily_metrics(db_session, user.id, performance=0.4, recovery_pct=None)
        db_session.refresh(dm)
        assert dm.performance == pytest.approx(0.4)

    def test_fractional_performance_readiness_gradation(self):
        # 0.4 → moderate (округление до 1 дало бы ready); 0.7 → ready; −0.6 → rest
        assert readiness_structured(performance=0.4)['status'] == 'moderate'
        assert readiness_structured(performance=0.7)['status'] == 'ready'
        assert readiness_structured(performance=-0.6)['status'] == 'rest'
