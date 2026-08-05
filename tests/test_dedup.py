# Тесты дедупликации по внешнему ID (External-id dedup tests — BACKLOG #228, Этап 3)

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from src.models import SessionLocal, TrainingSession, DeletedTraining
from src.services.sync.dedup import (
    load_dedup_state, is_duplicate, find_deleted_match, near_any,
)
from src.services.training_service import delete_training
from tests.helpers import build_training_session, make_user

BT = datetime(2026, 7, 10, 8, 0, 0, tzinfo=timezone.utc)


def _user(db, n: int):
    return make_user(db, chat_id=97000 + n, email=f"dedup_{n}@example.com")


class TestUniqueConstraints:
    def test_duplicate_external_id_rejected_by_db(self, db_session):
        """Частичный UNIQUE: второй insert с тем же (user, brand, ext_id) отбивается БД."""
        user = _user(db_session, 1)
        build_training_session(db_session, user.id, begin_ts=BT,
                               external_activity_id="act-1", source_brand="coros")
        with pytest.raises(IntegrityError):
            build_training_session(db_session, user.id, begin_ts=BT + timedelta(hours=1),
                                   external_activity_id="act-1", source_brand="coros")
        db_session.rollback()

    def test_null_external_ids_do_not_conflict(self, db_session):
        """NULL не конфликтуют — legacy-строки и ручные загрузки безопасны."""
        user = _user(db_session, 2)
        build_training_session(db_session, user.id, begin_ts=BT)
        build_training_session(db_session, user.id, begin_ts=BT + timedelta(hours=1))
        count = db_session.query(TrainingSession).filter(
            TrainingSession.user_id == user.id).count()
        assert count == 2

    def test_duplicate_file_sha_rejected_by_db(self, db_session):
        """Частичный UNIQUE по file_sha256: повторная загрузка того же файла отбивается."""
        user = _user(db_session, 3)
        build_training_session(db_session, user.id, begin_ts=BT, file_sha256="a" * 64)
        with pytest.raises(IntegrityError):
            build_training_session(db_session, user.id, begin_ts=BT + timedelta(hours=1),
                                   file_sha256="a" * 64)
        db_session.rollback()


class TestDedupLogic:
    def test_duplicate_by_external_id(self, db_session):
        user = _user(db_session, 4)
        build_training_session(db_session, user.id, begin_ts=BT,
                               external_activity_id="act-42", source_brand="coros")
        state = load_dedup_state(db_session, user.id, "coros", None)
        # Тот же ID, но время «уехало» на 10 минут — всё равно дубликат (id wins over time)
        assert is_duplicate(state, "act-42", BT + timedelta(minutes=10))
        assert not is_duplicate(state, "act-43", BT + timedelta(days=2))

    def test_legacy_fallback_window(self, db_session):
        """Строка без внешнего ID: дубликат ловится окном ±120с, а не посекундным равенством."""
        user = _user(db_session, 5)
        build_training_session(db_session, user.id, begin_ts=BT)  # legacy, без ID
        state = load_dedup_state(db_session, user.id, "coros", None)
        assert is_duplicate(state, "new-act", BT + timedelta(seconds=45)), \
            "сдвиг 45с внутри окна — раньше (посекундное равенство) это давало дубль"
        assert not is_duplicate(state, "new-act", BT + timedelta(seconds=300))

    def test_deleted_match_by_external_id(self, db_session):
        user = _user(db_session, 6)
        d = DeletedTraining(user_id=user.id, begin_ts=BT,
                            external_activity_id="act-del", source_brand="coros")
        db_session.add(d)
        db_session.commit()
        state = load_dedup_state(db_session, user.id, "coros", None)
        assert find_deleted_match(state, "act-del", BT + timedelta(minutes=30)) is not None
        assert find_deleted_match(state, "other", BT + timedelta(days=1)) is None

    def test_deleted_match_legacy_window(self, db_session):
        user = _user(db_session, 7)
        d = DeletedTraining(user_id=user.id, begin_ts=BT)  # legacy, без ID
        db_session.add(d)
        db_session.commit()
        state = load_dedup_state(db_session, user.id, "coros", None)
        assert find_deleted_match(state, "any", BT + timedelta(seconds=60)) is not None

    def test_near_any_handles_naive_timestamps(self):
        """SQLite отдаёт naive datetime — сравнение не должно падать."""
        naive = BT.replace(tzinfo=None)
        assert near_any(BT + timedelta(seconds=10), [naive])


class TestDeleteKeepsExternalId:
    def test_delete_training_copies_external_id(self, db_session):
        """При удалении внешний ID переезжает в DeletedTraining — ре-синк узнает тренировку."""
        user = _user(db_session, 8)
        s = build_training_session(db_session, user.id, begin_ts=BT,
                                   external_activity_id="act-99", source_brand="coros")
        assert delete_training(db_session, user.id, s.id)
        d = db_session.query(DeletedTraining).filter(
            DeletedTraining.user_id == user.id).first()
        assert d.external_activity_id == "act-99"
        assert d.source_brand == "coros"
