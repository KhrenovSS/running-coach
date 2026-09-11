# Тесты хендлеров аккаунта Telegram (#236): /delete_me удаляет данные И отвязывает chat_id.
# Telegram мокается SimpleNamespace-объектами, сеть не нужна (паттерн tests/test_hr_max.py).
import asyncio
from types import SimpleNamespace

from src.models import DailyMetrics, TrainingSession, User
from src.telegram.state import set_pending_deletion
from tests.helpers import build_daily_metrics, build_training_session, make_user


def _fake_update(chat_id: int):
    messages: list[str] = []

    async def reply_text(text, **kwargs):
        messages.append(text)

    update = SimpleNamespace(effective_chat=SimpleNamespace(id=chat_id),
                             message=SimpleNamespace(reply_text=reply_text))
    return update, messages


def test_delete_me_confirm_unlinks_chat_id(db_session):
    """#236: раньше `telegram_chat_id = None` писался в detached-объект из get_user() и терялся —
    данные удалялись, а аккаунт оставался привязан к чату. Теперь отвязка персистится."""
    from src.telegram.handlers.account import cmd_delete_me_confirm

    user = make_user(db_session, chat_id=93901, email="del-93901@example.com")
    build_training_session(db_session, user.id)
    build_daily_metrics(db_session, user.id)
    set_pending_deletion(user.telegram_chat_id)
    update, messages = _fake_update(user.telegram_chat_id)

    asyncio.run(cmd_delete_me_confirm(update, None))

    db_session.expire_all()
    reloaded = db_session.query(User).filter(User.id == user.id).first()
    assert reloaded is not None                                   # аккаунт остаётся (email/пароль)
    assert reloaded.telegram_chat_id is None                      # но от чата отвязан
    assert db_session.query(TrainingSession).filter_by(user_id=user.id).count() == 0
    assert db_session.query(DailyMetrics).filter_by(user_id=user.id).count() == 0
    assert any("удалены" in m for m in messages)


def test_delete_me_confirm_expired_does_nothing(db_session):
    """Без свежего /delete_me подтверждение отклоняется, данные и привязка целы."""
    from src.telegram.handlers.account import cmd_delete_me_confirm

    user = make_user(db_session, chat_id=93902, email="del-93902@example.com")
    build_training_session(db_session, user.id)
    update, messages = _fake_update(user.telegram_chat_id)

    asyncio.run(cmd_delete_me_confirm(update, None))

    db_session.expire_all()
    reloaded = db_session.query(User).filter(User.id == user.id).first()
    assert reloaded.telegram_chat_id == 93902
    assert db_session.query(TrainingSession).filter_by(user_id=user.id).count() == 1
    assert any("истекло" in m for m in messages)
