# Тесты фикса синка Coros 17.09.2026 (Coros sync fix tests, incident 17.09.2026)
#
# Инцидент: тренировка режимом Track Run (sportType 103) молча отбрасывалась фильтром {100, 101};
# ручной health-синк из web падал с TypeError (лишний kwarg `pending`); 2-часовое окно since
# теряло тренировки, выгруженные часами в облако с задержкой.
# (Track Run silently dropped; manual health sync raised TypeError; 2-hour since-window lost late uploads.)

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from src.config.constants import ACTIVITY_SYNC_LOOKBACK_DAYS
from src.services.sync import orchestrator
from src.services.sync import activities as act_mod
from src.watch import coros as coros_mod
from src.watch.coros import CorosWatchClient, SPORT_TYPES_RUN
from tests.helpers import make_user
from tests.test_auto_sync import _make_cred, _reload_cred


# --- Хелперы (helpers) ---------------------------------------------------------------------------

class _FakeResponse:
    """Минимальный ответ httpx: .json() и .raise_for_status() (minimal httpx-like response)."""

    def __init__(self, payload: dict):
        self._payload = payload

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        return None


def _authed_client(monkeypatch, data_list: list[dict]) -> CorosWatchClient:
    """Клиент с токеном и подменённым HTTP GET — сети нет (authenticated client, no network)."""
    client = CorosWatchClient("e@example.com", "pw")
    client.accesstoken = "t"
    client.user_id = "u"

    async def fake_get(url, params=None, headers=None):
        return _FakeResponse({"result": "0000", "data": {"totalPage": 1, "dataList": data_list}})

    monkeypatch.setattr(client.client, "get", fake_get)
    return client


def _act(label_id: int, sport_type: int, start_ts: int) -> dict:
    """Сырая запись Coros dataList (raw Coros dataList item)."""
    return {"labelId": label_id, "sportType": sport_type, "startTime": start_ts,
            "endTime": start_ts + 1800, "name": f"act-{label_id}", "distance": 5000, "workoutTime": 1800}


# --- A. Фильтр по sportType (sport-type filter) --------------------------------------------------

def test_list_activities_accepts_all_running_modes_and_drops_others(monkeypatch):
    """Все четыре беговых режима (100 Run, 101 Indoor, 102 Trail, 103 Track) проходят фильтр;
    велосипед (200) и неизвестный код (999) отбрасываются. Track Run 103 — регресс инцидента 17.09.2026."""
    base = 1_700_000_000
    data_list = [
        _act(1, 100, base + 10),
        _act(2, 101, base + 20),
        _act(3, 102, base + 30),
        _act(4, 103, base + 40),
        _act(5, 200, base + 50),   # bike
        _act(6, 999, base + 60),   # unknown
    ]
    client = _authed_client(monkeypatch, data_list)

    result = asyncio.run(client.list_activities(since=None))

    assert len(result) == 4
    assert [a["id"] for a in result] == ["1", "2", "3", "4"]
    assert all(isinstance(a["id"], str) for a in result)
    assert [a["sport_type"] for a in result] == [100, 101, 102, 103]
    assert 103 in {a["sport_type"] for a in result}, "Track Run (103) снова отброшен — инцидент 17.09.2026"
    assert SPORT_TYPES_RUN == {100, 101, 102, 103}
    # start_time — aware UTC datetime (start_time is an aware UTC datetime)
    assert result[0]["start_time"] == datetime.fromtimestamp(base + 10, tz=timezone.utc)


# --- B. Строгость фильтра since (strict since filter) --------------------------------------------

def test_list_activities_since_filter_is_strict(monkeypatch):
    """startTime == since отбрасывается (строгое «позже»), startTime == since + 1 с — проходит."""
    since = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)
    since_ts = int(since.timestamp())
    data_list = [
        _act(10, 100, since_ts),       # ровно на границе → drop (exactly at boundary)
        _act(11, 100, since_ts + 1),   # на секунду позже → keep (one second later)
        _act(12, 100, since_ts - 60),  # раньше → drop (earlier)
    ]
    client = _authed_client(monkeypatch, data_list)

    result = asyncio.run(client.list_activities(since=since))

    assert [a["id"] for a in result] == ["11"]
    assert result[0]["start_time"] == since + timedelta(seconds=1)


