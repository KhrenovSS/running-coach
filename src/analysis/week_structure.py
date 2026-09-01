# M4.1/M4.3 (F5/F6, METRICS_GUIDE §11): структура недели и детренированность.
# (Weekly structure and detraining blocks for the workout review.)
#
# Чистая математика без БД (инвариант D2): история приходит списком кратких строк
# {"date": date, "type": str, "km": float} от workout_insights; каждый блок
# деградирует в {"applicable"/"available": False, reason}.

from __future__ import annotations

from datetime import date
from math import ceil

from src.config.constants import (
    DETRAINING_MIN_DAYS_OFF,
    QUALITY_TEMPO_MIN_LTHR_PCT,
    QUALITY_TEMPO_MIN_MAXHR_PCT,
    DETRAINING_VDOT_PCT_PER_DAY,
    POST_RACE_KM_PER_EASY_DAY,
    QUALITY_MAX_PER_WEEK,
    QUALITY_MIN_GAP_DAYS,
)

QUALITY_TYPES = ("tempo", "interval", "race")


def is_quality_session(ttype: str | None, avg_hr: int | None,
                       max_hr: int | None, lthr: int | None) -> bool:
    """«Качественный день»: interval/race всегда; tempo — только с подтверждением
    интенсивности по пульсу (классификация «tempo» остаточная — ловит умеренные).
    (Quality day: interval/race always; tempo only when avg HR confirms real work.)"""
    if ttype in ("interval", "race"):
        return True
    if ttype != "tempo":
        return False
    if avg_hr is None:
        return True  # незнание = осторожность: считаем качественной
    if lthr:
        return avg_hr >= QUALITY_TEMPO_MIN_LTHR_PCT * lthr
    if max_hr:
        return avg_hr >= QUALITY_TEMPO_MIN_MAXHR_PCT * max_hr
    return True

FLAG_HARD_DAYS_TOO_CLOSE = "hard_days_too_close"
FLAG_POST_RACE_RECOVERY = "post_race_recovery_violated"
FLAG_DETRAINING = "detraining_expected"


def _quality_days(history: list[dict], max_hr: int | None,
                  lthr: int | None) -> list[date]:
    """Уникальные даты качественных дней (unique quality-day dates), по возрастанию."""
    days = {row["date"] for row in history
            if row.get("date") is not None
            and is_quality_session(row.get("type"), row.get("avg_hr"), max_hr, lthr)}
    return sorted(days)


def week_structure(history: list[dict], session_date: date | None,
                   session_type: str | None, *,
                   session_avg_hr: int | None = None,
                   max_hr: int | None = None, lthr: int | None = None) -> dict:
    """M4.1: ≤3 качественных за 7 дней, ≥1 лёгкий день между качественными,
    восстановление после гонки — 1 лёгкий день на каждые 3 км (Дэниелс/Фиц, гайды 41/45).

    history — тренировки за ~15 дней ДО session_date включительно (сама сессия в списке).
    (Weekly structure: quality-day count/spacing and the post-race recovery rule.)
    """
    if session_date is None:
        return {"available": False, "reason": "no_date"}
    quality = [d for d in _quality_days(history, max_hr, lthr) if d <= session_date]
    out: dict = {"available": True}
    flags: list[str] = []

    # Качественные дни за скользящие 7 дней, включая день сессии
    week_quality = [d for d in quality if (session_date - d).days < 7]
    out["quality_days_7d"] = len(week_quality)

    session_is_quality = is_quality_session(session_type, session_avg_hr, max_hr, lthr)
    out["session_is_quality"] = session_is_quality
    if session_is_quality:
        prev_quality = [d for d in quality if d < session_date]
        gap_days = (session_date - prev_quality[-1]).days if prev_quality else None
        out["days_since_prev_quality"] = gap_days
        # «Минимум 1 лёгкий день между качественными» → интервал ≥ QUALITY_MIN_GAP_DAYS
        if ((gap_days is not None and gap_days < QUALITY_MIN_GAP_DAYS)
                or len(week_quality) > QUALITY_MAX_PER_WEEK):
            flags.append(FLAG_HARD_DAYS_TOO_CLOSE)

    # Восстановление после гонки: 1 лёгкий день / POST_RACE_KM_PER_EASY_DAY км
    races = [row for row in history
             if row.get("type") == "race" and row.get("date") is not None
             and row["date"] < session_date]
    if races and session_is_quality:
        race = max(races, key=lambda r: r["date"])
        required = ceil((race.get("km") or 0) / POST_RACE_KM_PER_EASY_DAY)
        elapsed = (session_date - race["date"]).days
        out["post_race"] = {"race_date": race["date"].isoformat(),
                            "race_km": race.get("km"),
                            "required_easy_days": required,
                            "days_elapsed": elapsed}
        if elapsed <= required:
            flags.append(FLAG_POST_RACE_RECOVERY)

    out["flags"] = flags
    return out


def detraining(history: list[dict], session_date: date | None) -> dict:
    """M4.3: пауза перед этой тренировкой. До 5 дней форма не теряется (гайд 46);
    дальше — ожидания вниз (~VDOT-декай), объём возврата ограничивает safety.
    (Detraining: layoff before this session; expectations drop past 5 days off.)"""
    if session_date is None:
        return {"available": False, "reason": "no_date"}
    prev = [row["date"] for row in history
            if row.get("date") is not None and row["date"] < session_date]
    if not prev:
        return {"available": False, "reason": "no_history"}
    days_off = (session_date - max(prev)).days
    flag = days_off >= DETRAINING_MIN_DAYS_OFF
    out = {"available": True, "days_off": days_off, "flag": flag}
    if flag:
        # Ожидаемое падение формы — поправка ожиданий, не приговор
        # (expected fitness drop — adjusts expectations, not a verdict)
        out["expected_vdot_drop_pct"] = round(
            (days_off - (DETRAINING_MIN_DAYS_OFF - 1)) * DETRAINING_VDOT_PCT_PER_DAY, 1)
    return out
