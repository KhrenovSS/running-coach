# Актуальные проблемы подопечного (решение владельца 10.09.2026): травма/боль («подвернул ногу»),
# долгий перерыв и т.п. LLM только сообщает факт (CoachTurn.concern: new/ongoing/resolved), код
# ведёт даты в UserModel.params_json["concerns"] (без миграции) и снимает проблему с контроля,
# когда CONCERN_EXPIRE_DAYS подряд нет ни боли > 0 (тапы), ни упоминаний в чате. Пока проблема
# активна — она в контексте LLM (блок concerns), в вечернем вопросе и в подписи кнопок боли;
# нет активных — коуч о старых болячках не спрашивает. Болезнь — отдельно (illness.py).
# (Active concerns: LLM reports, code keeps dates and auto-expires; the knee is no longer hardcoded.)

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from src.coach.config import (CONCERN_EXPIRE_DAYS, CONCERN_HISTORY_MAX,
                              PAIN_LOCATION_UNSPECIFIED)
from src.coach.skills.pain import recent_pain_by_day
from src.models import TrainingFeedback, User, UserModel, WellnessReport
from src.utils.logger import get_logger
from src.utils.timeutils import user_now

logger = get_logger(__name__)

LOCATION_RU = {"knee": "колено", "ankle": "голеностоп", "foot": "стопа", "shin": "голень",
               "calf": "икра", "achilles": "ахилл", "hamstring": "задняя поверхность бедра",
               "hip": "тазобедренный сустав/пах", "back": "спина", "other": "другое место",
               PAIN_LOCATION_UNSPECIFIED: "дискомфорт"}
KIND_RU = {"injury": "травма/боль", "long_break": "долгий перерыв", "other": "проблема"}
EVENING_FEEDBACK_WINDOW_H = 20   # боль из feedback за это окно гасит вечерний вопрос
PAIN_TAP_LABEL = "дискомфорт по кнопке"


# ---------- хранение (storage) ----------

def concerns_state(user_id: int, *, db: Session) -> list[dict]:
    """Сохранённый список проблем ([] — записей нет). (Persisted concern records.)"""
    um = db.query(UserModel).filter(UserModel.user_id == user_id).first()
    if um is None or not um.params_json:
        return []
    return [dict(c) for c in (um.params_json.get("concerns") or [])]


def _save(user_id: int, items: list[dict], *, db: Session) -> None:
    """Запись через db-bound UserModel новым dict — иначе JSON-колонка не увидит изменения."""
    um = db.query(UserModel).filter(UserModel.user_id == user_id).first()
    if um is None:
        um = UserModel(user_id=user_id, params_json={})
        db.add(um)
    params = dict(um.params_json or {})
    params["concerns"] = _compact(items)
    um.params_json = params
    db.commit()


def _compact(items: list[dict]) -> list[dict]:
    """Не больше CONCERN_HISTORY_MAX записей: активные всегда остаются, старая история уходит."""
    active = [c for c in items if c.get("status") == "active"]
    history = [c for c in items if c.get("status") != "active"]
    keep = max(CONCERN_HISTORY_MAX - len(active), 0)
    return active + (history[-keep:] if keep else [])


def _next_id(items: list[dict]) -> str:
    nums = [int(c["id"][1:]) for c in items if str(c.get("id", "")).startswith("c")
            and str(c["id"])[1:].isdigit()]
    return f"c{(max(nums) + 1) if nums else 1}"


# ---------- активность и протухание (activity & expiry, pure) ----------

def _last_signal(entry: dict, pain_days: dict) -> date | None:
    """Последний сигнал проблемы: создание, упоминание, жалоба, боль > 0 в БД (для травм)."""
    dates = [date.fromisoformat(entry[k]) for k in ("since", "last_mentioned", "last_complaint")
             if entry.get(k)]
    if entry.get("kind") == "injury" and entry.get("since"):
        since = date.fromisoformat(entry["since"])
        dates += [d for d, lvl in pain_days.items() if lvl > 0 and d >= since]
    return max(dates) if dates else None


def is_active(entry: dict, today: date, pain_days: dict) -> bool:
    """Активна, если статус active и последний сигнал моложе CONCERN_EXPIRE_DAYS."""
    if entry.get("status") != "active":
        return False
    last = _last_signal(entry, pain_days)
    return last is not None and (today - last).days < CONCERN_EXPIRE_DAYS


