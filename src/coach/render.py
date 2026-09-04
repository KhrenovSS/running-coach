# Детерминированный рендер карточек (Deterministic card rendering) — DEV_PLAN §1.3
#
# ЕДИНСТВЕННОЕ место, где числа коуча превращаются в текст для пользователя.
# Проза LLM идёт НАД карточкой и чисел не называет — гарантия здесь, не в промпте.
# (The only place coach numbers become user-facing text.)

from __future__ import annotations

from datetime import date
from typing import Any

from src.analysis.hr_zones import zone_ceiling_hr
from src.analysis.utils import format_pace
from src.coach.contracts import AthleteState, Prescription, SafetyVerdict, SkillResult
from src.coach.safety import is_stride
from src.coach.render_segments import (compact_segments, render_segment_lines,
                                       segments_total_min, visible_segments)
from src.config.constants import HR_DISPLAY_UNIT
from src.utils.timeutils import WEEKDAYS_RU as _WEEKDAYS_RU
from src.utils.timeutils import local_dt

_TYPE_LABEL = {
    "rest": "🛌 Отдых",
    "recovery": "🚶 Восстановительный бег",
    "easy": "🟢 Лёгкий бег",
    "long": "🟦 Длительный бег",
    "tempo": "🟠 Темповая",
    "interval": "🔴 Интервалы",
    "race": "🏁 Соревнование",
}
_STATUS_ICON = {"ok": "🟢", "warning": "🟡", "danger": "🔴", "unknown": "⚪"}


def _day_label(when: date | None, today: date | None = None) -> str | None:
    """«воскресенье 31.08» для будущего дня; None — сегодня/нет даты (day label)."""
    today = today or date.today()
    if when is None or when <= today:
        return None
    return f"{_WEEKDAYS_RU[when.weekday()]} {when:%d.%m}"


def _hr_ceiling(p: Prescription, max_hr: int | None, lthr: int | None = None) -> int | None:
    """Потолок пульса назначения в уд/мин или None (prescription bpm ceiling)."""
    if p.target.get("hr_ceiling") is not None:
        return int(p.target["hr_ceiling"])       # #295: зафиксированный при назначении потолок
    if max_hr is None or p.target.get("max_zone") is None:
        return None
    return zone_ceiling_hr(p.target["max_zone"], max_hr, lthr)


def _predicted_estimate(p: Prescription) -> tuple[float, float] | None:
    """(темп, дистанция) из прогноза по данным пользователя или None (estimate)."""
    predicted = p.predicted or {}
    pace, km = predicted.get("pace_min_km"), predicted.get("distance_km")
    if pace and km:
        return pace, km
    return None


def _pace_lead_lines(p: Prescription) -> list[str]:
    """Строки pace-режима: цель — темп+время, пульс — справочный прогноз.

    (Pace-lead card lines: pace+time are the goal, HR is a reference estimate.)
    """
    pace = p.target["pace_min_km"]
    parts = [f"Темп {format_pace(pace)}/км"]
    if p.volume.get("duration_min") is not None:
        parts.append(f"{p.volume['duration_min']:.0f} мин")
    if p.volume.get("distance_km") is not None:
        parts.append(f"≈{p.volume['distance_km']:.1f} км")
    if p.target.get("structure") and not p.target.get("segments"):
        parts.append(p.target["structure"])
    lines = [" · ".join(parts), "Ведём по темпу — на пульс сегодня не смотрим."]
    if p.predicted.get("expected_hr") is not None:
        lines.append(f"Пульс будет в районе ~{p.predicted['expected_hr']} "
                     f"{HR_DISPLAY_UNIT} (ориентировочно, по твоим пробежкам)")
    else:
        lines.append("Пульс не прогнозирую — мало данных на этом темпе.")
    return lines


def _hr_lead_lines(p: Prescription, max_hr: int | None,
                   lthr: int | None = None) -> list[str]:
    """Строки HR-режима: цель — зона/пульс+время, темп и км — ориентир.

    (HR-lead card lines: zone/HR+time are the goal, pace and km are estimates.)
    """
    estimate = _predicted_estimate(p)
    ceiling = _hr_ceiling(p, max_hr, lthr)
    # Пульс в уд/мин; ярлык зоны — только когда потолок посчитать нельзя (02.09.2026)
    parts = ([f"пульс до {ceiling} {HR_DISPLAY_UNIT}"] if ceiling is not None
             else [f"Z{p.target['max_zone']} и ниже"])
    if p.volume.get("duration_min") is not None:
        parts.append(f"{p.volume['duration_min']:.0f} мин")
    if p.volume.get("distance_km") is not None and estimate is None:
        parts.append(f"~{p.volume['distance_km']:.1f} км")
    if p.target.get("structure") and not p.target.get("segments"):
        parts.append(p.target["structure"])
    lines = [" · ".join(parts)]
    if estimate is not None:
        pace, km = estimate
        # #264: честная пометка качества оценки; старые predicted без quality = band
        quality = (p.predicted or {}).get("quality", "band")
        if quality == "adjusted":
            lines.append(f"Прикидка (данных на этом пульсе мало): "
                         f"~{format_pace(pace)}/км → ≈{km:.1f} км")
        elif quality == "typical":
            lines.append(f"По твоим прошлым таким пробежкам: "
                         f"~{format_pace(pace)}/км → ≈{km:.1f} км (без привязки к пульсу)")
        elif quality == "threshold":
            lines.append(f"Нормативный темп зоны от ПАНО часов: "
                         f"~{format_pace(pace)}/км → ≈{km:.1f} км")
        else:
            lines.append(f"Ориентир по твоим пробежкам: "
                         f"~{format_pace(pace)}/км → ≈{km:.1f} км")
    return lines


