# Рендер посегментной раскладки тренировки (per-segment card rendering) — M2.1.
#
# Вынесено из render.py ради дисциплины ~400 строк/файл. Числа берутся из уже
# заклэмпленных и обогащённых сегментов (segments.enrich_and_clamp_segments) —
# инвариант «числа для пользователя рендерит код, не проза LLM» сохранён.

from __future__ import annotations

from src.analysis.hr_zones import zone_ceiling_hr
from src.analysis.utils import format_pace

_SEG_ROLE = {"warmup": "Разминка", "steady": "Бег", "cooldown": "Заминка"}


def _fmt_amount(kind: str | None, value: float | None) -> str | None:
    """Объём сегмента в естественных единицах или None (segment amount)."""
    if value is None or kind in (None, "open"):
        return None
    if kind == "sec":
        return f"{value:.0f} сек"
    if kind == "min":
        return f"{value:g} мин"
    if kind == "km":
        return f"{value:g} км"
    if kind == "m":
        return f"{value:.0f} м"
    return None


def _work_label(seg: dict) -> str:
    """«Ускорения» для коротких кусков, иначе «Работа» (work segment label)."""
    kind, val = seg.get("amount_kind"), seg.get("amount_value") or 0
    return "Ускорения" if (kind == "sec" or (kind == "min" and val < 2)) else "Работа"


def _seg_minutes(seg: dict) -> float | None:
    """Время сегмента в минутах или None, если по объёму не посчитать (segment minutes)."""
    kind, val = seg.get("amount_kind"), seg.get("amount_value")
    if val is None or kind == "open":
        return None
    if kind == "min":
        return float(val)
    if kind == "sec":
        return val / 60.0
    pace = seg.get("pace_hint_min_km")
    if kind == "km" and pace:
        return val * pace
    if kind == "m" and pace:
        return (val / 1000.0) * pace
    return None


def _recovery_minutes(rec: dict) -> float | None:
    """Время восстановления в минутах (только по duration_min; HR/дистанция → None)."""
    return float(rec["duration_min"]) if rec.get("duration_min") is not None else None


def segments_total_min(segments: list[dict]) -> int | None:
    """Общий итог времени тренировки из сегментов (deterministic total minutes).

    Сумма repeat×(время сегмента) + repeat×(время восстановления). HR-only восстановление
    и объём без темпа в итог не входят — итог ориентировочный, но не противоречит сегментам.
    """
    total = 0.0
    for seg in segments:
        rep = max(1, seg.get("repeat", 1))
        lead = _seg_minutes(seg)
        if lead is not None:
            total += rep * lead
        rec = seg.get("recovery")
        if rec:
            rm = _recovery_minutes(rec)
            if rm is not None:
                total += rep * rm
    return round(total) if total > 0 else None


def _fmt_recovery(rec: dict) -> str:
    """Критерии восстановления: «2 мин трусцой или до пульса ≤125» (recovery criteria)."""
    crits = []
    if rec.get("duration_min") is not None:
        crits.append(f"{rec['duration_min']:g} мин трусцой")
    if rec.get("distance_km") is not None:
        crits.append(f"{rec['distance_km']:g} км трусцой")
    if rec.get("until_hr") is not None:
        crits.append(f"до пульса ≤{rec['until_hr']}")
    return " или ".join(crits) if crits else "лёгкая трусца"