def expire(items: list[dict], today: date, pain_days: dict) -> list[dict]:
    """Материализовать протухание: active без сигналов → expired (pure)."""
    out = []
    for c in items:
        c = dict(c)
        if c.get("status") == "active" and not is_active(c, today, pain_days):
            c["status"] = "expired"
            c["resolved_at"] = today.isoformat()
        out.append(c)
    return out


def _pain_days(user_id: int, *, db: Session) -> dict:
    return recent_pain_by_day(user_id, days=CONCERN_EXPIRE_DAYS + 1, db=db)


def active_concerns(user_id: int, *, db: Session, today: date) -> list[dict]:
    """Актуальные проблемы на сегодня (read-only, протухание считается на лету)."""
    items = concerns_state(user_id, db=db)
    if not items:
        return []
    pain_days = _pain_days(user_id, db=db)
    return [c for c in items if is_active(c, today, pain_days)]


def _matches(entry: dict, kind: str, location: str | None) -> bool:
    if entry.get("kind") != kind:
        return False
    if kind != "injury" or not location or not entry.get("location"):
        return True
    return (entry["location"] == location
            or PAIN_LOCATION_UNSPECIFIED in (entry["location"], location))


def _label_ru(entry: dict) -> str:
    """Человекочитаемое имя проблемы для подтверждений и вопросов."""
    label = entry.get("label")
    if entry.get("kind") == "injury":
        loc = LOCATION_RU.get(entry.get("location") or PAIN_LOCATION_UNSPECIFIED, "дискомфорт")
        return f"{loc} — {label}" if label and label != PAIN_TAP_LABEL else loc
    return label or KIND_RU.get(entry.get("kind"), "проблема")


# ---------- запись (writes) ----------

def record_concern(report, user_id: int, *, db: Session, now: datetime) -> str:
    """Применить сообщение LLM (ConcernReport) и вернуть детерминированную строку ответа.

    new → новая запись (та же проблема уже активна — обновляем упоминание);
    ongoing → обновить last_mentioned активной (нет активной — создать);
    resolved → снять с контроля. Сроки называет код, не проза LLM.
    (Apply the LLM's concern report; code owns the dates.)
    """
    today = now.date()
    kind = report.kind or "injury"
    location = report.location if kind == "injury" else None
    items = expire(concerns_state(user_id, db=db), today, _pain_days(user_id, db=db))
    match = next((c for c in items if c.get("status") == "active" and _matches(c, kind, location)),
                 None)

    if report.status == "resolved":
        if match is None:
            return "Понял — на контроле ничего похожего нет."
        match["status"] = "resolved"
        match["resolved_at"] = today.isoformat()
        match["updated_at"] = now.isoformat()
        _save(user_id, items, db=db)
        logger.info("Concern resolved user=%s: %s", user_id, match.get("id"))
        return f"Снял с контроля: {_label_ru(match)}. Если вернётся — скажи."

    if match is not None:
        match["last_mentioned"] = today.isoformat()
        match["updated_at"] = now.isoformat()
        if location and match.get("location") in (None, PAIN_LOCATION_UNSPECIFIED):
            match["location"] = location
        if report.label and (not match.get("label") or match["label"] == PAIN_TAP_LABEL):
            match["label"] = report.label
        _save(user_id, items, db=db)
        return f"Учёл: {_label_ru(match)} — всё ещё на контроле."

    since = today - timedelta(days=int(report.days_ago or 0))
    entry = {"id": _next_id(items), "kind": kind,
             "location": (location or PAIN_LOCATION_UNSPECIFIED) if kind == "injury" else None,
             "label": report.label, "status": "active",
             "since": since.isoformat(), "last_mentioned": today.isoformat(),
             "last_complaint": None, "source": "chat", "resolved_at": None,
             "updated_at": now.isoformat()}
    items.append(entry)
    _save(user_id, items, db=db)
    logger.info("Concern recorded user=%s: %s %s", user_id, kind, entry["location"])
    return (f"Запомнил: {_label_ru(entry)}. Буду спрашивать, пока беспокоит; "
            f"без жалоб {CONCERN_EXPIRE_DAYS} дней сниму с контроля.")