def test_list_activities_without_since_returns_all_running(monkeypatch):
    """since=None — окно не применяется, все беговые записи возвращаются (no since → no time filter)."""
    data_list = [_act(20, 100, 1_600_000_000), _act(21, 102, 1_500_000_000)]
    client = _authed_client(monkeypatch, data_list)

    result = asyncio.run(client.list_activities())

    assert sorted(a["id"] for a in result) == ["20", "21"]


# --- C. Диагностика фильтра в логе (filter diagnostics in log) -----------------------------------

def test_list_activities_logs_filter_diagnostics(monkeypatch, caplog):
    """В INFO-логе клиента Coros (логгер `app`) есть счётчики отброшенных: dropped_sport с кодом 200 и dropped_since=1."""
    # Прод-логгер не пропагирует в root — включаем на время теста, чтобы caplog его увидел
    # (app logger has propagate=False; enable it so caplog captures the record)
    monkeypatch.setattr(coros_mod.logger, "propagate", True)
    caplog.set_level(logging.INFO, logger="app")

    since = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)
    since_ts = int(since.timestamp())
    data_list = [
        _act(30, 100, since_ts + 100),  # keep
        _act(31, 200, since_ts + 200),  # dropped_sport → {200: 1}
        _act(32, 100, since_ts - 100),  # dropped_since → 1
    ]
    client = _authed_client(monkeypatch, data_list)

    result = asyncio.run(client.list_activities(since=since))
    assert [a["id"] for a in result] == ["30"]

    records = [r for r in caplog.records
               if r.name == "app" and "list_activities" in r.getMessage()]
    assert records, "нет диагностической строки Coros list_activities в логе"
    msg = records[-1].getMessage()
    assert "raw=3" in msg and "run=1" in msg
    assert "dropped_sport=" in msg and "200" in msg
    assert "dropped_since=1" in msg
    assert f"since={since.isoformat()}" in msg


# --- D. run_sync_for_user: `pending` только для activity (pending only for activity) --------------

def _patch_session_local(monkeypatch, db_session):
    """orchestrator.SessionLocal → фабрика, отдающая тестовую сессию с no-op close
    (orchestrator opens/closes its own session; hand it the test session and swallow close)."""
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(orchestrator, "SessionLocal", lambda: db_session)


def test_run_sync_for_user_health_does_not_pass_pending(db_session, monkeypatch):
    """Health-функция принимает только progress: `pending` ей не передаётся (раньше — TypeError
    и progress.step='error'). Успех двигает last_health_sync_at."""
    user = make_user(db_session, chat_id=98101, email="sf-health@example.com")
    cred = _make_cred(db_session, user.id)
    _patch_session_local(monkeypatch, db_session)
    monkeypatch.setattr(orchestrator, "telegram_notify", lambda **kw: None)
    calls = []

    async def fake_health(cred, brand, db, progress=None):   # без **kwargs — лишний kwarg = TypeError
        calls.append({"brand": brand, "progress": progress})
        return 1

    monkeypatch.setitem(orchestrator.SYNC_CONFIG["health"], "sync_fn", fake_health)
    progress: dict = {}

    orchestrator.run_sync_for_user(user.id, "coros", "health", progress=progress, pending={})

    assert progress.get("step") != "error", progress
    assert calls and calls[0]["brand"] == "coros" and calls[0]["progress"] is progress
    assert _reload_cred(cred.id).last_health_sync_at is not None


