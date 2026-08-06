# Тесты адаптивного максимального пульса (Adaptive max HR tests)
#
# Повышение: 1–2 превышения за месяц — предупреждение, ≥3 — принудительное обновление.
# Снижение: предложение по 90 дням интенсивных тренировок (только кнопка).
# Telegram мокается — сеть в тестах не нужна.

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.services import hr_max
from src.analysis.utils import smoothed_hr_peak
from src.domain.models.audit import AuditEvent
from src.domain.models import User
from tests.helpers import make_user, build_training_session

_uid = iter(range(94000, 94999))  # уникальные chat_id/email между тестами — диапазон 94xxx свободен, см. docs/TESTING.md (unique ids across tests)


def _user(db, max_hr=177):
    n = next(_uid)
    return make_user(db, chat_id=n, email=f"hrmax{n}@example.com", max_hr=max_hr)


def _session(db, user_id, peak, days_ago=1, training_type='tempo', smoothed=True):
    """Тренировка с заданным пиком (Training with a given peak)."""
    return build_training_session(
        db, user_id, training_type=training_type,
        max_heart_rate=peak if not smoothed else peak + 3,  # сырой max чуть выше — важно, что берётся smoothed
        hr_peak_smoothed=peak if smoothed else None,
        begin_ts=datetime.now(timezone.utc) - timedelta(days=days_ago),
    )


@pytest.fixture
def sent(monkeypatch):
    """Мок telegram_notify: собирает отправленные уведомления (Collects notify calls)."""
    calls = []
    monkeypatch.setattr(hr_max, "telegram_notify",
                        lambda user_id, text, reply_markup=None: calls.append(
                            {"user_id": user_id, "text": text, "reply_markup": reply_markup}))
    return calls


# --- Сглаженный пик (Smoothed peak) ---

def test_smoothed_peak_kills_single_spike():
    """Одиночный выброс 230 не влияет на пик (Single 230 spike is filtered out)."""
    hr = [150] * 50 + [230] + [150] * 50
    assert smoothed_hr_peak(hr) == 150


def test_smoothed_peak_keeps_sustained_high_hr():
    """Устойчивый рост до 182 сохраняется (Sustained rise to 182 survives)."""
    hr = list(range(140, 183)) + [182] * 30
    assert smoothed_hr_peak(hr) == 182


def test_smoothed_peak_empty_and_short():
    assert smoothed_hr_peak([]) is None
    assert smoothed_hr_peak([160, 162]) == 161


# --- Повышение (Raise) ---

def test_first_exceedance_warns_only(db_session, sent):
    """Первое превышение: профиль не тронут, одно предупреждение с кнопками."""
    user = _user(db_session)
    _session(db_session, user.id, peak=181)
    result = hr_max.evaluate_max_hr_raise(db_session, user.id, 181, source="test")
    assert result is None
    db_session.refresh(user)
    assert user.max_hr == 177
    assert len(sent) == 1
    assert "181" in sent[0]["text"] and "177" in sent[0]["text"]
    buttons = [b for row in sent[0]["reply_markup"]["inline_keyboard"] for b in row]
    assert any(b["callback_data"] == "maxhr:set:181" for b in buttons)
    assert any(b["callback_data"] == "maxhr:ignore" for b in buttons)


def test_three_exceedances_force_update(db_session, sent):
    """3 превышения за месяц → max_hr = 3-й по величине пик, одно уведомление, аудит."""
    user = _user(db_session)
    for days_ago, peak in ((10, 183), (5, 182), (1, 181)):
        _session(db_session, user.id, peak=peak, days_ago=days_ago)
    result = hr_max.evaluate_max_hr_raise(db_session, user.id, 181, source="test")
    assert result == (177, 181)
    db_session.refresh(user)
    assert user.max_hr == 181
    assert len(sent) == 1
    assert "177 → 181" in sent[0]["text"]
    audit = db_session.query(AuditEvent).filter(
        AuditEvent.user_id == user.id, AuditEvent.event_type == "settings.changed").first()
    assert audit is not None
    meta = json.loads(audit.metadata_json)
    assert meta["source"] == "auto_max_hr"
    assert meta["changes"]["max_hr"] == {"old": 177, "new": 181}