def refresh_from_pain(user_id: int, level: int, *, db: Session, today: date,
                      location: str | None = None) -> None:
    """Тап боли > 0: продлить активную травму (или завести новую по кнопке); 0 — ничего."""
    if level <= 0:
        return
    items = expire(concerns_state(user_id, db=db), today, _pain_days(user_id, db=db))
    match = next((c for c in items if c.get("status") == "active" and c.get("kind") == "injury"),
                 None)
    if match is not None:
        match["last_complaint"] = today.isoformat()
        if location and match.get("location") in (None, PAIN_LOCATION_UNSPECIFIED):
            match["location"] = location
    else:
        items.append({"id": _next_id(items), "kind": "injury",
                      "location": location or PAIN_LOCATION_UNSPECIFIED,
                      "label": PAIN_TAP_LABEL, "status": "active",
                      "since": today.isoformat(), "last_mentioned": None,
                      "last_complaint": today.isoformat(), "source": "pain_tap",
                      "resolved_at": None, "updated_at": today.isoformat()})
    _save(user_id, items, db=db)


def resolve(user_id: int, *, db: Session, today: date, kind: str | None = None,
            location: str | None = None) -> bool:
    """Снять с контроля подходящие активные проблемы; True — что-то снято."""
    items = concerns_state(user_id, db=db)
    hit = False
    for c in items:
        if c.get("status") == "active" and (kind is None or _matches(c, kind, location)):
            c["status"], c["resolved_at"], hit = "resolved", today.isoformat(), True
    if hit:
        _save(user_id, items, db=db)
    return hit


# ---------- представления (views) ----------

def primary_location(user_id: int, *, db: Session, today: date) -> str | None:
    """Локализация первой активной травмы (для pain_location тапа) или None."""
    for c in active_concerns(user_id, db=db, today=today):
        if c.get("kind") == "injury" and c.get("location") != PAIN_LOCATION_UNSPECIFIED:
            return c.get("location")
    return None


def context_block(active: list[dict], today: date) -> list[dict] | None:
    """Блок для контекста LLM: что система держит на контроле (None — ничего)."""
    if not active:
        return None
    out = []
    for c in active:
        since = date.fromisoformat(c["since"])
        last = c.get("last_complaint")
        last_signal = _last_signal(c, {}) or since
        out.append({"kind": c.get("kind"), "label": c.get("label"), "location": c.get("location"),
                    "days_since": (today - since).days,
                    "days_since_last_complaint": ((today - date.fromisoformat(last)).days
                                                  if last else None),
                    "expires_in_days": max(CONCERN_EXPIRE_DAYS - (today - last_signal).days, 0)})
    return out


def evening_question(active: list[dict]) -> str:
    """Текст вечернего вопроса по первой активной проблеме."""
    c = active[0]
    if c.get("kind") == "injury":
        loc = LOCATION_RU.get(c.get("location") or PAIN_LOCATION_UNSPECIFIED, "дискомфорт")
        return f"🌙 Как самочувствие? {loc[0].upper() + loc[1:]} сегодня?"
    return f"🌙 Как самочувствие? {_label_ru(c)} — как сегодня?"


def pain_prompt_label(user_id: int, *, db: Session, today: date) -> str:
    """Подпись строки боли после RPE: «Колено?» при активной травме, иначе нейтрально."""
    loc = primary_location(user_id, db=db, today=today)
    if loc:
        name = LOCATION_RU.get(loc, "дискомфорт")
        return f"{name[0].upper() + name[1:]}?"
    return "Боль или дискомфорт?"


def evening_check_needed(user_id: int, *, db: Session) -> bool:
    """Нужен ли вечерний вопрос: только при активной проблеме и если боль за сегодня не записана.

    (Evening question only while a concern is active and today's pain is not yet recorded.)
    Перенесено из orchestrator.py (лимит строк) + гейт по concerns (решение владельца 10.09.2026).
    """
    user = db.query(User).filter(User.id == user_id).first()
    today = user_now(user).date()
    if not active_concerns(user_id, db=db, today=today):
        return False
    wellness = db.query(WellnessReport).filter(
        WellnessReport.user_id == user_id,
        WellnessReport.report_date == today,
        WellnessReport.pain_level.isnot(None),
    ).first()
    if wellness is not None:
        return False
    since = datetime.now(timezone.utc) - timedelta(hours=EVENING_FEEDBACK_WINDOW_H)
    fb = db.query(TrainingFeedback).filter(
        TrainingFeedback.user_id == user_id,
        TrainingFeedback.created_at >= since,
        TrainingFeedback.pain_level.isnot(None),
    ).first()
    return fb is None
