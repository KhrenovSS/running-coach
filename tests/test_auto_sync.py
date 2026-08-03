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
