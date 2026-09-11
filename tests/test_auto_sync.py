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


# --- Восстановление после алерта: бот отписывается, что синк снова работает (06.09.2026) ---

def _collect_notify(monkeypatch):
    sent = []
    monkeypatch.setattr(orchestrator, "telegram_notify", lambda **kw: sent.append(kw))
    return sent


def _mine(sent, user_id):
    # Цикл синкает ВСЕ creds в БД — фильтруем по своему пользователю (filter by our user)
    return [kw["text"] for kw in sent if kw["user_id"] == user_id]


def test_auto_sync_recovery_notifies_after_alert(db_session, monkeypatch):
    """3 сбоя → алерт; следующий успех → ровно одно сообщение «восстановлена» с числом подтянутых."""
    user = make_user(db_session, chat_id=96006, email="recover-alert@example.com")
    cred = _make_cred(db_session, user.id)
    sent = _collect_notify(monkeypatch)
    _patch_no_network(monkeypatch, result=-1)
    for _ in range(3):
        orchestrator.auto_sync_activities()

    _patch_no_network(monkeypatch, result=2)
    orchestrator.auto_sync_activities()

    texts = _mine(sent, user.id)
    assert len(texts) == 2, texts
    assert "не работает" in texts[0]
    assert "восстановлена" in texts[1] and "тренировок" in texts[1]
    assert "Сбоев подряд было: 3" in texts[1]
    assert "Подтянуто тренировок: 2" in texts[1]
    assert "раньше успешных синхронизаций не было" in texts[1]  # last_activity_sync_at был None
    assert _reload_cred(cred.id).activity_sync_failures == 0


def test_auto_sync_recovery_silent_below_threshold(db_session, monkeypatch):
    """2 сбоя (алерта не было) → успех → никаких уведомлений: нечего «закрывать»."""
    user = make_user(db_session, chat_id=96007, email="recover-quiet@example.com")
    _make_cred(db_session, user.id)
    sent = _collect_notify(monkeypatch)
    _patch_no_network(monkeypatch, result=-1)
    orchestrator.auto_sync_health()
    orchestrator.auto_sync_health()
    _patch_no_network(monkeypatch, result=3)
    orchestrator.auto_sync_health()

    assert _mine(sent, user.id) == []


def test_auto_sync_recovery_text_empty_result_and_gap(db_session, monkeypatch):
    """Успех с пустым результатом после алерта: «новых … не было» + длительность паузы от last_*_sync_at.
    Backoff при 3 сбоях = интервал ×8: минимальный интервал 15 мин → 2 ч, пауза 3 ч 5 мин → синк созрел."""
    from datetime import datetime, timedelta, timezone
    user = make_user(db_session, chat_id=96008, email="recover-empty@example.com")
    cred = _make_cred(db_session, user.id)
    cred.activity_sync_interval = 15
    cred.last_activity_sync_at = datetime.now(timezone.utc) - timedelta(hours=3, minutes=5)
    cred.activity_sync_failures = 3  # алерт уже уходил (порог достигнут)
    db_session.commit()
    sent = _collect_notify(monkeypatch)
    _patch_no_network(monkeypatch, result=0)

    orchestrator.auto_sync_activities()

    texts = _mine(sent, user.id)
    assert len(texts) == 1, texts
    assert "тренировок" in texts[0] and "восстановлена" in texts[0]
    assert "Новых тренировок за время сбоя не было" in texts[0]
    assert "пауза 3 ч 5 мин" in texts[0]


def test_fmt_gap():
    """Форматирование паузы: минуты / часы / дни."""
    assert orchestrator._fmt_gap(17 * 60) == "17 мин"
    assert orchestrator._fmt_gap(3600) == "1 ч"
    assert orchestrator._fmt_gap(3600 + 42 * 60) == "1 ч 42 мин"
    assert orchestrator._fmt_gap(26 * 3600) == "1 дн 2 ч"


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


# --- #312/#313 (07.09.2026): причина сбоя в алерте, ручной синк закрывает алерт ---

def test_classify_watch_error():
    import httpx
    from src.exceptions import WatchAPIError, WatchAuthError
    from src.services.sync import utils as u

    req = httpx.Request("POST", "https://x")
    assert u.classify_watch_error(httpx.HTTPStatusError("504", request=req,
                                                        response=httpx.Response(504, request=req))) == u.SYNC_ERROR_SERVER
    assert u.classify_watch_error(httpx.HTTPStatusError("401", request=req,
                                                        response=httpx.Response(401, request=req))) == u.SYNC_ERROR_CREDENTIALS
    assert u.classify_watch_error(httpx.ConnectTimeout("t", request=req)) == u.SYNC_ERROR_SERVER
    assert u.classify_watch_error(WatchAuthError("Auth failed: bad password", brand="coros")) == u.SYNC_ERROR_CREDENTIALS
    assert u.classify_watch_error(WatchAuthError("Network error: boom", brand="coros")) == u.SYNC_ERROR_SERVER
    assert u.classify_watch_error(WatchAPIError("down", brand="coros", status=503)) == u.SYNC_ERROR_SERVER
    assert u.classify_watch_error(RuntimeError("x")) == u.SYNC_ERROR_UNKNOWN


