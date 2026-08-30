# Тесты vision-извлечения сна и записи (#257)
import httpx
import pytest

from src.coach import vision
from src.coach.vision import SleepShot, extract_sleep
from src.services.sleep_ingest import save_sleep_shot
from src.models import DailyMetrics
from tests.coach.conftest import _unique_user


def _bridge(monkeypatch, text: str, status: int = 200):
    """Подменить httpx.post на мост-ответ (сеть в тестах запрещена)."""
    def fake_post(url, json=None, headers=None, timeout=None):
        req = httpx.Request("POST", url)
        return httpx.Response(status, json={"text": text}, request=req)
    monkeypatch.setattr(vision.httpx, "post", fake_post)
    monkeypatch.setattr(vision.settings, "coach_llm_bridge_url", "http://bridge")


def test_extract_sleep_valid(monkeypatch):
    # Реальный экран Coros: длительность + deep/rem %, бдение, стресс, bedtime-сдвиг
    _bridge(monkeypatch, '{"is_sleep_screen": true, "duration_min": 352, '
            '"deep_pct": 10, "rem_pct": 22, "awake_min": 10, '
            '"awake_interruptions": 0, "bedtime_offset_min": 49, '
            '"sleep_stress": 21, "note": "сон ниже нормы", "date": null}')
    shot = extract_sleep(b"img")
    assert shot is not None and shot.has_data()
    assert shot.duration_min == 352 and shot.deep_pct == 10 and shot.rem_pct == 22
    assert shot.sleep_stress == 21 and shot.bedtime_offset_min == 49
    extra = shot.extra()
    assert extra["deep_pct"] == 10 and extra["sleep_stress"] == 21
    assert extra["note"] == "сон ниже нормы"


def test_extract_sleep_not_a_sleep_screen(monkeypatch):
    _bridge(monkeypatch, '{"is_sleep_screen": false}')
    shot = extract_sleep(b"img")
    assert shot is not None and shot.has_data() is False


def test_extract_sleep_bad_json_returns_none(monkeypatch):
    _bridge(monkeypatch, "извините, не смог прочитать")
    assert extract_sleep(b"img") is None


def test_extract_sleep_bridge_error_returns_none(monkeypatch):
    _bridge(monkeypatch, "", status=502)
    assert extract_sleep(b"img") is None


def test_extract_sleep_no_bridge_configured(monkeypatch):
    monkeypatch.setattr(vision.settings, "coach_llm_bridge_url", "")
    assert extract_sleep(b"img") is None


def test_out_of_range_rejected(monkeypatch):
    # deep_pct 150 вне 0-100 → ValidationError → None (не пишем мусор)
    _bridge(monkeypatch, '{"is_sleep_screen": true, "duration_min": 400, "deep_pct": 150}')
    assert extract_sleep(b"img") is None


def test_save_sleep_shot_upsert(db_session):
    """Запись в DailyMetrics по локальной дате; повтор — обновление, не дубль."""
    from datetime import date
    user = _unique_user(db_session)
    shot = SleepShot(is_sleep_screen=True, duration_min=352, deep_pct=10,
                     rem_pct=22, awake_min=10, sleep_stress=21,
                     bedtime_offset_min=49, date=date.today().isoformat())
    dm = save_sleep_shot(user.id, shot, db=db_session)
    assert dm.sleep_duration_min == 352 and dm.sleep_awake_min == 10
    assert dm.sleep_extra["deep_pct"] == 10 and dm.sleep_extra["sleep_stress"] == 21
    assert dm.sleep_source == "coros_screenshot"

    shot2 = SleepShot(is_sleep_screen=True, duration_min=500, deep_pct=15,
                      date=date.today().isoformat())
    save_sleep_shot(user.id, shot2, db=db_session)
    rows = db_session.query(DailyMetrics).filter_by(user_id=user.id).all()
    assert len(rows) == 1 and rows[0].sleep_duration_min == 500  # апдейт, не дубль


def test_save_sleep_shot_keeps_existing_hrv(db_session):
    """Скрин сна не перетирает Coros-HRV/recovery за тот же день."""
    from datetime import date
    user = _unique_user(db_session)
    dm = DailyMetrics(user_id=user.id, date=date.today(), avg_sleep_hrv=62.0,
                      recovery_pct=44, source_brand="coros")
    db_session.add(dm)
    db_session.commit()
    save_sleep_shot(user.id, SleepShot(is_sleep_screen=True, duration_min=440,
                                       date=date.today().isoformat()), db=db_session)
    db_session.refresh(dm)
    assert dm.avg_sleep_hrv == 62.0 and dm.recovery_pct == 44  # HRV цел
    assert dm.sleep_duration_min == 440


def test_missing_sleep_cleared_when_data_present(db_session):
    """#257: 'sleep' уходит из missing при наличии sleep_duration_min."""
    from datetime import date
    from src.coach.state import assess_state
    user = _unique_user(db_session)
    state = assess_state(user.id, db=db_session)
    assert "sleep" in state.missing              # данных нет — честно missing

    dm = DailyMetrics(user_id=user.id, date=date.today(), sleep_duration_min=440,
                      sleep_source="coros_screenshot")
    db_session.add(dm)
    db_session.commit()
    state2 = assess_state(user.id, db=db_session)
    assert "sleep" not in state2.missing
