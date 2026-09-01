# Кросс-чеки данных с эталонами часов (F2/F7, #286): чистая математика без БД.
# (Data cross-checks against watch-reported references; pure math, no DB.)
#
# device_check — F2: расхождение дистанции/времени пайплайна с session-сообщением
# часов > DEVICE_MISMATCH_PCT → mismatch (collect_flags → device_mismatch → suspect_data).
# lap_check — F7: телеметрия per_km против авто-км лапов (только лог, флагов нет).

from __future__ import annotations

from src.config.constants import DEVICE_MISMATCH_PCT
from src.utils.logger import get_logger

logger = get_logger("analysis.data_checks")


def device_check(device_summary: dict | None, total_distance_km: float | None,
                 duration_minutes: float | None) -> dict | None:
    """Расхождение с эталоном часов; None — эталона нет (legacy/TCX).
    (Pipeline vs watch-reported distance/time; None when no summary stored.)"""
    ds = device_summary if isinstance(device_summary, dict) else None
    if not ds:
        return None
    out: dict = {"mismatch": False}
    dev_km = (ds.get("distance_m") or 0) / 1000
    if dev_km > 0 and total_distance_km:
        diff = abs(total_distance_km - dev_km) / dev_km
        out["dist_diff_pct"] = round(diff, 3)
        if diff > DEVICE_MISMATCH_PCT:
            out["mismatch"] = True
    dev_min = (ds.get("timer_s") or 0) / 60
    if dev_min > 0 and duration_minutes:
        diff = abs(duration_minutes - dev_min) / dev_min
        out["time_diff_pct"] = round(diff, 3)
        if diff > DEVICE_MISMATCH_PCT:
            out["mismatch"] = True
    return out


def lap_check(laps: list | None, per_km: list[dict] | None) -> dict | None:
    """F7 (телеметрия): сверка per_km пайплайна с авто-км лапами часов.

    Только лог/числа, флагов нет: расхождение >2% сигналит о дрейфе алгоритма.
    None — лапы не авто-км (структурные) или сверять нечего.
    (Pipeline per_km vs watch auto-km laps; telemetry only, no flags.)"""
    if not laps or not per_km:
        return None
    body = laps[:-1]
    auto = [l for l in body if 900 <= (l.get('distance_m') or 0) <= 1100]
    if len(auto) < 2 or len(auto) != len(body):
        return None  # структурная разметка — не эталон километров
    diffs = []
    for lap, row in zip(auto, per_km):
        timer, dist = lap.get('timer_s'), lap.get('distance_m')
        if not timer or not dist or not row.get('pace_min_km'):
            continue
        lap_pace = timer / 60 / (dist / 1000)
        diffs.append(abs(row['pace_min_km'] - lap_pace) / lap_pace)
    if not diffs:
        return None
    max_diff = max(diffs)
    if max_diff > 0.02:
        logger.warning("Lap check: per_km vs watch auto-laps diff %.1f%% (laps=%d)",
                       max_diff * 100, len(auto))
    return {"kms_compared": len(diffs), "max_pace_diff_pct": round(max_diff, 3)}
