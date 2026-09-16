# Урезание СТРУКТУРНОЙ тренировки под потолок объёма (structured-workout trimming) — 16.09.2026
#
# Решение владельца 16.09.2026 (по литературе, гайды 44/45/46/61): структурную тренировку выше
# потолка не «снимаем до ровной» и не отклоняем, а урезаем осмысленно:
#   • ускорения — «символический объём, не в счёт км» (гайд 61), ≤ STRIDES_MAX_PER_SESSION (гайд 46)
#     → режем РОВНУЮ часть (разминка/бег/заминка, с полами), число ускорений сохраняем; ровной
#     части меньше PLAN_EASY_MIN_MINUTES → ускорения снимаются (ровная пробежка под потолком);
#   • качественная работа (отрезки длиннее STRIDE_MAX_SEC) → уменьшаем ПОВТОРЫ (не ниже
#     SEGMENT_WORK_REPEAT_MIN), разминку/заминку не трогаем (гайд 44: потолки качества за сессию;
#     гайд 45: при сокращении режут наполнитель, не ключевой стимул); не помещается → структура
#     снимается, остаётся ровный бег под потолком.
# Чистые функции над WorkoutSegment (до простановки чисел); сумма минут считается как в
# render_segments.segments_total_min — итоговая длительность совпадает с суммой сегментов, поэтому
# рост после clamp (#343) невозможен по построению. (Pure helpers; total == sum of segments.)

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from src.coach.config import (
    PLAN_EASY_MIN_MINUTES,
    SEGMENT_COOLDOWN_MIN_MIN,
    SEGMENT_WARMUP_MIN_MIN,
    SEGMENT_WORK_REPEAT_MIN,
    STRIDES_MAX_PER_SESSION,
)
from src.coach.contracts import WorkoutProposal, WorkoutSegment
from src.coach.safety import is_stride

_FLEX_ROLES = ("warmup", "steady", "cooldown")
_ROLE_FLOOR_MIN = {"warmup": SEGMENT_WARMUP_MIN_MIN, "cooldown": SEGMENT_COOLDOWN_MIN_MIN}


@dataclass
class TrimResult:
    """Итог урезания: сегменты ([] — структура снята), заметка для карточки, сумма минут."""
    segments: list[WorkoutSegment]
    note: str | None
    total_min: float | None


def segment_minutes(seg: WorkoutSegment, *, pace_min_km: float | None = None) -> float | None:
    """Минуты одного повтора сегмента (без отдыха); None — по объёму не посчитать."""
    kind, val = seg.amount_kind, seg.amount_value
    if val is None or kind == "open":
        return None
    if kind == "min":
        return float(val)
    if kind == "sec":
        return float(val) / 60.0
    if kind == "km" and pace_min_km:
        return float(val) * pace_min_km
    if kind == "m" and pace_min_km:
        return float(val) / 1000.0 * pace_min_km
    return None


def _recovery_minutes(seg: WorkoutSegment) -> float:
    """Отдых между повторами в минутах; HR-критерий/дистанция → 0 (как в segments_total_min)."""
    rec = seg.recovery
    return float(rec.duration_min) if rec is not None and rec.duration_min is not None else 0.0


def _seg_total(seg: WorkoutSegment, *, pace_min_km: float | None) -> float | None:
    lead = segment_minutes(seg, pace_min_km=pace_min_km)
    if lead is None:
        return None
    return max(1, seg.repeat) * (lead + _recovery_minutes(seg))


def total_minutes(segments: list[WorkoutSegment], *,
                  pace_min_km: float | None = None) -> float | None:
    """Сумма минут структуры; None — есть сегмент без счётного объёма (total or None)."""
    total = 0.0
    for seg in segments:
        t = _seg_total(seg, pace_min_km=pace_min_km)
        if t is None:
            return None
        total += t
    return total


def _fmt(v: float) -> str:
    return f"{v:.0f}"


