# Сегментация по лапам часов (#302, 08.09.2026) — Lap-aware segmentation.
#
# Если лапы структурные (программа на часах или ручные отсечки — не авто-километры), часы знают
# структуру тренировки точнее любой эвристики по темпу: 7×18 с ускорений темповый детектор не видит
# (окно 50 м, фазы < 60 с/200 м отсекаются), а лапы несут их поштучно. Дистанция и длительность
# сегмента берутся из лапа (часы надёжнее GPS — случай 01.09 с gps_unreliable), пульс/каденс/высота —
# из среза трекпоинтов по времени лапа. Форма сегмента — та же, что у km/pace-сегментов
# (`segment_km._build_segment_stats`), плюс `source="laps"`, `lap`, `intensity`.
# (Structured watch laps become segments verbatim; distance/time from the lap, HR/cadence/alt from
# the trackpoint slice; same dict shape as the other segmenters.)

from __future__ import annotations

from datetime import datetime, timezone

from src.analysis.hr_zones import get_band, get_zone
from src.analysis.intervals import structural_laps
from src.analysis.segment_km import _build_segment_stats
from src.analysis.utils import format_duration, format_pace
from src.config.constants import LAP_PACE_SANITY_MAX_MIN_KM, LAP_PACE_SANITY_MIN_MIN_KM

LAP_SEGMENTS_MIN = 3   # меньше окон на треке → лапы не используем (прежний путь)


def _as_dt(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def _align(dt: datetime, ref: datetime) -> datetime:
    """Привести aware/naive к виду ref (FIT даёт naive UTC, reanalyze — aware)."""
    if ref.tzinfo is None and dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    if ref.tzinfo is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def lap_windows(laps: list[dict], t0: datetime) -> list[tuple[float, float] | None]:
    """Окна лапов (start_sec, end_sec) от t0; None — у лапа нет start_time.

    Конец: `end_time`, иначе start следующего лапа, иначе start + (elapsed_s или timer_s).
    (Lap windows in seconds from track start; None when the lap has no start time.)
    """
    starts = [_as_dt(l.get("start_time")) for l in laps]
    out: list[tuple[float, float] | None] = []
    for i, lap in enumerate(laps):
        st = starts[i]
        if st is None:
            out.append(None)
            continue
        start_sec = (_align(st, t0) - t0).total_seconds()
        end_dt = _as_dt(lap.get("end_time"))
        if end_dt is None and i + 1 < len(laps):
            end_dt = starts[i + 1]
        if end_dt is not None:
            end_sec = (_align(end_dt, t0) - t0).total_seconds()
        else:
            end_sec = start_sec + float(lap.get("elapsed_s") or lap.get("timer_s") or 0)
        out.append((start_sec, end_sec) if end_sec > start_sec else None)
    return out


def _slice_points(trackpoints: list[dict], t0: datetime, start_sec: float, end_sec: float) -> list[dict]:
    """Лёгкие точки среза [start, end): dist_delta/time_delta_sec/hr/cad/alt (как km_segment_fallback)."""
    points, prev = [], None
    for cur in trackpoints:
        t = _as_dt(cur.get("time"))
        if t is None:
            continue
        sec = (_align(t, t0) - t0).total_seconds()
        if sec < start_sec:
            prev = cur
            continue
        if sec >= end_sec:
            break
        if prev is not None and prev.get("time") is not None:
            pt = _as_dt(prev["time"])
            d_delta = (_align(t, t0) - _align(pt, t0)).total_seconds()
            d_dist = (max(0.0, (cur.get("dist") or 0) - (prev.get("dist") or 0))
                      if cur.get("dist") is not None and prev.get("dist") is not None else 0.0)
            if d_delta > 0:
                points.append({"dist_delta": d_dist, "time_delta_sec": d_delta,
                               "hr": prev.get("hr"), "cad": prev.get("cad"), "alt": prev.get("alt")})
        prev = cur
    return points


def _slice_summary(points: list[dict]) -> dict:
    """HR/каденс среза по времени — независимо от GPS-дистанции (time-weighted HR/cadence)."""
    hr_w = [(p["hr"], p["time_delta_sec"]) for p in points if p.get("hr") is not None]
    cad_w = [(p["cad"], p["time_delta_sec"]) for p in points if p.get("cad")]
    out: dict = {}
    if hr_w and sum(w for _, w in hr_w) > 0:
        out["avg_hr"] = round(sum(h * w for h, w in hr_w) / sum(w for _, w in hr_w))
    if cad_w and sum(w for _, w in cad_w) > 0:
        out["avg_cadence"] = round(sum(c * w for c, w in cad_w) / sum(w for _, w in cad_w))
    return out


def lap_segments(laps: list[dict] | None, trackpoints: list[dict], max_hr: int,
                 lthr: int | None = None) -> list[dict] | None:
    """Сегменты по структурным лапам или None (авто-км / нет лапов / окна не легли на трек).
    (Segments from structured laps; None → caller falls back to pace/km segmentation.)"""
    laps = structural_laps(laps)
    if not laps or not trackpoints:
        return None
    t0 = _as_dt(trackpoints[0].get("time"))
    if t0 is None:
        return None
    segments: list[dict] = []
    for i, (lap, window) in enumerate(zip(laps, lap_windows(laps, t0))):
        if window is None:
            continue
        start_sec, end_sec = window
        dist_m = float(lap.get("distance_m") or 0)
        timer_s = float(lap.get("timer_s") or lap.get("elapsed_s") or (end_sec - start_sec))
        if dist_m <= 0 or timer_s <= 0:
            continue
        points = _slice_points(trackpoints, t0, start_sec, end_sec)
        # stats даёт высоту (и HR/каденс при живом GPS); при нулевой GPS-дистанции — сводка по времени
        stats = (_build_segment_stats(points, max_hr, lthr) if len(points) >= 2 else None) or {}
        summary = _slice_summary(points)
        avg_hr = stats.get("avg_hr") or summary.get("avg_hr") or lap.get("avg_hr")
        dur_min = timer_s / 60.0
        pace = dur_min / (dist_m / 1000.0)
        # Санити: темп лапа вне [3:00, 15:00] → дистанция часов мусорная (GPS-сбой) — оставляем
        # время и пульс, дистанцию/темп не выдумываем (implausible lap pace → no distance/pace)
        dist_ok = LAP_PACE_SANITY_MIN_MIN_KM <= pace <= LAP_PACE_SANITY_MAX_MIN_KM
        seg = {
            "duration_min": round(dur_min, 1),
            "duration": format_duration(dur_min),
            "distance_km": round(dist_m / 1000.0, 2) if dist_ok else None,   # 2 dp: 62 м = 0.06
            "avg_hr": avg_hr,
            "pace": format_pace(pace) if dist_ok else None,
            "pace_min_km": round(pace, 2) if dist_ok else None,
            "avg_cadence": stats.get("avg_cadence") or summary.get("avg_cadence") or lap.get("avg_cadence"),
            "zone": get_zone(avg_hr, max_hr, lthr) if avg_hr else None,
            "band": get_band(avg_hr, max_hr, lthr) if avg_hr else None,
            "elevation_gain": stats.get("elevation_gain", lap.get("ascent_m")),
            "elevation_loss": stats.get("elevation_loss", lap.get("descent_m")),
            "source": "laps",
            "lap": i + 1,
        }
        if not dist_ok:
            seg["distance_unreliable"] = True
        if lap.get("intensity"):
            seg["intensity"] = lap["intensity"]
        segments.append(seg)
    if len(segments) < LAP_SEGMENTS_MIN:
        return None
    return segments
