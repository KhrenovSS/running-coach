# Тесты D1: workout_insights — очередь отложенного разбора + персист итога
# (D1 tests: deferred-review queue + persisted outcome) — DEV_PLAN §9 D-серия

from datetime import datetime, timedelta, timezone

from src.models import TrainingSession, WorkoutInsight
from src.services.repositories_insights import InsightRepository, REVIEW_MAX_ATTEMPTS


def _session_id(user_id: int, db) -> int:
    s = db.query(TrainingSession).filter_by(user_id=user_id).order_by(
        TrainingSession.begin_ts.desc()).first()
    return s.id


def test_upsert_idempotent_and_no_status_demotion(athlete_with_history, db_session):
    """Повторный upsert не плодит строк и не откатывает done обратно в pending."""
    sid = _session_id(athlete_with_history.id, db_session)
    row = InsightRepository.upsert(athlete_with_history.id, sid, db=db_session,
                                   computed={"v": 1}, schema_version=1)
    assert row.status == "pending"
    InsightRepository.finish(sid, db=db_session, source="fallback")
    again = InsightRepository.upsert(athlete_with_history.id, sid, db=db_session,
                                     computed={"v": 2}, schema_version=1)
    assert again.id == row.id
    assert again.status == "done"          # статус не понижен повторным синком
    assert again.computed_json == {"v": 2}  # computed обновлён
    count = db_session.query(WorkoutInsight).filter_by(session_id=sid).count()
    assert count == 1


def test_claim_is_exclusive(athlete_with_history, db_session):
    """Двойной claim: первый True, второй False (дедуп исполнителей)."""
    sid = _session_id(athlete_with_history.id, db_session)
    InsightRepository.upsert(athlete_with_history.id, sid, db=db_session)
    assert InsightRepository.claim(sid, db=db_session) is True
    assert InsightRepository.claim(sid, db=db_session) is False
    row = InsightRepository.for_session(athlete_with_history.id, sid, db=db_session)
    assert row.status == "running"
    assert row.attempts == 1
    assert row.claimed_at is not None


def test_release_returns_to_queue_then_errors(athlete_with_history, db_session):
    """Сбой после claim → строка в pending; исчерпание попыток → error."""
    sid = _session_id(athlete_with_history.id, db_session)
    InsightRepository.upsert(athlete_with_history.id, sid, db=db_session)
    for attempt in range(1, REVIEW_MAX_ATTEMPTS + 1):
        assert InsightRepository.claim(sid, db=db_session) is True
        InsightRepository.release(sid, db=db_session)
        row = InsightRepository.for_session(athlete_with_history.id, sid, db=db_session)
        expected = "pending" if attempt < REVIEW_MAX_ATTEMPTS else "error"
        assert row.status == expected, f"attempt={attempt}"


def test_reclaim_stale_running(athlete_with_history, db_session):
    """Зависший running (креш между claim и finish) возвращается в очередь."""
    sid = _session_id(athlete_with_history.id, db_session)
    InsightRepository.upsert(athlete_with_history.id, sid, db=db_session)
    assert InsightRepository.claim(sid, db=db_session)
    row = InsightRepository.for_session(athlete_with_history.id, sid, db=db_session)
    row.claimed_at = datetime.now(timezone.utc) - timedelta(minutes=60)
    db_session.commit()
    assert InsightRepository.reclaim_stale_running(15, db=db_session) == 1
    row = InsightRepository.for_session(athlete_with_history.id, sid, db=db_session)
    assert row.status == "pending"


def test_expire_older_than(athlete_with_history, db_session):
    """Протухший pending → expired; computed_json сохраняется."""
    sid = _session_id(athlete_with_history.id, db_session)
    InsightRepository.upsert(athlete_with_history.id, sid, db=db_session,
                             computed={"drift": {"applicable": False}},
                             schema_version=1)
    row = InsightRepository.for_session(athlete_with_history.id, sid, db=db_session)
    row.created_at = datetime.now(timezone.utc) - timedelta(hours=30)
    db_session.commit()
    assert InsightRepository.expire_older_than(24, db=db_session) == 1
    row = InsightRepository.for_session(athlete_with_history.id, sid, db=db_session)
    assert row.status == "expired"
    assert row.computed_json is not None


def test_pending_older_than_picks_due_only(athlete_with_history, db_session):
    """Джоба берёт только pending старше таймаута (свежие ждут тапа)."""
    sessions = db_session.query(TrainingSession).filter_by(
        user_id=athlete_with_history.id).order_by(
        TrainingSession.begin_ts.desc()).limit(2).all()
    fresh, old = sessions[0].id, sessions[1].id
    InsightRepository.upsert(athlete_with_history.id, fresh, db=db_session)
    InsightRepository.upsert(athlete_with_history.id, old, db=db_session)
    row = InsightRepository.for_session(athlete_with_history.id, old, db=db_session)
    row.created_at = datetime.now(timezone.utc) - timedelta(minutes=45)
    db_session.commit()
    due = InsightRepository.pending_older_than(30, db=db_session)
    assert [r.session_id for r in due] == [old]