def test_old_exceedances_outside_window_ignored(db_session, sent):
    """Превышения старше 30 дней не считаются: 2 свежих + 1 старое → только предупреждение."""
    user = _user(db_session)
    _session(db_session, user.id, peak=182, days_ago=45)  # вне окна (outside window)
    _session(db_session, user.id, peak=181, days_ago=5)
    _session(db_session, user.id, peak=181, days_ago=1)
    result = hr_max.evaluate_max_hr_raise(db_session, user.id, 181, source="test")
    assert result is None
    db_session.refresh(user)
    assert user.max_hr == 177
    assert len(sent) == 1
    assert sent[0]["reply_markup"] is not None  # предупреждение с кнопками (warning w/ buttons)


def test_same_day_bulk_upload_warns_only(db_session, sent):
    """3 превышения ОДНИМ днём (bulk-загрузка) → только предупреждение, не форс
    (db-safety review 06.08.2026: превышения считаются по разным дням)."""
    user = _user(db_session)
    for _ in range(3):
        _session(db_session, user.id, peak=181, days_ago=1)
    result = hr_max.evaluate_max_hr_raise(db_session, user.id, 181, source="test")
    assert result is None
    db_session.refresh(user)
    assert user.max_hr == 177
    assert len(sent) == 1
    assert sent[0]["reply_markup"] is not None


