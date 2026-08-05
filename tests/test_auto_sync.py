# Тесты фоновой автосинхронизации (Background auto-sync tests)
#
# R2-регресс: _auto_sync ДОЛЖЕН коммитить last_*_sync_at. Раньше сессия закрывалась
# до цикла, setattr шёл по detached-объектам без commit → таймстемпы не двигались →
# каждый тик ре-синкал все креды (риск бана watch-API).

from src.models import SessionLocal, WatchCredential
from src.services.sync import orchestrator
from tests.helpers import make_user


def _make_cred(db, user_id: int, brand: str = "coros"):
    cred = WatchCredential(
        user_id=user_id,
        brand=brand,
        encrypted_password="enc",
        is_active=True,
        last_activity_sync_at=None,  # никогда не синхронизировалось → sync due
        last_health_sync_at=None,
    )
    db.add(cred)
    db.commit()
    db.refresh(cred)
    return cred


def _patch_no_network(monkeypatch, result: int):
    """Подменить run_async_in_thread синхронной заглушкой (без сети/потоков)."""
    def fake_run(coro):
        coro.close()  # закрыть неиспользованную корутину (avoid 'never awaited')
        return result
    monkeypatch.setattr(orchestrator, "run_async_in_thread", fake_run)


def test_auto_sync_commits_last_activity_timestamp(db_session, monkeypatch):
    """После успешного авто-синка last_activity_sync_at сохраняется в БД (был None → set)."""
    user = make_user(db_session)
    cred = _make_cred(db_session, user.id)
    _patch_no_network(monkeypatch, result=2)  # synced=2

    orchestrator.auto_sync_activities()

    fresh = SessionLocal()
    try:
        reloaded = fresh.query(WatchCredential).filter(WatchCredential.id == cred.id).first()
        assert reloaded.last_activity_sync_at is not None, \
            "last_activity_sync_at не закоммичен — вернулся баг ресинк-шторма"
    finally:
        fresh.close()


def test_auto_sync_commits_timestamp_on_empty_result(db_session, monkeypatch):
    """Даже при пустом результате (0) таймстемп продвигается — иначе повторный ре-синк каждый тик."""
    user = make_user(db_session, chat_id=222, email="empty@example.com")
    cred = _make_cred(db_session, user.id)
    _patch_no_network(monkeypatch, result=0)  # нет новых данных

    orchestrator.auto_sync_health()

    fresh = SessionLocal()
    try:
        reloaded = fresh.query(WatchCredential).filter(WatchCredential.id == cred.id).first()
        assert reloaded.last_health_sync_at is not None, \
            "last_health_sync_at не закоммичен при пустом результате"
    finally:
        fresh.close()


# --- Этап 2 ремедиации (BACKLOG #227): сбой НЕ двигает таймстемп, счётчики, уведомление ---

def _reload_cred(cred_id: int) -> WatchCredential:
    fresh = SessionLocal()
    try:
        return fresh.query(WatchCredential).filter(WatchCredential.id == cred_id).first()
    finally:
        fresh.close()


def test_auto_sync_failure_does_not_advance_timestamp(db_session, monkeypatch):
    """Сбой (-1): last_*_sync_at стоит на месте, счётчик растёт, кэш токена сброшен.
    Раньше исключение в sync-функции возвращало 0 → таймстемп уезжал → данные терялись навсегда."""
    from datetime import datetime, timedelta, timezone
    user = make_user(db_session, chat_id=96001, email="fail1@example.com")
    cred = _make_cred(db_session, user.id)
    cred.access_token = "cached-token"
    cred.api_user_id = "api-uid"
    cred.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=12)
    db_session.commit()
    _patch_no_network(monkeypatch, result=-1)

    orchestrator.auto_sync_activities()

    reloaded = _reload_cred(cred.id)
    assert reloaded.last_activity_sync_at is None, "таймстемп сдвинулся при сбое — потеря данных вернулась"
    assert reloaded.activity_sync_failures == 1
    assert reloaded.access_token is None, "кэш токена должен сбрасываться при сбое (reuse-until-failure)"


