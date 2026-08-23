# Детерминированный рендер карточек (Deterministic card rendering) — DEV_PLAN §1.3
#
# ЕДИНСТВЕННОЕ место, где числа коуча превращаются в текст для пользователя.
# Проза LLM идёт НАД карточкой и чисел не называет — гарантия здесь, не в промпте.
# (The only place coach numbers become user-facing text.)

from __future__ import annotations

from src.coach.contracts import AthleteState, Prescription, SafetyVerdict, SkillResult

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


def render_prescription(p: Prescription) -> str:
    """Карточка назначения — все числа только из заклэмпленного Prescription."""
    lines = [f"*{_TYPE_LABEL.get(p.workout_type, p.workout_type)}*"]
    if p.workout_type != "rest":
        parts = [f"Z{p.target['max_zone']} и ниже"]
        if p.volume.get("duration_min") is not None:
            parts.append(f"{p.volume['duration_min']:.0f} мин")
        if p.volume.get("distance_km") is not None:
            parts.append(f"~{p.volume['distance_km']:.1f} км")
        if p.target.get("structure"):
            parts.append(p.target["structure"])
        lines.append(" · ".join(parts))
    if p.earliest is not None and p.workout_type != "rest":
        lines.append(f"Интенсив — не раньше {p.earliest:%d.%m %H:%M}")
    if p.clamped:
        lines.append("")
        lines.append(render_safety_note(p.safety))
    return "\n".join(lines)


def render_safety_note(verdict: SafetyVerdict) -> str:
    """Фиксированный не-LLM-блок ограничения (fixed non-LLM safety block)."""
    reasons = "; ".join(r.reason for r in verdict.reasons[:3]) or "границы безопасности"
    return f"⚠️ *Ограничение по безопасности:* {reasons}."


def _skill_line(sr: SkillResult) -> str:
    icon = _STATUS_ICON.get(sr.status, "⚪")
    val = ""
    if sr.value is not None:
        val = f" — {sr.value}{(' ' + sr.unit) if sr.unit else ''}"
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
    return "\n".join(lines)
