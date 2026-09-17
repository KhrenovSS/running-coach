# Календарь целевых стартов (Race calendar) — #243 ч.1, решения владельца 17.09.2026.
#
# Старты задаются в чате: LLM сообщает факт (CoachTurn.races — дата, дистанция, метка, add|cancel),
# код валидирует, пишет UserModel.params_json["races"] (top-level, без миграции; merge-паттерн как
# coach/illness.py) и отвечает детерминированной строкой. Стартов несколько; после даты запись гаснет
# сама (lazy `done` — только при записи: week_targets остаётся без побочных эффектов). Периодизация
# и потолок объёма — coach/race_plan.py; сроки и фазы LLM не считает.
# (Race calendar in params_json; the LLM reports facts, code owns dates and replies.)

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from src.coach.config import (
    RACE_DISTANCE_MAX_KM,
    RACE_DISTANCE_MIN_KM,
    RACE_MAX_WEEKS_AHEAD,
    RACES_HISTORY_MAX,
)
from src.coach.race_plan import volume_ceiling_km
from src.models import UserModel
from src.utils.logger import get_logger

logger = get_logger(__name__)

STATUS_ACTIVE, STATUS_CANCELLED, STATUS_DONE = "active", "cancelled", "done"
RACE_MARKER = "race"    # ключ Recommendation.target_json — «этот день — старт из календаря»
# Ярлыки стандартных дистанций (допуск ±0.3 км) — «полумарафон», не «21.1 км»
_DISTANCE_LABELS = ((5.0, "5 км"), (10.0, "10 км"), (21.1, "полумарафон"), (42.2, "марафон"))


def distance_label(km: float) -> str:
    for std, label in _DISTANCE_LABELS:
        if abs(km - std) <= 0.3:
            return label
    return f"{km:g} км"


# ---------- хранение (storage) ----------

def races_state(user_id: int, *, db: Session) -> list[dict]:
    """Все записи календаря ([] — нет). (All persisted race records.)"""
    um = db.query(UserModel).filter(UserModel.user_id == user_id).first()
    if um is None or not um.params_json:
        return []
    return [dict(r) for r in (um.params_json.get("races") or [])]


def _save(user_id: int, items: list[dict], *, db: Session) -> None:
    um = db.query(UserModel).filter(UserModel.user_id == user_id).first()
    if um is None:
        um = UserModel(user_id=user_id, params_json={})
        db.add(um)
    params = dict(um.params_json or {})
    params["races"] = _compact(items)
    um.params_json = params
    db.commit()


def _compact(items: list[dict]) -> list[dict]:
    """Активные — все; закрытых (done/cancelled) храним не больше RACES_HISTORY_MAX свежих."""
    active = [r for r in items if r.get("status") == STATUS_ACTIVE]
    closed = sorted((r for r in items if r.get("status") != STATUS_ACTIVE), key=lambda r: r["date"])
    return sorted(active + closed[-RACES_HISTORY_MAX:], key=lambda r: r["date"])


def expire(items: list[dict], today: date) -> tuple[list[dict], bool]:
    """Активные старты с прошедшей датой → done (pure). Возврат (items, были ли изменения)."""
    out, changed = [], False
    for r in items:
        if r.get("status") == STATUS_ACTIVE and date.fromisoformat(r["date"]) < today:
            r = {**r, "status": STATUS_DONE}
            changed = True
        out.append(r)
    return out, changed


def active_races(user_id: int, *, db: Session, today: date) -> list[dict]:
    """Актуальные старты (active, дата ≥ сегодня) по дате — read-only, без побочных эффектов."""
    return sorted((r for r in races_state(user_id, db=db)
                   if r.get("status") == STATUS_ACTIVE and date.fromisoformat(r["date"]) >= today),
                  key=lambda r: r["date"])


# ---------- чат: факт от LLM → запись кодом (chat facts) ----------

def resolve_race_date(report, today: date) -> date:
    """Дата старта из отчёта LLM: ровно одно из `date` («ГГГГ-ММ-ДД» как есть; «ММ-ДД» — ближайшее
    будущее вхождение) или `days_ahead` от сегодня. Прошлое и дальше RACE_MAX_WEEKS_AHEAD — ValueError
    с текстом для подопечного. (Resolve the race date; code, not the LLM, owns the year.)"""
    raw, ahead = getattr(report, "date", None), getattr(report, "days_ahead", None)
    if raw and ahead is not None:
        raise ValueError("Дата старта названа дважды — уточни одну.")
    if ahead is not None:
        d = today + timedelta(days=int(ahead))
    elif raw:
        try:
            if len(raw) == 10:
                d = date.fromisoformat(raw)
            else:
                month, day = (int(x) for x in raw.split("-"))
                d = date(today.year, month, day)
                if d < today:
                    d = date(today.year + 1, month, day)
        except ValueError:
            raise ValueError("Не разобрал дату старта — назови день и месяц.") from None
    else:
        raise ValueError("Не понял дату старта — назови день и месяц.")
    if d < today:
        raise ValueError(f"Дата {d:%d.%m.%Y} уже прошла — назови год или ближайшую дату.")
    if d > today + timedelta(weeks=RACE_MAX_WEEKS_AHEAD):
        raise ValueError(f"Старт {d:%d.%m.%Y} дальше года — запишу, когда будет ближе.")
    return d


