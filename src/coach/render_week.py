# Карточка недели (weekly plan card) — вынесено из render.py (лимит ~400 строк/файл, 02.09.2026)
#
# Числа — только из клэмпленных Prescription, детерминированных targets и фактов
# связанных тренировок; структура сегментов — компактной строкой (compact_segments).
# render.py этот модуль НЕ импортирует (без цикла). (Week card; numbers come from code.)

from __future__ import annotations

from datetime import date, timedelta

from src.analysis.utils import format_pace
from src.coach.contracts import Prescription
from src.coach.render import _WEEKDAYS_RU, _TYPE_LABEL, _hr_ceiling, _predicted_estimate
from src.coach.render_segments import compact_segments, visible_segments


def _distance_hint_km(p: Prescription) -> float | None:
    """Примерная дистанция для карточки: прогноз → объём → темп×время (or None).

    Прогноз первым — как в дневной карточке (`_hr_lead_lines`): при наличии истории
    километры расчётные, а не число LLM (02.09.2026: вс 9.0 vs ≈11.3).
    (Prediction first, like the day card; then volume, then pace×duration.)
    """
    est = _predicted_estimate(p)          # (pace, km) из p.predicted
    if est is not None:
        return est[1]
    km = p.volume.get("distance_km")
    if km is not None:
        return km
    pace, dur = p.target.get("pace_min_km"), p.volume.get("duration_min")
    if pace and dur:
        return dur / pace
    return None


def _pace_hint(p: Prescription) -> float | None:
    """Ориентир темпа (мин/км) для строки недели: прогноз по истории → подсказка
    самого длинного основного сегмента → None (нет данных — темп не печатаем).
    Целевой темп (pace_min_km) сюда не входит — он печатается как «темп X/км».
    (Pace hint: prediction, else the main segment's hint, else None.)
    """
    predicted = p.predicted or {}
    if predicted.get("pace_min_km"):
        return float(predicted["pace_min_km"])
    main = [s for s in (p.target.get("segments") or [])
            if s.get("role") in ("steady", "work") and s.get("pace_hint_min_km")]
    if main:
        longest = max(main, key=lambda s: float(s.get("amount_value") or 0))
        return float(longest["pace_hint_min_km"])
    return None



def _fact_line(day: str, p: Prescription, fact: dict | None,
               max_hr: int | None = None, lthr: int | None = None) -> str:
    """Прошедший день: факт связанной тренировки (✓) или пропуск (✗) — без потолка
    пульса и ≈км плана, которые дрейфуют со сменой якоря зон (past day as fact)."""
    label = _TYPE_LABEL.get(p.workout_type, p.workout_type)
    # Плановая структура прошедшего дня (ускорения и т.п.) — рядом с фактом
    segs = visible_segments(p.target)
    structure = compact_segments(segs, max_hr, lthr) if segs else ""
    head = [label, structure] if structure else [label]
    if fact is None:
        parts = list(head)
        if p.volume.get("duration_min") is not None:
            parts.append(f"{p.volume['duration_min']:.0f} мин")
        parts.append("пропущен")
        return f"✗ {day} — " + " · ".join(parts)
    parts = list(head)
    if fact.get("duration_min"):
        parts.append(f"факт {fact['duration_min']:.0f} мин")
    if fact.get("distance_km"):
        parts.append(f"{fact['distance_km']:.1f} км")
    if fact.get("pace_min_km"):
        parts.append(f"{format_pace(fact['pace_min_km'])}/км")
    if fact.get("avg_hr"):
        parts.append(f"ср. пульс {fact['avg_hr']}")
    return f"✓ {day} — " + " · ".join(parts)


def render_week_plan(prescriptions: list[Prescription], targets: dict,
                     max_hr: int | None = None, lthr: int | None = None,
                     today: date | None = None,
                     facts: dict[date, dict | None] | None = None) -> str:
    """Сводная карточка недельного плана — числа только из клэмпленных
    Prescription и детерминированных targets (weekly plan card).

    targets без мезоцикла (сохранённая неделя, week_view) → строка сводки
    опускается; today → маркер «▶» у сегодняшнего дня; facts (дата → факт или None)
    → прошедшие дни рендерятся как ✓ факт / ✗ пропущен (02.09.2026: план прошедших
    дней не «меняется», он выполнен). (Tolerant header; past days as facts.)
    """
    start = date.fromisoformat(targets["week_start"])
    end = start + timedelta(days=6)
    lines = [f"*План на неделю ({start:%d.%m}–{end:%d.%m})*"]
    if targets.get("mesocycle_week") is not None:
        summary = (f"Неделя {targets['mesocycle_week']}/{targets['mesocycle_length']} "
                   f"мезоцикла ({'разгрузочная' if targets['phase'] == 'deload' else 'рост'}) "
                   f"· цель ~{targets['target_km']:.0f} км")
        if targets.get("plan_scope") == "rest_of_week":
            # Остаток недели (#293): сколько уже сделано и что распределяли
            summary += (f" · сделано {targets['done_km']:.1f} км, "
                        f"осталось ~{targets['remaining_km']:.1f} км")
        lines.append(summary)
    has_facts = False
    for p in sorted(prescriptions, key=lambda x: x.when):
        if facts is not None and today is not None and p.when < today:
            has_facts = True
            lines.append(_fact_line(
                f"{_WEEKDAYS_RU[p.when.weekday()][:2]} {p.when:%d.%m}", p, facts.get(p.when),
                max_hr, lthr))
            continue
        mark = "▶ " if today is not None and p.when == today else ""
        day = f"{mark}{_WEEKDAYS_RU[p.when.weekday()][:2]} {p.when:%d.%m}"
        parts = [_TYPE_LABEL.get(p.workout_type, p.workout_type)]
        if p.target.get("pace_min_km") is not None:
            parts.append(f"темп {format_pace(p.target['pace_min_km'])}/км")
        else:
            ceiling = _hr_ceiling(p, max_hr, lthr)
            if ceiling is not None:
                parts.append(f"пульс до {ceiling}")
            elif p.target.get("max_zone") is not None:
                parts.append(f"Z{p.target['max_zone']} и ниже")
            pace_hint = _pace_hint(p)     # ориентир темпа по истории (02.09.2026)
            if pace_hint is not None:
                parts.append(f"~{format_pace(pace_hint)}/км")
        if p.volume.get("duration_min") is not None:
            parts.append(f"{p.volume['duration_min']:.0f} мин")
        km = _distance_hint_km(p)
        if km is not None:
            parts.append(f"≈{km:.1f} км")
        segs = visible_segments(p.target)
        if segs:
            # Структура — компактной строкой прямо здесь (02.09: «детали в дне» не было)
            parts.append(compact_segments(segs, max_hr, lthr))
        elif p.target.get("structure"):
            parts.append(p.target["structure"])
        lines.append(f"{day} — " + " · ".join(parts))
    if any(p.clamped for p in prescriptions):
        lines.append("⚠️ Часть дней урезана границами безопасности.")
    legend = "✓ факт · ✗ пропущен · " if has_facts else ""
    lines.append(f"{legend}Остальные дни — отдых. Перепланировать: /plan")
    return "\n".join(lines)