def render_segment_lines(segments: list[dict]) -> list[str]:
    """Посегментная раскладка тренировки с метриками для часов (per-segment lines)."""
    lines: list[str] = []
    for seg in segments:
        role = seg.get("role")
        head = _work_label(seg) if role == "work" else _SEG_ROLE.get(role, "Бег")
        if seg.get("repeat", 1) > 1:
            head += f" ×{seg['repeat']}"
        parts: list[str] = []
        amt = _fmt_amount(seg.get("amount_kind"), seg.get("amount_value"))
        if amt:
            parts.append(amt)
        zone = seg.get("target_zone")
        if seg.get("hr_ceiling") is not None:
            # Пульс в уд/мин, без ярлыка зоны (пожелание владельца 02.09.2026)
            parts.append(f"пульс до {seg['hr_ceiling']}")
        elif zone is not None:
            parts.append(f"Z{zone}")            # зона — только когда пульс неизвестен
        if seg.get("pace_target_min_km") is not None:
            parts.append(f"темп {format_pace(seg['pace_target_min_km'])}/км")
        elif seg.get("pace_hint_min_km") is not None:
            parts.append(f"~{format_pace(seg['pace_hint_min_km'])}/км")
        # Короткий/быстрый кусок без темпа: цель по ощущениям (не «мало данных»).
        if seg.get("effort"):
            parts.append(seg["effort"])
        elif (role == "work" and seg.get("pace_target_min_km") is None
              and seg.get("pace_hint_min_km") is None):
            parts.append("по ощущениям")
        lines.append(f"{head}: " + " · ".join(parts))
        if seg.get("recovery"):
            lines.append("   отдых между: " + _fmt_recovery(seg["recovery"]))
    return lines


_COMPACT_ROLE = {"warmup": "разм", "cooldown": "зам"}
_MONOTONE_ROLES = {"warmup", "steady", "cooldown"}


def _role_of(seg) -> str | None:
    return seg.get("role") if isinstance(seg, dict) else getattr(seg, "role", None)


def is_monotone(segments) -> bool:
    """Ровная пробежка: только разминка/бег/заминка и не больше одного ровного блока.

    Решение владельца 02.09.2026: такую тренировку не делим на сущности — она целиком
    «пульс до N · время». Структура остаётся при работе/восстановлении (ускорения,
    интервалы) и при двух ровных блоках с разным пульсом («до 130, потом 130–140»).
    Принимает dict-сегменты и WorkoutSegment. (Monotone run → no segment structure.)
    """
    roles = [_role_of(s) for s in (segments or [])]
    return bool(roles) and set(roles) <= _MONOTONE_ROLES and roles.count("steady") <= 1


def visible_segments(target: dict | None) -> list[dict]:
    """Сегменты для показа: монотонная структура скрывается (и для уже сохранённых строк)."""
    segs = (target or {}).get("segments") or []
    return [] if is_monotone(segs) else segs


def _seg_bpm(seg: dict, max_hr: int | None, lthr: int | None) -> int | None:
    """Потолок пульса сегмента: от текущего якоря зон (согласованно с потолком строки),
    иначе сохранённый hr_ceiling, иначе None (segment bpm ceiling)."""
    zone = seg.get("target_zone")
    if max_hr and zone is not None:
        bpm = zone_ceiling_hr(zone, max_hr, lthr)
        if bpm is not None:
            return bpm
    return seg.get("hr_ceiling")


def compact_segments(segments: list[dict] | None, max_hr: int | None = None,
                     lthr: int | None = None) -> str:
    """Структура тренировки одной строкой для карточки недели / короткой карточки дня:
    «25 мин до 138 + 7×18 сек до 156 + зам 5 мин до 126». Пульс — в уд/мин; зона (Z2) —
    только когда пульс посчитать нельзя. Восстановление и подсказки темпа — в полной
    раскладке. (One-line structure, bpm-first.)
    """
    parts: list[str] = []
    for seg in segments or []:
        amt = _fmt_amount(seg.get("amount_kind"), seg.get("amount_value"))
        role, zone = seg.get("role"), seg.get("target_zone")
        rep = seg.get("repeat", 1) or 1
        bpm = _seg_bpm(seg, max_hr, lthr)
        intensity = f"до {bpm}" if bpm is not None else (f"Z{zone}" if zone is not None else "")
        if role in _COMPACT_ROLE:
            body = f"{_COMPACT_ROLE[role]} {amt}" if amt else _COMPACT_ROLE[role]
        else:
            body = amt or "—"
            if rep > 1:
                body = f"{rep}×{body}"
        parts.append(f"{body} {intensity}".rstrip())
    return " + ".join(parts)
