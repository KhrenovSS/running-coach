# Тесты условия напоминания о скриншоте сна (#257)
from datetime import date

from src.coach import orchestrator
from src.models import DailyMetrics
from src.services.sleep_ingest import SLEEP_SOURCE
from src.telegram.jobs.sleep_reminder import _needs_reminder
from tests.coach.conftest import _unique_user


def test_reminder_needed_when_no_sleep_shot(db_session):
    user = _unique_user(db_session)
    assert _needs_reminder(user, db=db_session) is True


def test_no_reminder_when_shot_present_today(db_session):
    user = _unique_user(db_session)
    db_session.add(DailyMetrics(user_id=user.id, date=date.today(),
                                sleep_duration_min=440, sleep_source=SLEEP_SOURCE))
    db_session.commit()
    assert _needs_reminder(user, db=db_session) is False


def test_reminder_still_needed_when_only_hrv_present(db_session):
    """HRV из Coros-синка есть, но скрина сна нет → напоминание нужно."""
    user = _unique_user(db_session)
    db_session.add(DailyMetrics(user_id=user.id, date=date.today(),
                                avg_sleep_hrv=62.0, source_brand="coros"))
    db_session.commit()
    assert _needs_reminder(user, db=db_session) is True


def test_no_reminder_when_initiative_low(db_session):
    user = _unique_user(db_session)
    orchestrator.set_initiative(user.id, "low", db=db_session)
    assert _needs_reminder(user, db=db_session) is False
