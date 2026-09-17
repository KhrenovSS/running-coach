# Диапазон времени ровного дня (Plain-day time range) — решение владельца 17.09.2026.
#
# Инцидент 17.09: утро урезало плановые 40 → 30 мин ради точности ±5 % недели. Вместо точки ровный день
# (easy/recovery/long без сегментов и без целевого темпа) получает диапазон «минимум ради эффекта — план»:
# низ = max(PLAN_EASY_MIN_MINUTES, LOW_PCT × верх), у длительной мягче (гайд 45: ключевой стимул) и не ниже
# порога длительной. Верх остаётся `volume.duration_min` (суммы, кэпы, экспорт не меняются), низ —
# производный ключ `volume.duration_min_low`, считается один раз в `prescriber.finalize`; километры —
# следствие темпа истории, не хранятся. Качественные/структурные/race/pace-режим — точка.
# (Derived low bound for plain days; upper bound stays the single hard number.)

from __future__ import annotations

from src.analysis.utils import format_pace
from src.coach.config import (
    LONG_RUN_MIN_MINUTES,
    PLAN_EASY_MIN_MINUTES,
    VOLUME_RANGE_LOW_PCT,
    VOLUME_RANGE_LOW_PCT_LONG,
)

RANGE_TYPES = ("easy", "recovery", "long")


def duration_low(workout_type: str | None, duration_min: float | None, *, has_segments: bool,
                 has_pace: bool, long_min_minutes: float = LONG_RUN_MIN_MINUTES) -> float | None:
    """Низ диапазона минут или None (точка): только ровные дни RANGE_TYPES без структуры и темпа;
    low = max(PLAN_EASY_MIN_MINUTES, pct × верх), long — VOLUME_RANGE_LOW_PCT_LONG и ≥ порога длительной;
    low ≥ верх → None. Чистая функция. (Derived low bound; None means a single value.)"""
    if workout_type not in RANGE_TYPES or not duration_min or has_segments or has_pace:
        return None
    pct = VOLUME_RANGE_LOW_PCT_LONG if workout_type == "long" else VOLUME_RANGE_LOW_PCT
    low = max(PLAN_EASY_MIN_MINUTES, round(float(duration_min) * pct))
    if workout_type == "long":
        low = max(low, long_min_minutes)
    return float(low) if low < float(duration_min) else None


def has_range(volume: dict | None) -> bool:
    v = volume or {}
    low, high = v.get("duration_min_low"), v.get("duration_min")
    return bool(low and high and low < high)


def minutes_label(volume: dict | None) -> str | None:
    """«30–40 мин» при диапазоне, «40 мин» без него, None — минут нет. (Minutes label for cards.)"""
    v = volume or {}
    high = v.get("duration_min")
    if high is None:
        return None
    if has_range(v):
        return f"{v['duration_min_low']:.0f}–{high:.0f} мин"
    return f"{high:.0f} мин"


def km_range(volume: dict | None, predicted: dict | None) -> tuple[float, float] | None:
    """(низ, верх) км по темпу прогноза: низ = duration_min_low / pace, верх = predicted.distance_km.
    None — диапазона или прогноза нет. (Km bounds derived from the pace estimate; not stored.)"""
    v, p = volume or {}, predicted or {}
    pace, km = p.get("pace_min_km"), p.get("distance_km")
    if not has_range(v) or not pace or not km:
        return None
    return round(v["duration_min_low"] / pace, 1), float(km)


def km_label(volume: dict | None, predicted: dict | None, *, prefix: str = "≈") -> str | None:
    """«≈4.3–5.7 км» при диапазоне, «≈5.7 км» по прогнозу, None — прогноза нет."""
    p = predicted or {}
    bounds = km_range(volume, p)
    if bounds is not None:
        return f"{prefix}{bounds[0]:.1f}–{bounds[1]:.1f} км"
    if p.get("distance_km"):
        return f"{prefix}{p['distance_km']:.1f} км"
    return None


def estimate_line(volume: dict | None, predicted: dict | None, *, lead: str) -> str:
    """Строка ориентира карточки: «{lead}~7:03/км → ≈4.3–5.7 км» (или одиночные км)."""
    pace = (predicted or {}).get("pace_min_km")
    return f"{lead}~{format_pace(pace)}/км → {km_label(volume, predicted)}"