def test_failure_alert_names_server_cause(db_session, monkeypatch):
    """Coros лежит (5xx) → алерт говорит «сервер часов недоступен», а не «проверь учётные данные»."""
    from src.config.constants import SYNC_FAILURE_NOTIFY_THRESHOLD
    from src.services.sync import utils as u

    user = make_user(db_session, chat_id=96010, email="srv@example.com")
    cred = _make_cred(db_session, user.id)
    cred.health_sync_failures = SYNC_FAILURE_NOTIFY_THRESHOLD - 1
    db_session.commit()
    sent = []
    monkeypatch.setattr(orchestrator, "telegram_notify", lambda **kw: sent.append(kw))
    u.note_sync_error(cred, u.SYNC_ERROR_SERVER)
    orchestrator._record_sync_failure(db_session, cred, orchestrator.SYNC_CONFIG["health"])
    assert len(sent) == 1 and "Сервер часов недоступен" in sent[0]["text"]
    assert "проверь логин" not in sent[0]["text"]
    assert u.pop_sync_error(cred) is None          # причина потреблена


def test_manual_sync_success_closes_alert_and_moves_timestamp(db_session, monkeypatch):
    """#312: ручной синк (бот/web) после алерта → счётчик 0, таймстемп вперёд, «✅ восстановлена»."""
    from src.config.constants import SYNC_FAILURE_NOTIFY_THRESHOLD

    user = make_user(db_session, chat_id=96011, email="man@example.com")
    cred = _make_cred(db_session, user.id)
    cred.health_sync_failures = SYNC_FAILURE_NOTIFY_THRESHOLD
    db_session.commit()
    sent = []
    monkeypatch.setattr(orchestrator, "telegram_notify", lambda **kw: sent.append(kw))
    assert orchestrator.record_manual_sync_result(db_session, cred, "health", 2) is None
    reloaded = _reload_cred(cred.id)
    assert reloaded.health_sync_failures == 0 and reloaded.last_health_sync_at is not None
    assert len(sent) == 1 and "восстановлена" in sent[0]["text"]
    # сбой ручного синка: счётчик не трогаем, токен сброшен, подсказка по причине
    from src.services.sync import utils as u
    u.note_sync_error(cred, u.SYNC_ERROR_CREDENTIALS)
    hint = orchestrator.record_manual_sync_result(db_session, cred, "health", -1)
    assert "учётные данные" in hint and _reload_cred(cred.id).health_sync_failures == 0
    assert _reload_cred(cred.id).access_token is None


def test_bot_sync_runner_uses_shared_bookkeeping(db_session, monkeypatch):
    from src.telegram import sync_runner

    user = make_user(db_session, chat_id=96012, email="bot@example.com")
    cred = _make_cred(db_session, user.id)
    cred.activity_sync_failures = 5
    db_session.commit()

    def fake_run(coro):
        coro.close()
        return 1
    monkeypatch.setattr(sync_runner, "run_async_in_thread", fake_run)
    monkeypatch.setattr(orchestrator, "telegram_notify", lambda **kw: None)
    ok, text = sync_runner.run_sync_in_thread(96012)
    assert ok and "Синхронизация завершена" in text
    reloaded = _reload_cred(cred.id)
    assert reloaded.activity_sync_failures == 0 and reloaded.last_activity_sync_at is not None


def test_bot_sync_runner_audits_per_brand_counts(db_session, monkeypatch):
    """#114: `sync.<brand>.completed` каждого бренда несёт СВОЁ число новых тренировок, не накопленное."""
    import json
    from src.domain.models.audit import AuditEvent
    from src.telegram import sync_runner

    user = make_user(db_session, chat_id=96013, email="bot2@example.com")
    _make_cred(db_session, user.id, brand="coros")
    _make_cred(db_session, user.id, brand="garmin")
    results = iter([0, 2, 0, 3])          # health/activity для coros, затем для garmin

    def fake_run(coro):
        coro.close()
        return next(results)
    monkeypatch.setattr(sync_runner, "run_async_in_thread", fake_run)
    monkeypatch.setattr(orchestrator, "telegram_notify", lambda **kw: None)
    ok, _ = sync_runner.run_sync_in_thread(96013)
    assert ok
    db_session.expire_all()
    found = {}
    for ev in db_session.query(AuditEvent).filter(AuditEvent.user_id == user.id).all():
        if ev.event_type.endswith(".completed"):
            meta = json.loads(ev.metadata_json)
            found[meta["brand"]] = (meta["found"], meta.get("health"))
    assert found == {"coros": (2, 0), "garmin": (3, 0)}