def _scale_flex(segments: list[WorkoutSegment], flex_target: float, *,
                pace_min_km: float | None) -> list[WorkoutSegment] | None:
    """Ужать ровную часть (разминка/бег/заминка) до flex_target минут с полами разминки/заминки;
    None — не помещается. Пропорция сохраняется, остаток уходит в «бег». (Scale steady parts.)"""
    flex_idx = [i for i, s in enumerate(segments) if s.role in _FLEX_ROLES]
    if not flex_idx:
        return None
    mins = {i: _seg_total(segments[i], pace_min_km=pace_min_km) for i in flex_idx}
    if any(m is None for m in mins.values()):
        return None
    flex_total = sum(mins.values())
    if flex_total <= 0:
        return None
    k = flex_target / flex_total
    new_min: dict[int, float] = {}
    for i in flex_idx:
        seg = segments[i]
        floor_ = _ROLE_FLOOR_MIN.get(seg.role)
        scaled = mins[i] * k
        if floor_ is not None and seg.amount_kind == "min":
            scaled = min(mins[i], max(float(floor_), scaled))    # пол, но не выше исходного
        new_min[i] = math.floor(scaled) if seg.amount_kind == "min" else scaled
    steady = [i for i in flex_idx if segments[i].role == "steady"]
    if steady:
        # Остаток после полов — в ровный бег (одним блоком; несколько блоков — пропорционально)
        others = sum(v for i, v in new_min.items() if i not in steady)
        rest = math.floor(flex_target - others)
        if rest <= 0:
            return None
        share = sum(mins[i] for i in steady)
        for i in steady:
            new_min[i] = math.floor(rest * mins[i] / share) if share else rest
    if sum(new_min.values()) > flex_target + 1e-6:
        return None
    out = list(segments)
    for i in flex_idx:
        seg = segments[i]
        if new_min[i] <= 0:
            return None
        rep = max(1, seg.repeat)
        per_rep = new_min[i] / rep - _recovery_minutes(seg)
        if per_rep <= 0:
            return None
        if seg.amount_kind == "min":
            out[i] = replace(seg, amount_value=float(per_rep))
        else:
            # км/м: масштабируем объём пропорционально минутам (kind сохраняем)
            lead = segment_minutes(seg, pace_min_km=pace_min_km) or 1.0
            out[i] = replace(seg, amount_value=round(float(seg.amount_value) * per_rep / lead, 2))
    return out


