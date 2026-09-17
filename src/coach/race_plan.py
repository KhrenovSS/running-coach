# Периодизация к целевому старту и потолок недельного объёма (Race periodization) — #243 ч.1,
# решения владельца 17.09.2026. Чистые функции над календарём стартов (coach/races.py) и числами
# недели: потолок по дистанции (середина литературы, coach/config.py), фаза по неделям до
# ближайшего старта (гайд 60: тейпер 2 недели — 75 % / 55 % пика), «достижимый пик» при нехватке
# недель (+10 %/нед и разгрузки не форсируются — честная фраза в шапке), размещение старта в
# плане кодом (как полевой тест ПАНО). Числа для LLM — факты, не советы.
# (Pure race periodization: ceilings, taper phases, reachable peak, race placement.)

from __future__ import annotations

from dataclasses import replace
from datetime import date
from math import ceil

from src.coach.config import (
    CYCLE_3_1,
    HARD_TYPES,
    LOAD_PROGRESSION,
    PLAN_EASY_MIN_MINUTES,
    RACE_BUILD_GROWTH_SHARE,
    RACE_HORIZON_WEEKS,
    RACE_RATIONALE,
    RACE_TAPER_HARD_DAYS_MAX,
    RACE_TAPER_VOLUME_PCT,
    RACE_TAPER_WEEKS,
    RACE_VOLUME_CEILINGS_KM,
    RACE_VOLUME_DEFAULT_CEILING_KM,
    RACE_VOLUME_HARD_CAP_KM,
    RACE_WEEK_VOLUME_PCT,
)
from src.coach.contracts import WorkoutProposal
from src.coach.lthr_field import TEST_RATIONALE

PHASE_BASE = "base"                 # стартов нет или они за горизонтом — обычная прогрессия под потолком
PHASE_BUILD = "build"               # набор к пику: ≥ 2 недель до старта
PHASE_TAPER = "taper"               # неделя −1: объём 75 % пика, интенсив короткий
PHASE_RACE_WEEK = "race_week"       # неделя старта: 55 % пика (не меньше дистанции), старт — качество
PHASE_MAINTENANCE = "maintenance"   # объём упёрся в потолок — плато, прогресс в качество
PHASE_RU = {PHASE_BASE: "рост", PHASE_BUILD: "набор к старту", PHASE_TAPER: "тейпер",
            PHASE_RACE_WEEK: "неделя старта", PHASE_MAINTENANCE: "на потолке"}

_MESO_LEN = CYCLE_3_1["build_weeks"] + CYCLE_3_1["deload_week"]


def volume_ceiling_km(distance_km: float | None) -> float:
    """Потолок недельного объёма по дистанции цели (корзины RACE_VOLUME_CEILINGS_KM, крыша
    RACE_VOLUME_HARD_CAP_KM); None — без стартов, потолок полумарафона. (Ceiling by race distance.)"""
    if distance_km is None:
        return RACE_VOLUME_DEFAULT_CEILING_KM
    for upper, cap in RACE_VOLUME_CEILINGS_KM:
        if distance_km <= upper:
            return min(cap, RACE_VOLUME_HARD_CAP_KM)
    return min(RACE_VOLUME_CEILINGS_KM[-1][1], RACE_VOLUME_HARD_CAP_KM)


def weeks_to(race_date: date, week_start: date) -> int:
    """Полных недель от понедельника планируемой недели до старта: 0 — старт в эту неделю."""
    return (race_date - week_start).days // 7


def _next_race(active: list[dict], week_start: date) -> dict | None:
    """Ближайший старт не раньше планируемой недели (старты до неё — уже прошли)."""
    ahead = [r for r in active if date.fromisoformat(r["date"]) >= week_start]
    return min(ahead, key=lambda r: r["date"]) if ahead else None


def goal_for_week(active: list[dict], *, week_start: date, prev_km: float,
                  ref_peak_km: float) -> dict:
    """Блок `goal` для week_targets: фаза, потолок и «достижимый пик» к ближайшему старту.

    Потолок (`literature_peak_km`) — максимум по стартам в горизонте RACE_HORIZON_WEEKS (10 км через 6
    недель и марафон через 16 → потолок марафона), без стартов — по умолчанию. `reachable_peak_km` =
    min(потолок, prev_km × (1+10 %)^growth_weeks), growth_weeks = ceil((weeks_to_race − 1) × доля недель
    роста) — неделя −2 считается пиковой (гайд 60), не плоской. Формула режет прогрессию только на
    подходе к потолку; в остальном её ценность — честное число пика в шапке (`peak_capped_by_date`).
    `volume_cap_km`: base/build — достижимый пик; taper — ref_peak × 75 %; race_week — max(ref_peak × 55 %,
    дистанция) — марафон не влезет в 55 %. None — капа нет (нет истории). (Goal block for the week.)"""
    horizon = [r for r in active
               if 0 <= weeks_to(date.fromisoformat(r["date"]), week_start) <= RACE_HORIZON_WEEKS]
    literature = (min(RACE_VOLUME_HARD_CAP_KM, max(volume_ceiling_km(r["distance_km"]) for r in horizon))
                  if horizon else volume_ceiling_km(None))
    goal = {"phase": PHASE_BASE, "next_race": None, "weeks_to_race": None,
            "literature_peak_km": literature, "reachable_peak_km": literature, "peak_km": literature,
            "peak_capped_by_date": False, "ref_peak_km": round(ref_peak_km, 1),
            "volume_cap_km": literature, "hard_days_cap": None}
    nxt = _next_race(active, week_start)
    if nxt is None:
        return goal
    race_date = date.fromisoformat(nxt["date"])
    w = weeks_to(race_date, week_start)
    goal["next_race"] = {"label": nxt.get("label") or "", "date": nxt["date"],
                         "distance_km": nxt["distance_km"]}
    goal["weeks_to_race"] = w
    if w > RACE_HORIZON_WEEKS:
        return goal
    ref = ref_peak_km if ref_peak_km > 0 else prev_km
    if w == 0:
        goal.update(phase=PHASE_RACE_WEEK, hard_days_cap=0,
                    volume_cap_km=(round(max(ref * RACE_WEEK_VOLUME_PCT, float(nxt["distance_km"])), 1)
                                   if ref > 0 else None))
        return goal
    if w < RACE_TAPER_WEEKS:
        goal.update(phase=PHASE_TAPER, hard_days_cap=RACE_TAPER_HARD_DAYS_MAX,
                    volume_cap_km=round(ref * RACE_TAPER_VOLUME_PCT, 1) if ref > 0 else None)
        return goal
    pct = LOAD_PROGRESSION["max_weekly_increase_pct"] / 100.0
    growth_weeks = max(1, ceil((w - 1) * RACE_BUILD_GROWTH_SHARE))
    reachable = literature
    if prev_km > 0:
        reachable = round(min(literature, prev_km * (1 + pct) ** growth_weeks), 1)
    goal.update(phase=PHASE_BUILD, reachable_peak_km=reachable, peak_km=reachable,
                peak_capped_by_date=reachable < literature - 0.5, volume_cap_km=reachable)
    return goal