def test_auto_sync_notifies_after_threshold_failures(db_session, monkeypatch):
    """На 3-м подряд сбое пользователь получает telegram-уведомление (ровно одно)."""
    user = make_user(db_session, chat_id=96002, email="fail3@example.com")
    cred = _make_cred(db_session, user.id)
    _patch_no_network(monkeypatch, result=-1)
    sent = []
    monkeypatch.setattr(orchestrator, "telegram_notify", lambda **kw: sent.append(kw))

    for _ in range(4):
        orchestrator.auto_sync_health()

    reloaded = _reload_cred(cred.id)
    assert reloaded.health_sync_failures == 4
    # Цикл синкает ВСЕ creds в БД (в т.ч. из соседних тестов) — фильтруем по своему пользователю
    # (The loop syncs ALL creds incl. neighbors' — filter by our user)
    mine = [kw for kw in sent if kw["user_id"] == user.id]
    assert len(mine) == 1, "уведомление должно уйти ровно один раз — на пороге"
    assert "здоровья" in mine[0]["text"]


def test_auto_sync_success_resets_failure_counter(db_session, monkeypatch):
    """Успех после сбоев: счётчик обнуляется, таймстемп двигается."""
    user = make_user(db_session, chat_id=96003, email="recover@example.com")
    cred = _make_cred(db_session, user.id)
    _patch_no_network(monkeypatch, result=-1)
    orchestrator.auto_sync_activities()
    orchestrator.auto_sync_activities()
    assert _reload_cred(cred.id).activity_sync_failures == 2

    _patch_no_network(monkeypatch, result=5)
    orchestrator.auto_sync_activities()

    reloaded = _reload_cred(cred.id)
    assert reloaded.activity_sync_failures == 0
    assert reloaded.last_activity_sync_at is not None


def test_effective_interval_backoff():
    """Backoff: интервал удваивается на каждый сбой, cap = MAX_SYNC_INTERVAL_MIN."""
    from src.config.constants import MAX_SYNC_INTERVAL_MIN
    from src.services.sync.utils import effective_interval_seconds
    base = 3600
    assert effective_interval_seconds(base, 0) == base
    assert effective_interval_seconds(base, 1) == base * 2
    assert effective_interval_seconds(base, 3) == base * 8
    assert effective_interval_seconds(base, 100) == MAX_SYNC_INTERVAL_MIN * 60


def test_health_sync_returns_minus_one_on_error(db_session, monkeypatch):
    """Исключение внутри health-синка → -1 (раньше 0 = «успех» и потеря данных)."""
    import asyncio
    from src.services.sync import health as health_mod

    class FakeClient:
        async def get_daily_metrics(self, start, end):
            raise RuntimeError("boom")
        async def close(self):
            pass

    async def fake_make_client(cred):
        return FakeClient()

    monkeypatch.setattr(health_mod, "_make_client", fake_make_client)
    user = make_user(db_session, chat_id=96004, email="herr@example.com")
    cred = _make_cred(db_session, user.id)

    assert asyncio.run(health_mod.sync_health_for_user(cred, "coros", db_session)) == -1


def test_activity_sync_returns_minus_one_on_error(db_session, monkeypatch):
    """Исключение внутри activity-синка → -1 (раньше 0 = «успех» и потеря тренировок)."""
    import asyncio
    from src.services.sync import activities as act_mod

    class FakeClient:
        async def list_activities(self, since=None):
            raise RuntimeError("boom")
        async def close(self):
            pass

    async def fake_make_client(cred):
        return FakeClient()

    monkeypatch.setattr(act_mod, "_make_client", fake_make_client)
    user = make_user(db_session, chat_id=96005, email="aerr@example.com")
    cred = _make_cred(db_session, user.id)

    assert asyncio.run(act_mod.sync_activities_for_user(cred, "coros", db_session)) == -1
