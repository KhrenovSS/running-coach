# Тесты хранилища сырых файлов и reanalyze-от-сырья (Raw file storage + raw reanalyze tests — BACKLOG #229)

from pathlib import Path

from src.services import raw_files
from src.services.raw_files import save_raw_file, resolve_raw_file, sha256_hex
from src.services.reanalyze import reanalyze_training
from tests.helpers import build_training_session, make_user

FIXTURES = Path(__file__).parent / "fixtures"


def _user(db, n: int):
    return make_user(db, chat_id=98000 + n, email=f"raw_{n}@example.com")


class TestRawStorage:
    def test_save_is_content_addressed_and_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(raw_files.settings, "raw_files_dir", str(tmp_path))
        content = b"fake-fit-content"
        p1 = save_raw_file(7, content, ".FIT")
        p2 = save_raw_file(7, content, "fit")

        assert p1 == p2, "одинаковый контент — один файл (content-addressed)"
        assert Path(p1).read_bytes() == content
        assert sha256_hex(content) in p1
        assert "/7/" in p1

    def test_resolve_missing_returns_none(self):
        assert resolve_raw_file(None) is None
        assert resolve_raw_file("/nonexistent/path.fit") is None

    def test_save_failure_returns_none(self, monkeypatch):
        # Недоступная директория → None, без исключения (unwritable dir → None, no raise)
        monkeypatch.setattr(raw_files.settings, "raw_files_dir", "/proc/forbidden")
        assert save_raw_file(1, b"data", "fit") is None


def _render_tcx(trackpoints) -> str:
    """Собрать минимальный валидный TCX из синтетических трекпоинтов
    (Render a minimal valid TCX from synthetic trackpoints)."""
    rows = []
    for tp in trackpoints:
        rows.append(
            f"<Trackpoint><Time>{tp['time'].strftime('%Y-%m-%dT%H:%M:%SZ')}</Time>"
            f"<Position><LatitudeDegrees>{tp['lat']}</LatitudeDegrees>"
            f"<LongitudeDegrees>{tp['lon']}</LongitudeDegrees></Position>"
            f"<AltitudeMeters>{tp['alt'] or 150}</AltitudeMeters>"
            f"<DistanceMeters>{tp['dist']}</DistanceMeters>"
            f"<HeartRateBpm><Value>{tp['hr']}</Value></HeartRateBpm></Trackpoint>"
        )
    start = trackpoints[0]['time'].strftime('%Y-%m-%dT%H:%M:%SZ')
    return (
        '<?xml version="1.0"?>'
        '<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">'
        f'<Activities><Activity Sport="Running"><Id>{start}</Id><Lap StartTime="{start}"><Track>'
        + ''.join(rows) +
        '</Track></Lap></Activity></Activities></TrainingCenterDatabase>'
    )


class TestReanalyzeFromRaw:
    def test_reanalyze_prefers_raw_file(self, db_session, tmp_path):
        """Сессия БЕЗ trackpoints_json, но с сырым TCX → пересчёт работает от сырья
        и заполняет кэш trackpoints_json."""
        from tests.helpers import build_trackpoints
        user = _user(db_session, 1)
        tps = build_trackpoints(training_type='tempo', distance_km=6.0)
        raw = tmp_path / "run.tcx"
        raw.write_text(_render_tcx(tps))
        session = build_training_session(
            db_session, user.id,
            begin_ts=tps[0]['time'],
            trackpoints_json=None,
            raw_file_path=str(raw),
            source_brand='manual',
        )

        result = reanalyze_training(db_session, session.id, user.id)

        assert result is not None
        assert result['training_type'] != 'invalid'
        db_session.refresh(session)
        assert session.trackpoints_json, "кэш очищенных трекпоинтов должен обновиться от сырья"

    def test_reanalyze_falls_back_to_cache_when_raw_missing(self, db_session):
        """Сырьё указано, но файла нет → fallback на trackpoints_json (legacy-путь)."""
        from src.analysis.utils import serialize_trackpoints
        from tests.helpers import build_trackpoints
        user = _user(db_session, 2)
        tps = build_trackpoints(training_type='tempo', distance_km=6.0)
        session = build_training_session(
            db_session, user.id,
            begin_ts=tps[0]['time'],
            trackpoints_json=serialize_trackpoints(tps),
            raw_file_path="/nonexistent/gone.fit",
        )

        result = reanalyze_training(db_session, session.id, user.id)
        assert result is not None