def test_run_sync_for_user_activity_passes_pending(db_session, monkeypatch):
    """Activity-функция получает тот же самый dict `pending`, что передал вызывающий код."""
    user = make_user(db_session, chat_id=98102, email="sf-activity@example.com")
    cred = _make_cred(db_session, user.id)
    _patch_session_local(monkeypatch, db_session)
    monkeypatch.setattr(orchestrator, "telegram_notify", lambda **kw: None)
    seen = {}

    async def fake_activity(cred, brand, db, progress=None, pending=None):
        seen["pending"] = pending
        seen["progress"] = progress
        return 2

    monkeypatch.setitem(orchestrator.SYNC_CONFIG["activity"], "sync_fn", fake_activity)
    progress: dict = {}
    pending: dict = {}

    orchestrator.run_sync_for_user(user.id, "coros", "activity", progress=progress, pending=pending)

    assert seen["pending"] is pending
    assert seen["progress"] is progress
    assert progress.get("step") != "error", progress
    assert _reload_cred(cred.id).last_activity_sync_at is not None


def test_run_sync_for_user_health_without_progress_and_pending(db_session, monkeypatch):
    """Вызов из бота/авто: progress=None, pending=None — health получает progress=None и не падает."""
    user = make_user(db_session, chat_id=98103, email="sf-health-none@example.com")
    cred = _make_cred(db_session, user.id)
    _patch_session_local(monkeypatch, db_session)
    monkeypatch.setattr(orchestrator, "telegram_notify", lambda **kw: None)
    calls = []

    async def fake_health(cred, brand, db, progress=None):
        calls.append(progress)
        return 0

    monkeypatch.setitem(orchestrator.SYNC_CONFIG["health"], "sync_fn", fake_health)

    orchestrator.run_sync_for_user(user.id, "coros", "health")

    assert calls == [None]
    assert _reload_cred(cred.id).last_health_sync_at is not None


# --- E. Окно since — дни, не часы (since window in days, not hours) ------------------------------

def test_activity_sync_since_window_is_days_not_hours(db_session, monkeypatch):
    """since = last_activity_sync_at − ACTIVITY_SYNC_LOOKBACK_DAYS дней (раньше — 2 часа):
    часы выгружают тренировку в облако с задержкой, а таймстемп двигается и при пустом результате."""
    seen = {}

    class FakeClient:
        async def list_activities(self, since=None):
            seen["since"] = since
            return []

        async def close(self):
            pass

    async def fake_make_client(cred):
        return FakeClient()

    monkeypatch.setattr(act_mod, "_make_client", fake_make_client)
    user = make_user(db_session, chat_id=98104, email="sf-window@example.com")
    cred = _make_cred(db_session, user.id)
    now = datetime.now(timezone.utc)
    cred.last_activity_sync_at = now
    db_session.commit()

    result = asyncio.run(act_mod.sync_activities_for_user(cred, "coros", db_session))

    assert result == 0
    since = seen["since"]
    assert since is not None
    if since.tzinfo is None:  # SQLite может отдать naive UTC (SQLite may return naive UTC)
        since = since.replace(tzinfo=timezone.utc)
    window = now - since
    expected = timedelta(days=ACTIVITY_SYNC_LOOKBACK_DAYS)
    assert abs((window - expected).total_seconds()) < 5, f"окно since = {window}, ожидалось ≈ {expected}"
    assert window > timedelta(hours=2), "окно since снова часы, а не дни — тренировки с задержкой потеряются"
    assert ACTIVITY_SYNC_LOOKBACK_DAYS >= 1


def test_activity_sync_first_run_has_no_since(db_session, monkeypatch):
    """Первый синк (last_activity_sync_at=None) — since=None: полный список без окна (first run: no window)."""
    seen = {}

    class FakeClient:
        async def list_activities(self, since=None):
            seen["since"] = since
            return []

        async def close(self):
            pass

    async def fake_make_client(cred):
        return FakeClient()

    monkeypatch.setattr(act_mod, "_make_client", fake_make_client)
    user = make_user(db_session, chat_id=98105, email="sf-first@example.com")
    cred = _make_cred(db_session, user.id)

    assert asyncio.run(act_mod.sync_activities_for_user(cred, "coros", db_session)) == 0
    assert "since" in seen and seen["since"] is None