def test_service_never_raises(db_session, monkeypatch):
    """Исключение внутри сервиса гасится (rollback), вызывающий синк не получает сбой."""
    user = _user(db_session)
    _session(db_session, user.id, peak=181)
    monkeypatch.setattr(hr_max, "telegram_notify",
                        lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    assert hr_max.evaluate_max_hr_raise(db_session, user.id, 181, source="test") is None


def test_artifact_above_cap_ignored(db_session, sent):
    """Пик выше 220 — артефакт: ни апдейта, ни уведомления."""
    user = _user(db_session)
    assert hr_max.evaluate_max_hr_raise(db_session, user.id, 230, source="test") is None
    db_session.refresh(user)
    assert user.max_hr == 177
    assert sent == []


def test_peak_below_profile_early_exit(db_session, sent):
    """Пик ≤ профильного и falsy-значения — ранний выход без уведомлений."""
    user = _user(db_session)
    assert hr_max.evaluate_max_hr_raise(db_session, user.id, 170, source="test") is None
    assert hr_max.evaluate_max_hr_raise(db_session, user.id, 177, source="test") is None
    assert hr_max.evaluate_max_hr_raise(db_session, user.id, None, source="test") is None
    assert hr_max.evaluate_max_hr_raise(db_session, user.id, 0, source="test") is None
    assert sent == []


def test_legacy_rows_counted_via_raw_max(db_session, sent):
    """Legacy-строки (hr_peak_smoothed=NULL) участвуют через max_heart_rate (coalesce)."""
    user = _user(db_session)
    for days_ago in (7, 4):
        _session(db_session, user.id, peak=181, days_ago=days_ago, smoothed=False)
    _session(db_session, user.id, peak=181, days_ago=1)
    result = hr_max.evaluate_max_hr_raise(db_session, user.id, 181, source="test")
    assert result == (177, 181)
    db_session.refresh(user)
    assert user.max_hr == 181


def test_default_profile_when_max_hr_empty(db_session, sent):
    """user.max_hr = None → профиль берётся из default_max_hr (177)."""
    user = _user(db_session)
    user.max_hr = None
    db_session.commit()
    for days_ago in (5, 3, 1):
        _session(db_session, user.id, peak=181, days_ago=days_ago)
    assert hr_max.evaluate_max_hr_raise(db_session, user.id, 181, source="test") == (177, 181)


# --- Снижение (Lowering) ---

def _intense(db, user_id, peak, days_ago, ttype='interval'):
    return _session(db, user_id, peak=peak, days_ago=days_ago, training_type=ttype)


def test_lowering_suggested(db_session, sent):
    """5 интенсивных за 90 дней, пики ≤ 172 при профиле 177+5 маржи → предложение."""
    user = _user(db_session, max_hr=180)
    for i in range(5):
        _intense(db_session, user.id, peak=170 + i % 3, days_ago=10 + i * 7)
    suggested = hr_max.evaluate_max_hr_lowering(db_session, user.id)
    assert suggested == 172
    db_session.refresh(user)
    assert user.max_hr == 180, "снижение никогда не применяется автоматически"
    assert len(sent) == 1
    assert "172" in sent[0]["text"]
    buttons = [b for row in sent[0]["reply_markup"]["inline_keyboard"] for b in row]
    assert any(b["callback_data"] == "maxhr:set:172" for b in buttons)
    audit = db_session.query(AuditEvent).filter(
        AuditEvent.user_id == user.id,
        AuditEvent.event_type == hr_max.MAX_HR_SUGGEST_EVENT).first()
    assert audit is not None


def test_lowering_needs_enough_intense_workouts(db_session, sent):
    """4 интенсивных < порога 5 → без предложения."""
    user = _user(db_session, max_hr=180)
    for i in range(4):
        _intense(db_session, user.id, peak=170, days_ago=10 + i * 7)
    assert hr_max.evaluate_max_hr_lowering(db_session, user.id) is None
    assert sent == []


def test_lowering_not_suggested_when_peak_close(db_session, sent):
    """Пик 177 при профиле 180 — в пределах маржи 5 → без предложения."""
    user = _user(db_session, max_hr=180)
    for i in range(5):
        _intense(db_session, user.id, peak=177, days_ago=10 + i * 7)
    assert hr_max.evaluate_max_hr_lowering(db_session, user.id) is None
    assert sent == []


def test_lowering_cooldown(db_session, sent):
    """Свежее предложение (аудит-событие) → кулдаун, повторного нет."""
    user = _user(db_session, max_hr=180)
    for i in range(5):
        _intense(db_session, user.id, peak=170, days_ago=10 + i * 7)
    assert hr_max.evaluate_max_hr_lowering(db_session, user.id) == 170
    assert hr_max.evaluate_max_hr_lowering(db_session, user.id) is None
    assert len(sent) == 1


# --- Кнопки бота (Bot buttons) ---

def _fake_query(data, chat_id):
    """Мини-стабы Update/CallbackQuery для вызова хендлера (Minimal Update/query stubs)."""
    messages = []

    async def answer():
        pass

    async def edit_message_text(text, **kwargs):
        messages.append(text)

    query = SimpleNamespace(data=data, answer=answer, edit_message_text=edit_message_text)
    update = SimpleNamespace(callback_query=query,
                             effective_chat=SimpleNamespace(id=chat_id))
    return update, messages


def test_button_set_updates_max_hr(db_session):
    """Кнопка maxhr:set:182 обновляет профиль и пишет аудит."""
    from src.telegram.handlers.hr_max import hr_max_callback
    user = _user(db_session)
    update, messages = _fake_query("maxhr:set:182", user.telegram_chat_id)
    asyncio.run(hr_max_callback(update, None))
    db_session.expire_all()
    reloaded = db_session.query(User).filter(User.id == user.id).first()
    assert reloaded.max_hr == 182
    assert any("182" in m for m in messages)
    audit = db_session.query(AuditEvent).filter(
        AuditEvent.user_id == user.id, AuditEvent.event_type == "settings.changed").first()
    assert audit is not None
    assert json.loads(audit.metadata_json)["source"] == "telegram_button"


def test_button_rejects_implausible_value(db_session):
    """Кнопка с value вне 100–220 отклоняется."""
    from src.telegram.handlers.hr_max import hr_max_callback
    user = _user(db_session)
    update, messages = _fake_query("maxhr:set:250", user.telegram_chat_id)
    asyncio.run(hr_max_callback(update, None))
    db_session.expire_all()
    reloaded = db_session.query(User).filter(User.id == user.id).first()
    assert reloaded.max_hr == 177
    assert any("Недопустимое" in m for m in messages)


def test_button_ignore_keeps_value(db_session):
    """Кнопка maxhr:ignore ничего не меняет."""
    from src.telegram.handlers.hr_max import hr_max_callback
    user = _user(db_session)
    update, messages = _fake_query("maxhr:ignore", user.telegram_chat_id)
    asyncio.run(hr_max_callback(update, None))
    db_session.expire_all()
    reloaded = db_session.query(User).filter(User.id == user.id).first()
    assert reloaded.max_hr == 177
    assert any("без изменений" in m for m in messages)