def trim_segments(segments: list[WorkoutSegment], target_min: float, *,
                  pace_min_km: float | None = None) -> TrimResult:
    """Урезать структуру до target_min минут по правилам гайдов (см. шапку модуля).

    Возврат: сегменты (пустой список — структуру честно снимаем), заметка «что урезано», сумма.
    Уже помещается → сегменты как есть. (Trim by the guide rules; [] means structure dropped.)
    """
    segs = list(segments or [])
    if not segs:
        return TrimResult([], None, None)
    notes: list[str] = []
    # 1. Ускорений не больше STRIDES_MAX_PER_SESSION (гайд 46) — независимо от потолка
    for i, seg in enumerate(segs):
        if seg.role == "work" and is_stride(seg) and seg.repeat > STRIDES_MAX_PER_SESSION:
            notes.append(f"ускорения {seg.repeat} → {STRIDES_MAX_PER_SESSION}")
            segs[i] = replace(seg, repeat=STRIDES_MAX_PER_SESSION)
    total = total_minutes(segs, pace_min_km=pace_min_km)
    if total is None:
        # Несчётный сегмент (open/по пульсу) — резать нечем: структуру снимаем
        return TrimResult([], "структура снята: объём сегментов не посчитать", None)
    if total <= target_min + 1e-6:
        return TrimResult(segs, "; ".join(notes) or None, total)

    quality_idx = [i for i, s in enumerate(segs) if s.role == "work" and not is_stride(s)]
    stride_idx = [i for i, s in enumerate(segs) if s.role == "work" and is_stride(s)]

    if quality_idx:
        # 2. Качественная работа: повторы вниз (не ниже минимума), разминка/заминка целы
        before = {i: max(1, segs[i].repeat) for i in quality_idx}
        while total > target_min + 1e-6:
            cands = [i for i in quality_idx if segs[i].repeat > SEGMENT_WORK_REPEAT_MIN]
            if not cands:
                break
            i = max(cands, key=lambda j: segs[j].repeat)
            per_rep = (segment_minutes(segs[i], pace_min_km=pace_min_km) or 0.0) \
                + _recovery_minutes(segs[i])
            segs[i] = replace(segs[i], repeat=segs[i].repeat - 1)
            total -= per_rep
        changed = [f"повторы {before[i]} → {segs[i].repeat}" for i in quality_idx
                   if segs[i].repeat != before[i]]
        notes.extend(changed)
        if total > target_min + 1e-6:
            return TrimResult([], "структура снята: повторы не помещаются в потолок", None)
        return TrimResult(segs, "; ".join(notes) or None, total)

    # 3. Ускорения / блоки с разным пульсом: режем ровную часть, ускорения сохраняем
    fixed = sum(_seg_total(segs[i], pace_min_km=pace_min_km) or 0.0 for i in stride_idx)
    flex_target = target_min - fixed
    flex_before = total - fixed
    if stride_idx and flex_target < PLAN_EASY_MIN_MINUTES:
        return TrimResult([], f"ускорения сняты: ровной части осталось бы меньше "
                              f"{PLAN_EASY_MIN_MINUTES} мин", None)
    scaled = _scale_flex(segs, flex_target, pace_min_km=pace_min_km)
    if scaled is None:
        return TrimResult([], "структура снята: ровная часть не ужимается под потолок", None)
    new_total = total_minutes(scaled, pace_min_km=pace_min_km) or 0.0
    notes.append(f"ровная часть {_fmt(flex_before)} → {_fmt(new_total - fixed)} мин")
    n_strides = sum(max(1, segs[i].repeat) for i in stride_idx)
    if n_strides:
        notes.append(f"{n_strides} ускорений сохранены")
    return TrimResult(scaled, "; ".join(notes), new_total)


def shrink_proposal(proposal: WorkoutProposal, new_min: float, *, trail: str,
                    pace_min_km: float | None = None) -> tuple[WorkoutProposal, str | None]:
    """Урезать предложение до new_min минут: ровное — длительность и дистанция пропорционально;
    структурное — через trim_segments (длительность = сумма урезанных сегментов, чтобы finalize
    её не переписал вверх). Возврат — (копия с code_trimmed=True и следом в rationale, заметка о
    структуре | None). Вход не мутирует. (Shrink a proposal; structured via trim_segments.)"""
    duration = float(proposal.duration_min) if proposal.duration_min else None
    scale = (new_min / duration) if duration and duration > 0 else None
    distance = (round(proposal.distance_km * scale, 1)
                if proposal.distance_km and scale is not None else proposal.distance_km)
    before = total_minutes(proposal.segments, pace_min_km=pace_min_km) if proposal.segments else None
    if not proposal.segments or (before is not None and before <= new_min + 1e-6):
        # Ровное предложение — или структура покрывает лишь часть тренировки (одни ускорения без
        # ровной части, сумма сегментов уже под потолком): режем длительность, сегменты как есть
        return replace(proposal, duration_min=int(new_min), distance_km=distance,
                       rationale=[*proposal.rationale, trail], code_trimmed=True), None
    result = trim_segments(proposal.segments, new_min, pace_min_km=pace_min_km)
    if not result.segments:
        note = f"структура снята ({result.note})" if result.note else "структура снята"
        return replace(proposal, duration_min=int(new_min), distance_km=distance,
                       segments=[], structure=None,
                       rationale=[*proposal.rationale, trail, note], code_trimmed=True), note
    total = result.total_min if result.total_min is not None else new_min
    final_min = int(math.floor(total))
    distance = (round(proposal.distance_km * final_min / duration, 1)
                if proposal.distance_km and duration else proposal.distance_km)
    extra = [result.note] if result.note else []
    return replace(proposal, duration_min=final_min, distance_km=distance,
                   segments=result.segments,
                   rationale=[*proposal.rationale, trail, *extra], code_trimmed=True), result.note
