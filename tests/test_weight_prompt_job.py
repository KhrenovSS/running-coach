# Еженедельный опрос веса (02.10.2026): только в день взвешивания и только тем, кто не
# вводил вес на этой неделе. (Weekly weigh-in prompt — day gate and this-week dedup.)

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.config.constants import WEIGHT_PROMPT_WEEKDAY, WEIGHT_PROMPT_HOURS
from src.domain.models import WeightMeasurement
from src.telegram.jobs.weight import (WEIGHT_PROMPT_PTB_DAYS, is_weigh_in_day, users_to_prompt,
                                      prompt_text, week_start)
from tests.helpers import make_user

MSK = ZoneInfo("Europe/Moscow")
SUNDAY = datetime(2026, 10, 4, 9, 0, tzinfo=MSK)   # воскресенье (Sunday)


def _user(db, n: int):
    # chat_id уникален в общей SQLite-базе сессии (unique across the shared test DB)
    return make_user(db, chat_id=7_020_100 + n, email=f"wprompt_{n}@example.com")


def test_weigh_in_day_is_sunday_and_ptb_mapping():
    assert WEIGHT_PROMPT_WEEKDAY == 6 and is_weigh_in_day(SUNDAY)
    assert not is_weigh_in_day(SUNDAY - timedelta(days=1))
    # PTB нумерует с воскресенья = 0 (PTB: Sunday is 0)
    assert WEIGHT_PROMPT_PTB_DAYS == (0,)
    assert WEIGHT_PROMPT_HOURS[0] == 9


def test_week_start_is_local_monday():
    assert week_start(SUNDAY) == datetime(2026, 9, 28, 0, 0, tzinfo=MSK)


def test_no_prompt_outside_weigh_in_day(db_session):
    _user(db_session, 1)
    assert users_to_prompt(db_session, SUNDAY - timedelta(days=2)) == []


def test_prompt_only_users_without_weight_this_week(db_session):
    fresh = _user(db_session, 2)
    weighed_this_week = _user(db_session, 3)
    weighed_last_week = _user(db_session, 4)
    db_session.add_all([
        WeightMeasurement(user_id=weighed_this_week.id, weight_kg=74.0,
                          measured_at=SUNDAY - timedelta(days=3)),       # четверг этой недели
        WeightMeasurement(user_id=weighed_last_week.id, weight_kg=74.0,
                          measured_at=SUNDAY - timedelta(days=8)),       # прошлая неделя
    ])
    db_session.commit()

    ids = {u.id for u in users_to_prompt(db_session, SUNDAY)}
    assert fresh.id in ids and weighed_last_week.id in ids
    assert weighed_this_week.id not in ids


def test_prompt_text_morning_vs_reminder():
    assert "Доброе утро" in prompt_text(SUNDAY)
    assert "Напоминание" in prompt_text(SUNDAY.replace(hour=15))