def _describe(r: dict) -> str:
    label = r.get("label") or distance_label(float(r["distance_km"]))
    return f"{date.fromisoformat(r['date']):%d.%m} · {label} ({float(r['distance_km']):g} км)"


def _match_cancel(active: list[dict], report, today: date) -> list[dict]:
    """Кандидаты на отмену: сужаем по метке, дате, дистанции — каждый фильтр только если он что-то оставил."""
    found = list(active)
    label = (getattr(report, "label", None) or "").strip().lower()
    if label:
        by_label = [r for r in found if label in (r.get("label") or "").lower()
                    or label in distance_label(float(r["distance_km"])).lower()]
        found = by_label or found
    if getattr(report, "date", None) or getattr(report, "days_ahead", None) is not None:
        try:
            d = resolve_race_date(report, today).isoformat()
            found = [r for r in found if r["date"] == d] or found
        except ValueError:
            pass
    km = getattr(report, "distance_km", None)
    if km is not None:
        found = [r for r in found if abs(float(r["distance_km"]) - float(km)) <= 0.5] or found
    return found


def record_race(report, user_id: int, *, db: Session, now: datetime) -> str:
    """Применить отчёт LLM о старте и вернуть детерминированную строку ответа.

    add — валидация даты/дистанции, дубль по дате обновляется; ответ называет недели до старта и
    ориентир пика (race_plan.volume_ceiling_km). cancel — один однозначный кандидат гасится, иначе
    перечисляем. Здесь же материализуется expire (прошедшие → done). (Apply the report; code replies.)"""
    today = now.date()
    items, _ = expire(races_state(user_id, db=db), today)
    active = [r for r in items if r.get("status") == STATUS_ACTIVE]
    if report.status == "cancel":
        found = _match_cancel(active, report, today)
        if not active:
            _save(user_id, items, db=db)
            return "В календаре стартов пусто — снимать нечего."
        if len(found) != 1:
            _save(user_id, items, db=db)
            return "Уточни, какой старт снять: " + "; ".join(_describe(r) for r in found) + "."
        target = found[0]
        for r in items:
            if r.get("id") == target["id"]:
                r["status"] = STATUS_CANCELLED
                r["updated_at"] = now.isoformat()
        _save(user_id, items, db=db)
        logger.info("Race cancelled user=%s: %s", user_id, _describe(target))
        return f"Снял старт {_describe(target)} из календаря. План пересоберу по /plan."
    km = getattr(report, "distance_km", None)
    if km is None:
        return "На какой дистанции старт? Запишу его в календарь, как только назовёшь."
    if not RACE_DISTANCE_MIN_KM <= float(km) <= RACE_DISTANCE_MAX_KM:
        return f"Дистанция {float(km):g} км вне диапазона {RACE_DISTANCE_MIN_KM:g}–{RACE_DISTANCE_MAX_KM:g} км — уточни."
    try:
        d = resolve_race_date(report, today)
    except ValueError as e:
        return str(e)
    label = (getattr(report, "label", None) or "").strip() or distance_label(float(km))
    existing = next((r for r in active if r["date"] == d.isoformat()), None)
    if existing is not None:
        existing.update(distance_km=float(km), label=label, updated_at=now.isoformat())
        rec = existing
    else:
        rec = {"id": max([r.get("id", 0) for r in items] or [0]) + 1, "date": d.isoformat(),
               "distance_km": float(km), "label": label, "status": STATUS_ACTIVE,
               "created_at": now.isoformat()}
        items.append(rec)
    _save(user_id, items, db=db)
    weeks = (d - today).days // 7
    logger.info("Race recorded user=%s: %s (%s weeks)", user_id, _describe(rec), weeks)
    head = f"Записал старт: {_describe(rec)}"
    if weeks == 0:
        return head + " — уже на этой неделе: план под старт пересоберу по /plan (короткие лёгкие дни, свежие ноги)."
    if weeks == 1:
        return head + " — через неделю: тейпер, объём снижу, интенсив короткий. План пересоберу по /plan."
    return (head + f" — до него {weeks} нед, ориентир пика ~{volume_ceiling_km(float(km)):.0f} км/нед. "
            "План недели пересоберу по /plan.")


# ---------- контекст и маркеры (context & markers) ----------

def context_block(active: list[dict], today: date) -> list[dict] | None:
    """Блок `races (params)` для today-контекста LLM (None — стартов нет). Только факты."""
    if not active:
        return None
    return [{"label": r.get("label") or distance_label(float(r["distance_km"])), "date": r["date"],
             "distance_km": r["distance_km"],
             "days_ahead": (date.fromisoformat(r["date"]) - today).days,
             "weeks_ahead": (date.fromisoformat(r["date"]) - today).days // 7} for r in active]


def mark_race(prescription, proposal, race: dict | None):
    """Пометить назначение дня старта в target (Prescription рождается только в clamp — маркер ставим
    в собранный объект до save_prescription). Маркер ставится и на понижённый safety тип: карточка
    честно скажет «старт в лёгком режиме» (#243 п.4). (Mark the race row, even if downgraded.)"""
    from src.coach.race_plan import is_race_proposal
    if race and is_race_proposal(proposal):
        prescription.target[RACE_MARKER] = {"id": race.get("id"), "label": race.get("label") or "",
                                            "distance_km": race.get("distance_km")}
    return prescription
