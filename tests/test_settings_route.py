# POST /settings (#239, 11.09.2026): max_hr вне MAX_HR_MIN..MAX_HR_CAP отклоняется редиректом с ошибкой,
# значение в БД не меняется; валидное — сохраняется. Паттерн TestClient — tests/test_logs_route.py.
import os
os.environ["SECRET_KEY"] = "test-secret-key-for-pytest"   # явно, не setdefault (#233)

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.api.deps import get_current_user
from src.config import settings as app_settings
from src.config.constants import MAX_HR_CAP, MAX_HR_MIN
from src.models import User, get_db
from src.startup import create_app
from tests.helpers import make_user

app = create_app()
client = TestClient(app)
_HEADERS = {"origin": app_settings.web_app_url} if app_settings.web_app_url else {}


def _as(user, db):
    """Роут видит того же пользователя и то же соединение: in-memory SQLite не делит таблицы между
    соединениями, а TestClient исполняет роут в другом потоке (пул — per-thread), поэтому сессия роута
    привязывается к соединению фикстуры. (Route session bound to the fixture's connection.)"""
    route_db = Session(bind=db.connection())
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: route_db


def _reset():
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


def test_settings_rejects_max_hr_out_of_range(db_session):
    user = make_user(db_session, chat_id=93951, email="set-93951@example.com", max_hr=177)
    _as(user, db_session)
    try:
        resp = client.post("/settings", data={"max_hr": str(MAX_HR_CAP + 80)},
                           headers=_HEADERS, follow_redirects=False)
        assert resp.status_code == 303 and resp.headers["location"] == "/settings?error=max_hr"
        db_session.expire_all()
        assert db_session.query(User).filter(User.id == user.id).first().max_hr == 177
        page = client.get("/settings?error=max_hr", headers=_HEADERS)
        assert page.status_code == 200 and f"{MAX_HR_MIN}–{MAX_HR_CAP}" in page.text
        assert f"min='{MAX_HR_MIN}' max='{MAX_HR_CAP}'" in page.text     # границы формы — из констант
    finally:
        _reset()


def test_settings_accepts_valid_max_hr(db_session):
    user = make_user(db_session, chat_id=93952, email="set-93952@example.com", max_hr=177)
    _as(user, db_session)
    try:
        resp = client.post("/settings", data={"max_hr": "180"}, headers=_HEADERS, follow_redirects=False)
        assert resp.status_code == 303 and resp.headers["location"] == "/"
        db_session.expire_all()
        assert db_session.query(User).filter(User.id == user.id).first().max_hr == 180
    finally:
        _reset()