def test_recent_returns_done_only(athlete_with_history, db_session):
    """recent отдаёт только завершённые итоги, новые первыми, в пределах окна."""
    sessions = db_session.query(TrainingSession).filter_by(
        user_id=athlete_with_history.id).order_by(
        TrainingSession.begin_ts.desc()).limit(3).all()
    done1, done2, pending = (s.id for s in sessions)
    InsightRepository.upsert(athlete_with_history.id, done1, db=db_session)
    InsightRepository.finish(done1, db=db_session, source="llm",
                             effort_match="harder", carry_forward="беречь колено")
    InsightRepository.upsert(athlete_with_history.id, done2, db=db_session)
    InsightRepository.finish(done2, db=db_session, source="fallback")
    InsightRepository.upsert(athlete_with_history.id, pending, db=db_session)
    rows = InsightRepository.recent(athlete_with_history.id, db=db_session)
    assert {r.session_id for r in rows} == {done1, done2}
    assert all(r.status == "done" for r in rows)
    by_sid = {r.session_id: r for r in rows}
    assert by_sid[done1].carry_forward == "беречь колено"
    assert by_sid[done1].effort_match == "harder"


def test_for_session_ownership(athlete_with_history, empty_user, db_session):
    """Чужой user_id не видит строку (ownership-фильтр)."""
    sid = _session_id(athlete_with_history.id, db_session)
    InsightRepository.upsert(athlete_with_history.id, sid, db=db_session)
    assert InsightRepository.for_session(empty_user.id, sid, db=db_session) is None


def test_finish_missing_row_is_noop(athlete_with_history, db_session):
    """finish по сессии без insight-строки (legacy) — молча ничего."""
    InsightRepository.finish(999999, db=db_session, source="llm")  # не бросает


def _stale_claimed(sid: int, db, minutes: int = 60) -> WorkoutInsight:
    """Сдвинуть claimed_at в прошлое (имитация зависшего running)."""
    row = db.query(WorkoutInsight).filter_by(session_id=sid).first()
    row.claimed_at = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    db.commit()
    return row


def test_reclaim_does_not_touch_done(athlete_with_history, db_session):
    """Регрессия гонки #256: живой исполнитель успел finish → reclaim НЕ
    возвращает done обратно в pending (нет повторного разбора)."""
    sid = _session_id(athlete_with_history.id, db_session)
    InsightRepository.upsert(athlete_with_history.id, sid, db=db_session)
    assert InsightRepository.claim(sid, db=db_session)
    _stale_claimed(sid, db_session)
    InsightRepository.finish(sid, db=db_session, source="llm")

    assert InsightRepository.reclaim_stale_running(15, db=db_session) == 0
    db_session.expire_all()
    row = InsightRepository.for_session(athlete_with_history.id, sid, db=db_session)
    assert row.status == "done"


def test_reclaim_exhausted_attempts_goes_error(athlete_with_history, db_session):
    """Reclaim при attempts >= MAX → error (ветка раньше не покрывалась)."""
    sid = _session_id(athlete_with_history.id, db_session)
    InsightRepository.upsert(athlete_with_history.id, sid, db=db_session)
    assert InsightRepository.claim(sid, db=db_session)
    row = _stale_claimed(sid, db_session)
    row.attempts = REVIEW_MAX_ATTEMPTS
    db_session.commit()

    assert InsightRepository.reclaim_stale_running(15, db=db_session) == 1
    db_session.expire_all()
    row = InsightRepository.for_session(athlete_with_history.id, sid, db=db_session)
    assert row.status == "error"


def test_release_does_not_touch_done(athlete_with_history, db_session):
    """release после параллельного finish — done не откатывается (#256)."""
    sid = _session_id(athlete_with_history.id, db_session)
    InsightRepository.upsert(athlete_with_history.id, sid, db=db_session)
    assert InsightRepository.claim(sid, db=db_session)
    InsightRepository.finish(sid, db=db_session, source="llm")
    InsightRepository.release(sid, db=db_session)
    db_session.expire_all()
    row = InsightRepository.for_session(athlete_with_history.id, sid, db=db_session)
    assert row.status == "done"


# --- recent_flag (F3): флаг недавнего разбора → сигнал safety --------------------

def test_recent_flag_true_within_window(athlete_with_history, db_session):
    """Свежая строка с флагом в computed.flags → True (окно 4 дня)."""
    from src.coach.config import HRR_POOR_RECOVERY_LOOKBACK_DAYS

    sid = _session_id(athlete_with_history.id, db_session)
    InsightRepository.upsert(
        athlete_with_history.id, sid, db=db_session,
        computed={"flags": ["heat", "poor_interval_recovery"]}, schema_version=6)
    assert InsightRepository.recent_flag(
        athlete_with_history.id, "poor_interval_recovery", db=db_session,
        days=HRR_POOR_RECOVERY_LOOKBACK_DAYS) is True


def test_recent_flag_false_when_stale(athlete_with_history, db_session):
    """Строка старше окна → False (флаг «протухает»)."""
    sid = _session_id(athlete_with_history.id, db_session)
    row = InsightRepository.upsert(
        athlete_with_history.id, sid, db=db_session,
        computed={"flags": ["poor_interval_recovery"]}, schema_version=6)
    row.created_at = datetime.now(timezone.utc) - timedelta(days=10)
    db_session.commit()
    assert InsightRepository.recent_flag(
        athlete_with_history.id, "poor_interval_recovery",
        db=db_session, days=4) is False


def test_recent_flag_false_without_flag_or_computed(athlete_with_history, db_session):
    """Флага нет в flags / computed_json пуст → False (без исключений)."""
    ids = [s.id for s in db_session.query(TrainingSession).filter_by(
        user_id=athlete_with_history.id).order_by(TrainingSession.id).all()]
    InsightRepository.upsert(athlete_with_history.id, ids[0], db=db_session,
                             computed={"flags": ["heat"]}, schema_version=6)
    InsightRepository.upsert(athlete_with_history.id, ids[1], db=db_session,
                             computed=None)
    assert InsightRepository.recent_flag(
        athlete_with_history.id, "poor_interval_recovery",
        db=db_session, days=4) is False
