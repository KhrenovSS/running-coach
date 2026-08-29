# Тесты конвертации UTC → локальный пояс (Tests for UTC → local time conversion)
from datetime import datetime, timezone
from types import SimpleNamespace

from src.utils.timeutils import fmt_local, local_dt, session_local_dt, user_now

UTC_DT = datetime(2026, 8, 26, 15, 12, 26, tzinfo=timezone.utc)


def _user(tz):
    return SimpleNamespace(timezone=tz)


def _session(tz):
    return SimpleNamespace(timezone=tz)


def test_none_returns_none():
    assert local_dt(None, _user("Europe/Moscow")) is None


def test_bug_case_moscow():
    # Инцидент 26.08.2026: бот показал 15:12 UTC вместо 18:12 MSK
    # (Incident 2026-08-26: bot showed 15:12 UTC instead of 18:12 MSK)
    local = local_dt(UTC_DT, _user("Europe/Moscow"))
    assert local.strftime("%d.%m.%Y %H:%M") == "26.08.2026 18:12"


def test_user_tz_wins_over_session_tz():
    local = local_dt(UTC_DT, _user("Asia/Dubai"), _session("Europe/Moscow"))
    assert local.hour == 19  # Dubai UTC+4


def test_session_tz_when_user_empty():
    local = local_dt(UTC_DT, _user(None), _session("Europe/Moscow"))
    assert local.hour == 18


def test_session_tz_string_fallback():
    # session_tz — для мест, где ORM-объекта уже нет (dict из new_trainings)
    # (session_tz — for call sites holding only a dict, not the ORM object)
    local = local_dt(UTC_DT, _user(None), session_tz="Europe/Moscow")
    assert local.hour == 18


def test_settings_fallback_when_all_empty():
    # Пусто у user и session → берётся settings.timezone (значение зависит от env)
    # (Both empty → settings.timezone; value depends on env)
    from zoneinfo import ZoneInfo
    from src.config import settings
    local = local_dt(UTC_DT, _user(None))
    assert local == UTC_DT.astimezone(ZoneInfo(settings.timezone))


def test_naive_treated_as_utc():
    naive = datetime(2026, 8, 26, 15, 12, 26)
    local = local_dt(naive, _user("Europe/Moscow"))
    assert local.hour == 18


def test_no_user_object():
    local = local_dt(UTC_DT, None, _session("Europe/Moscow"))
    assert local.hour == 18


def test_session_local_dt_prefers_workout_zone():
    # Тренировка в поездке показывается в её поясе (workout zone wins)
    local = session_local_dt(UTC_DT, _session("Asia/Dubai"), _user("Europe/Moscow"))
    assert local.hour == 19  # Dubai UTC+4


def test_session_local_dt_falls_back_to_user():
    local = session_local_dt(UTC_DT, _session(None), _user("Europe/Moscow"))
    assert local.hour == 18
    local = session_local_dt(UTC_DT, None, _user("Europe/Moscow"))
    assert local.hour == 18


def test_user_now_is_aware_in_user_zone():
    from zoneinfo import ZoneInfo
    now = user_now(_user("Europe/Moscow"))
    assert now.tzinfo == ZoneInfo("Europe/Moscow")


def test_fmt_local():
    local = local_dt(UTC_DT, _user("Europe/Moscow"))
    assert fmt_local(local) == "2026-08-26 18:12 (Europe/Moscow)"
