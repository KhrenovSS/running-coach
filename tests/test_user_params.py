# #274/#327 (11.09.2026): единый резолвер параметров анализа из профиля и его доставка в live-путь
# парсеров (раньше parse_fit/parse_tcx не принимали interval_* — синк классифицировал по дефолтам,
# reanalyze — по настройкам пользователя).
from pathlib import Path
from types import SimpleNamespace

from src.analysis.user_params import analysis_kwargs, gps_kwargs, interval_kwargs
from src.config.constants import (
    DEFAULT_HR_LAG_SEC, DEFAULT_MIN_OSCILLATIONS, DEFAULT_MIN_PHASE_DISTANCE_M,
    DEFAULT_MIN_PHASE_DURATION_SEC, DEFAULT_PACE_THRESHOLD, MAX_CREDIBLE_PACE, MAX_GPS_JUMP_M,
    MIN_HR_FOR_FAST_PACE,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_kwargs_defaults_without_user_or_with_empty_fields():
    empty = SimpleNamespace(interval_pace_threshold=None, interval_min_phase_duration=None,
                            interval_min_phase_distance_m=None, interval_hr_lag_sec=None,
                            interval_min_oscillations=None, max_credible_pace=None,
                            max_gps_jump_m=None, min_hr_for_fast_pace=None)
    for user in (None, empty):
        assert interval_kwargs(user) == {
            "pace_gap": DEFAULT_PACE_THRESHOLD,
            "interval_min_phase_duration": DEFAULT_MIN_PHASE_DURATION_SEC,
            "interval_min_phase_distance_m": DEFAULT_MIN_PHASE_DISTANCE_M,
            "interval_hr_lag_sec": DEFAULT_HR_LAG_SEC,
            "interval_min_oscillations": DEFAULT_MIN_OSCILLATIONS,
        }
        assert gps_kwargs(user) == {"max_credible_pace": MAX_CREDIBLE_PACE,
                                    "max_gps_jump_m": MAX_GPS_JUMP_M,
                                    "min_hr_for_fast_pace": MIN_HR_FOR_FAST_PACE}


def test_kwargs_take_user_values():
    user = SimpleNamespace(interval_pace_threshold=0.7, interval_min_phase_duration=45,
                           interval_min_phase_distance_m=150, interval_hr_lag_sec=8,
                           interval_min_oscillations=4, max_credible_pace=2.8,
                           max_gps_jump_m=80.0, min_hr_for_fast_pace=125)
    kw = analysis_kwargs(user)
    assert kw["pace_gap"] == 0.7 and kw["interval_min_phase_duration"] == 45
    assert kw["interval_min_phase_distance_m"] == 150 and kw["interval_hr_lag_sec"] == 8
    assert kw["interval_min_oscillations"] == 4
    assert kw["max_credible_pace"] == 2.8 and kw["max_gps_jump_m"] == 80.0
    assert kw["min_hr_for_fast_pace"] == 125


def test_parse_tcx_forwards_interval_kwargs(monkeypatch):
    """#327: interval_* доходят до process_trackpoints через parse_tcx."""
    import src.parsers.tcx_parser as tcx
    seen = {}

    def fake_process(trackpoints, start, max_hr, max_credible_pace, **kw):
        seen.update(kw, max_hr=max_hr, max_credible_pace=max_credible_pace)
        return {"ok": True}
    monkeypatch.setattr(tcx, "process_trackpoints", fake_process)
    user = SimpleNamespace(interval_pace_threshold=0.7, interval_min_phase_duration=45,
                           interval_min_phase_distance_m=150, interval_hr_lag_sec=8,
                           interval_min_oscillations=4, max_credible_pace=2.8,
                           max_gps_jump_m=80.0, min_hr_for_fast_pace=125)
    assert tcx.parse_tcx(str(FIXTURES / "tempo_run.tcx"), max_hr=180, **analysis_kwargs(user)) == {"ok": True}
    assert seen["pace_gap"] == 0.7 and seen["interval_min_oscillations"] == 4
    assert seen["interval_hr_lag_sec"] == 8 and seen["max_gps_jump_m"] == 80.0
    assert seen["max_credible_pace"] == 2.8 and seen["max_hr"] == 180


def test_parse_fit_forwards_interval_kwargs(monkeypatch):
    """#327: то же для FIT (extract_fit_activity замокан — бинарный файл не нужен)."""
    from datetime import datetime, timezone
    import src.parsers.fit_parser as fit
    seen = {}
    t0 = datetime(2026, 9, 11, 6, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(fit, "extract_fit_activity", lambda path, coros_cadence_workaround=False: {
        "trackpoints": [{"time": t0, "dist": 0.0}], "laps": [], "device_summary": {}, "calories": None})

    def fake_process(trackpoints, start, max_hr, max_credible_pace, **kw):
        seen.update(kw)
        return {"ok": True}
    monkeypatch.setattr(fit, "process_trackpoints", fake_process)
    user = SimpleNamespace(interval_pace_threshold=0.9, interval_min_phase_duration=30,
                           interval_min_phase_distance_m=None, interval_hr_lag_sec=None,
                           interval_min_oscillations=None, max_credible_pace=None,
                           max_gps_jump_m=None, min_hr_for_fast_pace=None)
    out = fit.parse_fit("/nonexistent.fit", max_hr=180, **analysis_kwargs(user))
    assert out["ok"] is True and out["laps_json"] is None
    assert seen["pace_gap"] == 0.9 and seen["interval_min_phase_duration"] == 30
    assert seen["interval_min_phase_distance_m"] == DEFAULT_MIN_PHASE_DISTANCE_M   # None → дефолт
    assert "laps" in seen and "watch_stride_m" in seen                              # прежние kw не потеряны


def test_segments_get_weather_after_merge(monkeypatch):
    """#252 закрыт как невоспроизводимый: temperature/weather_code проставляются сегментам ПОСЛЕ
    segment_by_pace (где живёт _merge_similar_segments) — у каждого итогового сегмента ключи есть."""
    from datetime import datetime, timedelta, timezone
    import src.analysis as analysis
    from tests.helpers import build_trackpoints

    t0 = datetime(2026, 6, 1, 6, 0, tzinfo=timezone.utc)
    tps = build_trackpoints('tempo', start_time=t0, max_hr=177)
    for i, tp in enumerate(tps):                      # позиции нужны, чтобы погода запрашивалась
        tp['lat'], tp['lon'] = 55.75 + i * 1e-5, 37.62
    hours = [(t0 - timedelta(hours=3) + timedelta(hours=h)) for h in range(8)]
    weather = {"times": [h.strftime("%Y-%m-%dT%H:%M") for h in hours],
               "temps": [15.0 + h for h in range(8)], "codes": [1] * 8, "precip": [0.0] * 8}
    monkeypatch.setattr(analysis, "fetch_weather", lambda *a, **k: weather)

    result = analysis.process_trackpoints(tps, t0, max_hr=177)
    assert result is not None and result["segments_json"]
    for seg in result["segments_json"]:
        assert seg.get("temperature") is not None and seg.get("weather_code") is not None
