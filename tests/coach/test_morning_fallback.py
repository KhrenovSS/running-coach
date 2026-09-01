# Тесты деградации утреннего вердикта при сбое моста (инцидент 01.09.2026).
# Ключевой инвариант: при недоступности LLM утро отдаёт ДЕТЕРМИНИРОВАННЫЙ вердикт
# со назначением (состояние + план дня), а не generic-карточку «базовый режим».
# retriable отражает ТИП сбоя: транзиентный (мост лёг) → есть смысл повторить.

from src.coach import orchestrator
from tests.coach.conftest import _unique_user
from tests.coach.fakes import FailingLLM, TransientFailingLLM


def test_morning_fallback_transient_keeps_prescription(athlete_with_history, db_session):
    """Транзиентный сбой моста в утреннем вердикте → состояние + назначение,
    без generic-фразы «базовый режим»; source=fallback, retriable=True."""
    uid = athlete_with_history.id
    reply = orchestrator.handle_chat(uid, "утренний вердикт", db=db_session,
                                     llm=TransientFailingLLM(), kind="morning")
    assert reply.source == "fallback"
    assert reply.retriable is True
    assert "базовом режиме" not in reply.text          # это НЕ generic-чат-fallback
    assert reply.text.startswith("*Состояние*")         # карточка состояния
    assert "\n\n*" in reply.text                         # + карточка назначения (второй заголовок)


def test_morning_fallback_permanent_not_retriable(athlete_with_history, db_session):
    """Постоянный сбой (нет ключа/мост отверг) → тот же полноценный вердикт,
    но retriable=False: отложенный повтор бессмыслен."""
    uid = athlete_with_history.id
    reply = orchestrator.handle_chat(uid, "утренний вердикт", db=db_session,
                                     llm=FailingLLM(), kind="morning")
    assert reply.source == "fallback"
    assert reply.retriable is False
    assert "базовом режиме" not in reply.text
    assert "\n\n*" in reply.text                         # назначение на месте


def test_chat_fallback_stays_generic(db_session):
    """Обычный чат (kind='chat') при сбое остаётся в базовом режиме (без назначения)."""
    uid = _unique_user(db_session).id
    reply = orchestrator.handle_chat(uid, "как дела?", db=db_session,
                                     llm=TransientFailingLLM(), kind="chat")
    assert reply.source == "fallback"
    assert "базовом режиме" in reply.text
