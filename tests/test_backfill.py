# Тест backfill-скрипта avg_pace (bin/backfill_avg_pace.py) — Трек 2 / проверка модуля.
# Скрипт лежит в bin/ (не пакет) — загружаем через importlib.

import importlib.util
import pathlib

from src.domain.models.base import utcnow
from src.models import TrainingSession
from tests.helpers import make_user

_SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "bin" / "backfill_avg_pace.py"


def _load_backfill():
    spec = importlib.util.spec_from_file_location("backfill_avg_pace", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _session(db, user_id, avg_pace, dist=10.0, dur=50.0):
    s = TrainingSession(user_id=user_id, begin_ts=utcnow(), total_distance_km=dist,
                        duration_minutes=dur, avg_pace=avg_pace, training_type="easy",
                        segments_json=[])
    db.add(s); db.commit(); db.refresh(s)
    return s


def test_backfill_fills_null_avg_pace_only(db_session):
    user = make_user(db_session, chat_id=77001, email="backfill@example.com")
    null_s = _session(db_session, user.id, avg_pace=None, dist=10.0, dur=50.0)   # → 5.0
    kept_s = _session(db_session, user.id, avg_pace=4.2, dist=10.0, dur=50.0)     # не трогать

    mod = _load_backfill()
    updated = mod.backfill_avg_pace()

    db_session.expire_all()
    assert updated == 1
    assert db_session.get(TrainingSession, null_s.id).avg_pace == 5.0    # 50/10
    assert db_session.get(TrainingSession, kept_s.id).avg_pace == 4.2    # неизменно


def test_backfill_idempotent(db_session):
    """Повторный запуск ничего не меняет (нет NULL с валидными dist/dur)."""
    user = make_user(db_session, chat_id=77002, email="backfill2@example.com")
    _session(db_session, user.id, avg_pace=None, dist=8.0, dur=40.0)
    mod = _load_backfill()
    assert mod.backfill_avg_pace() == 1   # первый проход
    assert mod.backfill_avg_pace() == 0   # второй — no-op


def test_backfill_skips_zero_distance(db_session):
    """NULL avg_pace, но distance=0 → не трогаем (нельзя делить)."""
    user = make_user(db_session, chat_id=77003, email="backfill3@example.com")
    _session(db_session, user.id, avg_pace=None, dist=0.0, dur=40.0)
    mod = _load_backfill()
    assert mod.backfill_avg_pace() == 0