# ---------- размещение старта в плане (race placement) ----------

def race_proposal(race: dict, days_ahead: int) -> WorkoutProposal:
    """Элемент плана на день старта: тип race (максимальное усилие, HARD_TYPES, каркас недели), цель —
    дистанция старта; минуты не задаём — карточка покажет ≈ по темпу истории, если сможет."""
    label = race.get("label") or ""
    return WorkoutProposal(workout_type="race", target_zone=4, distance_km=float(race["distance_km"]),
                           rationale=[RACE_RATIONALE] + ([label] if label else []),
                           for_days_ahead=days_ahead)


def is_race_proposal(proposal: WorkoutProposal | None) -> bool:
    return bool(proposal and proposal.rationale and proposal.rationale[0] == RACE_RATIONALE)


def _is_test(it: WorkoutProposal) -> bool:
    return bool(it.rationale and it.rationale[0] == TEST_RATIONALE)


def place_race(items: list[WorkoutProposal], *, race: dict, days_ahead: int,
               allowed: list[int]) -> tuple[list[WorkoutProposal], int | None]:
    """Поставить старт в план кодом (образец — lthr_field.place_test): день старта заменяется
    элементом race, чужие race-элементы LLM (кроме теста ПАНО) убираются — один старт на неделю.
    Неделя старта без качества: старт и есть качественный день (hard_days_cap = 0) — темповые/интервалы
    LLM понижаются до лёгких (зона 2, без структуры), накануне — не дольше PLAN_EASY_MIN_MINUTES
    (гайд 48: перед стартом — свежесть). День вне окна (отменён/болезнь) → без изменений и None.
    Чистая функция. (Place the race; the race week carries no other quality; pure.)"""
    if days_ahead not in allowed:
        return list(items), None
    out = [it for it in items
           if it.for_days_ahead != days_ahead and not (it.workout_type == "race" and not _is_test(it))]
    for i, it in enumerate(out):
        if it.workout_type in HARD_TYPES and not _is_test(it):
            eve = it.for_days_ahead == days_ahead - 1
            minutes = (min(it.duration_min or PLAN_EASY_MIN_MINUTES, PLAN_EASY_MIN_MINUTES) if eve
                       else it.duration_min)
            why = "накануне старта — лёгкий день (гайд 48)" if eve else "неделя старта — без качества, старт и есть качественный день"
            out[i] = replace(it, workout_type="easy", target_zone=2, duration_min=minutes,
                             distance_km=None, target_pace_min_km=None, segments=[], structure=None,
                             rationale=[*it.rationale, why])
    out.append(race_proposal(race, days_ahead))
    return sorted(out, key=lambda it: it.for_days_ahead), days_ahead


def header_suffix(goal: dict | None) -> str | None:
    """Хвост шапки карточки недели: фаза подготовки, старт, честный пик. None — нечего добавить."""
    if not goal:
        return None
    nxt = goal.get("next_race") or {}
    label = nxt.get("label") or ""
    when = f"{date.fromisoformat(nxt['date']):%d.%m}" if nxt.get("date") else ""
    tag = " ".join(x for x in (label, when) if x)
    phase = goal.get("phase")
    if phase == PHASE_RACE_WEEK:
        return f"неделя старта ({tag})" if tag else "неделя старта"
    if phase == PHASE_TAPER:
        return f"тейпер · старт {tag}" if tag else "тейпер"
    if phase == PHASE_BUILD:
        out = f"до старта {goal.get('weeks_to_race')} нед" + (f" ({tag})" if tag else "")
        if goal.get("peak_capped_by_date"):
            out += (f" · пик к старту ~{goal['reachable_peak_km']:.0f} км "
                    f"(литература {goal['literature_peak_km']:.0f})")
        return out
    if phase == PHASE_MAINTENANCE:
        return f"объём на потолке ~{goal.get('volume_cap_km') or goal.get('peak_km'):.0f} км — прогресс в качество"
    return None
