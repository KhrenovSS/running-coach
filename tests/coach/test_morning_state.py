# Заявка на утренний вердикт дня (19.09.2026): решения по скриншоту сна и дедуп
# отправки — чистая plan_action + claim/mark_sent/release в params_json.
from datetime import date, datetime, timedelta

from src.coach import illness, morning_state
from src.coach.llm.config import MORNING_CLAIM_STALE_MIN
from tests.coach.conftest import _unique_user

DAY = date(2026, 9, 19)
MORNING = datetime(2026, 9, 19, 8, 10)


def test_no_record_means_send():
    """Вердикта за сегодня не было → скриншот запускает его немедленно."""
    assert morning_state.plan_action({}, day=DAY, now=MORNING) == morning_state.SEND


def test_sent_without_sleep_means_resend():
    """Вердикт ушёл без сна → один пересчёт с учётом сна."""
    st = {"date": DAY.isoformat(), "with_sleep": False, "sent_at": "2026-09-19T09:30:00"}
    assert morning_state.plan_action(st, day=DAY, now=datetime(2026, 9, 19, 10, 0)) \
        == morning_state.RESEND


def test_sent_with_sleep_means_skip():
    """Сон уже учтён (второй скриншот того же утра) → тишина."""
    st = {"date": DAY.isoformat(), "with_sleep": True, "sent_at": "2026-09-19T08:12:00"}
    assert morning_state.plan_action(st, day=DAY, now=datetime(2026, 9, 19, 9, 0)) \
        == morning_state.SKIP


def test_after_stop_hour_means_skip():
    """После стоп-часа «утренний» вердикт не шлём — сон просто лежит в БД."""
    st = {"date": DAY.isoformat(), "with_sleep": False, "sent_at": "2026-09-19T09:30:00"}
    assert morning_state.plan_action(st, day=DAY, now=datetime(2026, 9, 19, 22, 0)) \
        == morning_state.SKIP


def test_fresh_claim_means_wait():
    """Ход 09:30 ещё в полёте → перепроверить позже, а не слать дубль."""
    st = {"date": DAY.isoformat(), "with_sleep": False, "claimed_at": "2026-09-19T09:30:00",
          "sent_at": None}
    assert morning_state.plan_action(st, day=DAY, now=datetime(2026, 9, 19, 9, 31)) \
        == morning_state.WAIT


def test_stale_claim_is_taken_over():
    """Заявка без отправки протухла (креш контейнера) → день снова свободен."""
    st = {"date": DAY.isoformat(), "with_sleep": False, "claimed_at": "2026-09-19T09:30:00",
          "sent_at": None}
    late = datetime(2026, 9, 19, 9, 30) + timedelta(minutes=MORNING_CLAIM_STALE_MIN + 1)
    assert morning_state.plan_action(st, day=DAY, now=late) == morning_state.SEND


def test_claim_blocks_second_sender(db_session):
    """Первый занял день — второй (резерв 09:30) молчит."""
    user = _unique_user(db_session)
    assert morning_state.claim(user.id, db=db_session, day=DAY, with_sleep=True,
                               now=MORNING) is True
    assert morning_state.claim(user.id, db=db_session, day=DAY, with_sleep=False,
                               now=MORNING) is False


def test_release_frees_the_day(db_session):
    """Ход упал до отправки → заявка снята, резерв 09:30 отработает."""
    user = _unique_user(db_session)
    morning_state.claim(user.id, db=db_session, day=DAY, with_sleep=True, now=MORNING)
    morning_state.release(user.id, db=db_session, day=DAY)
    assert morning_state.state(user.id, db=db_session) == {}
    assert morning_state.claim(user.id, db=db_session, day=DAY, with_sleep=True,
                               now=MORNING) is True


def test_resend_claim_allowed_only_once(db_session):
    """Пересчёт со сном занимает день поверх отправленного без сна — но ровно один раз."""
    user = _unique_user(db_session)
    morning_state.claim(user.id, db=db_session, day=DAY, with_sleep=False, now=MORNING)
    morning_state.mark_sent(user.id, db=db_session, day=DAY, with_sleep=False, now=MORNING)
    later = datetime(2026, 9, 19, 10, 0)
    assert morning_state.claim(user.id, db=db_session, day=DAY, with_sleep=True,
                               now=later) is True
    morning_state.mark_sent(user.id, db=db_session, day=DAY, with_sleep=True, now=later)
    assert morning_state.claim(user.id, db=db_session, day=DAY, with_sleep=True,
                               now=later) is False


def test_failed_resend_restores_sent_state(db_session):
    """Пересчёт не доехал → состояние «вердикт без сна отправлен», а не «не было вовсе»."""
    user = _unique_user(db_session)
    morning_state.claim(user.id, db=db_session, day=DAY, with_sleep=False, now=MORNING)
    morning_state.mark_sent(user.id, db=db_session, day=DAY, with_sleep=False, now=MORNING)
    morning_state.claim(user.id, db=db_session, day=DAY, with_sleep=True,
                        now=datetime(2026, 9, 19, 10, 0))
    morning_state.release(user.id, db=db_session, day=DAY)
    st = morning_state.state(user.id, db=db_session)
    assert st["sent_at"] and st["with_sleep"] is False


def test_other_params_survive(db_session):
    """Соседние ключи params_json (болезнь и пр.) заявка не затирает."""
    user = _unique_user(db_session)
    illness.record_illness(
        type("R", (), {"status": "sick", "kind": "cold", "days_ago": 0})(),
        user.id, db=db_session, now=datetime(2026, 9, 19, 8, 0))
    morning_state.claim(user.id, db=db_session, day=DAY, with_sleep=True, now=MORNING)
    assert illness.illness_state(user.id, db=db_session).get("status") == "sick"
