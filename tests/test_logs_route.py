# /logs (#303/#119, 07.09.2026): только для вошедшего; имена ротации как у логгера; день валидируется.
import os
os.environ["SECRET_KEY"] = "test-secret-key-for-pytest"   # явно, не setdefault (#233)

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from src.api.deps import get_current_user
from src.startup import create_app
from src.web.routes import logs as logs_mod

app = create_app()
client = TestClient(app)


def test_logs_requires_login():
    resp = client.get("/logs", follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/login"


def test_logs_reads_live_and_rotated_files(tmp_path, monkeypatch):
    monkeypatch.setattr(logs_mod, "LOGS_DIR", Path(tmp_path))
    (tmp_path / "app.log").write_text("INFO today-line <b>\n", encoding="utf-8")
    (tmp_path / "app.log.2026-09-01").write_text("ERROR old-line\n", encoding="utf-8")
    app.dependency_overrides[get_current_user] = lambda: object()
    try:
        live = client.get("/logs?lines=10")
        assert live.status_code == 200 and "today-line &lt;b&gt;" in live.text   # экранирование
        assert "2026-09-01" in live.text                                          # навигация по дням
        old = client.get("/logs?day=2026-09-01")
        assert "old-line" in old.text and "today-line" not in old.text
        assert client.get("/logs?day=../etc/passwd").status_code == 400          # только YYYY-MM-DD
        assert client.get(f"/logs?day={date.today().isoformat()}").status_code == 200
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_logs_level_from_field_not_message_text(tmp_path, monkeypatch):
    """#120: слово WARNING/ERROR внутри INFO-сообщения не меняет класс строки; уровень — из поля."""
    monkeypatch.setattr(logs_mod, "LOGS_DIR", Path(tmp_path))
    (tmp_path / "app.log").write_text(
        "2026-09-11 16:44:30 | INFO     | app | user typed WARNING and ERROR\n"
        "2026-09-11 16:44:31 | WARNING  | coach | real warning\n"
        "2026-09-11 16:44:32 | CRITICAL | app | boom\n"
        "plain line without level field\n", encoding="utf-8")
    app.dependency_overrides[get_current_user] = lambda: object()
    try:
        html = client.get("/logs?lines=10").text
        assert "<span class='INFO'>2026-09-11 16:44:30 | INFO" in html
        assert "<span class='WARNING'>2026-09-11 16:44:31" in html
        assert "<span class='ERROR'>2026-09-11 16:44:32 | CRITICAL" in html
        assert "<span class='INFO'>plain line" in html
    finally:
        app.dependency_overrides.pop(get_current_user, None)