def render_prescription(p: Prescription, max_hr: int | None = None,
                        lthr: int | None = None,
                        user: Any = None, today: date | None = None) -> str:
    """Карточка назначения — все числа только из заклэмпленного Prescription.

    max_hr — для потолка пульса зоны в уд/мин; None → без строки пульса.
    user — для локального пояса времени (user timezone); None → settings.timezone.
    today — точка отсчёта метки дня (для тестов); None → date.today().
    Режим по target["pace_min_km"]: задан → ведём по темпу (цель — темп+время,
    пульс справочно); нет → по пульсу (цель — зона+время, темп/км — ориентир).
    Будущий день (p.when > today) — день в заголовке + пометка «предварительно».
    """
    day = _day_label(p.when, today)
    title = _TYPE_LABEL.get(p.workout_type, p.workout_type)
    segments = visible_segments(p.target)     # ровная пробежка — без разбивки (02.09.2026)
    work = [s for s in segments if s.get("role") == "work"]
    if (work and all(is_stride(s) for s in work)
            and p.workout_type in ("easy", "long", "recovery")):
        # только короткие ускорения; длинные отрезки в Z3+ — уже tempo/interval (safety 04.09)
        title += " с ускорениями"
    header = f"*{title} — {day}*" if day else f"*{title}*"
    if segments:
        # Итог считаем из самих сегментов — иначе верхняя строка (общая длительность
        # предложения) противоречит сумме сегментов (инцидент 01.09: 35 мин vs ~46).
        total = segments_total_min(segments)
        if total:
            header += f" · ~{total} мин"
    lines = [header]
    if p.workout_type != "rest":
        if segments:
            lines += render_segment_lines(segments)   # посегментная раскладка вместо сводной
        elif p.target.get("pace_min_km") is not None:
            lines += _pace_lead_lines(p)
        else:
            lines += _hr_lead_lines(p, max_hr, lthr)
    if p.earliest is not None and p.workout_type != "rest":
        # naive-UTC → пояс пользователя (BACKLOG #260; инциденты 23.08 и 26.08: UTC)
        earliest = local_dt(p.earliest, user)
        lines.append(f"Интенсив — не раньше {earliest:%d.%m %H:%M}")
    if day:
        # План на будущий день строится по сегодняшним данным — утренний вердикт
        # целевого дня перепроверит его по свежим метрикам (provisional plan note).
        lines.append("Предварительно — утром сверимся по состоянию.")
    if p.clamped:
        lines.append("")
        lines.append(render_safety_note(p.safety))
    return "\n".join(lines)


def render_prescription_short(p: Prescription, max_hr: int | None = None,
                              lthr: int | None = None,
                              today: date | None = None) -> str:
    """Строка-напоминание: назначение на день не изменилось (unchanged-plan line).

    Решение владельца 26.08.2026: в дневном чате при неизменном назначении
    вместо повторной полной карточки — одна короткая строка. Будущий день —
    «План на воскресенье (31.08) …» вместо «на сегодня».
    """
    day = _day_label(p.when, today)
    prefix = (f"План на {day.split()[0]} ({p.when:%d.%m}) без изменений:\n" if day
              else "План на сегодня без изменений:\n")
    parts = [_TYPE_LABEL.get(p.workout_type, p.workout_type)]
    if p.workout_type != "rest":
        if p.target.get("pace_min_km") is not None:
            parts.append(f"темп {format_pace(p.target['pace_min_km'])}/км")
            if p.volume.get("duration_min") is not None:
                parts.append(f"{p.volume['duration_min']:.0f} мин")
            if p.volume.get("distance_km") is not None:
                parts.append(f"≈{p.volume['distance_km']:.1f} км")
            return prefix + " · ".join(parts)
        ceiling = _hr_ceiling(p, max_hr, lthr)
        if ceiling is not None:
            parts.append(f"пульс до {ceiling}")
        elif p.target.get("max_zone") is not None:
            parts.append(f"Z{p.target['max_zone']} и ниже")
        if p.volume.get("duration_min") is not None:
            parts.append(f"{p.volume['duration_min']:.0f} мин")
        estimate = _predicted_estimate(p)
        if estimate is not None:
            pace, km = estimate
            parts.append(f"~{format_pace(pace)}/км ≈ {km:.1f} км")
        segs = visible_segments(p.target)
        if segs:
            # «Детали в дне» должны быть и в короткой карточке (02.09.2026)
            parts.append(compact_segments(segs, max_hr, lthr))
    return prefix + " · ".join(parts)


def render_safety_note(verdict: SafetyVerdict) -> str:
    """Фиксированный не-LLM-блок ограничения (fixed non-LLM safety block)."""
    reasons = "; ".join(r.reason for r in verdict.reasons[:3]) or "границы безопасности"
    return f"⚠️ *Ограничение по безопасности:* {reasons}."


def _skill_line(sr: SkillResult) -> str:
    icon = _STATUS_ICON.get(sr.status, "⚪")
    val = ""
    if sr.value is not None:
        # backticks: внутри code-entity `_` безопасен для legacy-Markdown (инцидент 23.08)
        val = f" — `{sr.value}{(' ' + sr.unit) if sr.unit else ''}`"
    return f"{icon} {sr.key}{val}"


def render_state_card(state: AthleteState) -> str:
    """Сводка состояния (state summary card) — для /verdict и fallback-чата."""
    lines = ["*Состояние*"]
    if state.as_of is not None:
        lines.append(f"Данные на {state.as_of:%d.%m}")
    if state.readiness_score is not None:
        lines.append(f"Готовность: {state.readiness_score:.0f}/100")
    if state.fatigue_score is not None:
        lines.append(f"Усталость: {state.fatigue_score:.0f}/100")
    if state.recovery_hours_left:
        lines.append(f"До восстановления: {state.recovery_hours_left:.0f} ч")
    if state.zone_balance:
        lines.append(f"Z1–Z2 за 28 дней: {state.zone_balance['z1_z2']:.0%}")
    lines += [_skill_line(s) for s in state.skills.values()]
    if state.data_confidence < 0.5:
        lines.append(f"_Данных мало (доверие {state.data_confidence:.0%}) — выводы осторожные._")
    return "\n".join(lines)


def render_review(sr: SkillResult) -> str:
    """Детерминированный разбор тренировки (deterministic workout review) — fallback."""
    icon = _STATUS_ICON.get(sr.status, "⚪")
    lines = [f"{icon} *Разбор тренировки*", sr.message.replace("; ", "\n")]
    if sr.status == "warning" and sr.evidence:
        # Данные под вопросом — причина обязана дойти до пользователя, не только до LLM
        # (suspect data: the reason must reach the user, not just the LLM context)
        lines.append(f"_Данные под вопросом: {sr.evidence}_")
    return "\n".join(lines)


def render_gps_warning(gps_quality: dict | None) -> str | None:
    """Предупреждение о недостоверном GPS: числа рендерит детерминированный код,
    не проза LLM (инвариант DEV_PLAN §1). None — GPS в порядке.
    (GPS-unreliable warning; numbers come from deterministic render, not LLM prose.)"""
    if not gps_quality or not gps_quality.get("unreliable"):
        return None
    first = gps_quality.get("bad_first_min")
    last = gps_quality.get("bad_last_min")
    span_min = round(last - first) if first is not None and last is not None else None
    prefix = f"⚠️ GPS сбоил ~{span_min} мин" if span_min and span_min >= 1 else "⚠️ GPS сбоил"
    # Пользователю сопоставляем число, которое он видел на часах (device), а не
    # внутреннюю пост-очистку (contrast with the number the user saw on the watch)
    device_km = gps_quality.get("device_distance_km")
    dist = gps_quality.get("distance") or {}
    if dist.get("source") == "cadence_estimate" and dist.get("estimated_km"):
        line = f"{prefix}: дистанция ~`{dist['estimated_km']:.1f} км` — оценка по шагам"
        if device_km:
            line += f" (часы намерили {device_km:.1f} км)"
    else:
        line = f"{prefix}: дистанция и темп этой тренировки ненадёжны"
        if device_km:
            line += f" (часы намерили {device_km:.1f} км)"
    return line


def render_weekly(summary: dict) -> str:
    """Детерминированный недельный дайджест (deterministic weekly digest) — fallback C8.

    summary — выход tool'а get_weekly_summary; значения в backticks (инцидент 23.08).
    """
    lines = ["*Итоги недели*"]
    for w in summary.get("weeks", []):
        parts = [f"нед. {w['week_start']}:",
                 f"`{w['km']} км`", f"`{w['sessions']} трен.`"]
        if w.get("easy_share") is not None:
            parts.append(f"easy `{w['easy_share']:.0%}`")
        lines.append(" · ".join(parts))
    if summary.get("wow_change_pct") is not None:
        lines.append(f"Объём к прошлой неделе: `{summary['wow_change_pct']:+.1f}%`")
    if summary.get("avg_rpe") is not None:
        lines.append(f"Средний RPE: `{summary['avg_rpe']:.1f}`")
    return "\n".join(lines)
