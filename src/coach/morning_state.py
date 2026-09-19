# Состояние утреннего вердикта за день (Morning verdict state) — 19.09.2026
#
# Вердикт уходит сразу после распознанного скриншота сна за сегодня; джоба 09:30 —
# резерв для дней без скриншота. Чтобы резерв не продублировал ранний вердикт, факт
# отправки держим в UserModel.params_json["morning_verdict"] (без миграции, паттерн
# coach/illness.py). Поздний скриншот (вердикт уже ушёл БЕЗ сна) → один пересчёт.
#
# Заявка (claim) берётся ДО хода коуча: ход идёт в треде и длится десятки секунд, а
# хендлер фото и джоба 09:30 живут в одном процессе бота. Креш между claim и отправкой
# лечится сроком годности заявки (MORNING_CLAIM_STALE_MIN), а не ручной чисткой.
# (Per-day claim so the 09:30 fallback never duplicates the sleep-triggered verdict.)

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from src.coach.llm.config import (COACH_SLEEP_RECOMPUTE_STOP_HOUR,
                                  MORNING_CLAIM_STALE_MIN)
from src.models import UserModel
from src.utils.logger import get_logger

logger = get_logger("coach.morning_state")

KEY = "morning_verdict"

# Решения для пути «пришёл скриншот сна» (actions for the sleep-screenshot path)
SEND = "send"        # вердикта за сегодня ещё не было — шлём с учётом сна
RESEND = "resend"    # вердикт ушёл без сна — один пересчёт
WAIT = "wait"        # ход уже в полёте (джоба 09:30) — перепроверить позже
SKIP = "skip"        # сон уже учтён / поздно — только запись в БД


def state(user_id: int, *, db: Session) -> dict:
    """Сохранённая пометка за последний день ({} — записей нет). (Persisted record.)"""
    um = db.query(UserModel).filter(UserModel.user_id == user_id).first()
    if um is None or not um.params_json:
        return {}
    return dict(um.params_json.get(KEY) or {})


def _save(user_id: int, data: dict, *, db: Session) -> None:
    um = db.query(UserModel).filter(UserModel.user_id == user_id).first()
    if um is None:
        um = UserModel(user_id=user_id, params_json={})
        db.add(um)
    params = dict(um.params_json or {})   # копия целиком: иначе SQLAlchemy не увидит мутацию JSON
    params[KEY] = data
    um.params_json = params
    db.commit()


def _fresh_claim(st: dict, *, day: date, now: datetime, stale_min: int) -> bool:
    """Заявка на этот день ещё в работе: отправки не было и срок годности не вышел."""
    if st.get("date") != day.isoformat() or st.get("sent_at"):
        return False
    claimed = st.get("claimed_at")
    if not claimed:
        return False
    try:
        when = datetime.fromisoformat(claimed)
    except ValueError:
        return False
    return now - when < timedelta(minutes=stale_min)


def plan_action(st: dict, *, day: date, now: datetime,
                stop_hour: int = COACH_SLEEP_RECOMPUTE_STOP_HOUR,
                stale_min: int = MORNING_CLAIM_STALE_MIN) -> str:
    """Что делать со скриншотом сна за `day` — чистая функция (pure decision).

    Порядок важен: сначала «ход в полёте» (иначе перепроверка превратится в дубль),
    потом стоп-час (скрин в 23:00 не должен выстрелить «утренним» вердиктом ночью).
    """
    if _fresh_claim(st, day=day, now=now, stale_min=stale_min):
        return WAIT
    if now.hour >= stop_hour:
        return SKIP
    if st.get("date") != day.isoformat():
        return SEND                       # вердикта за сегодня не было (ранний путь/рестарт)
    if not st.get("sent_at"):
        return SEND                       # протухшая заявка: ход умер, не доставив вердикт
    return SKIP if st.get("with_sleep") else RESEND


def claim(user_id: int, *, db: Session, day: date, with_sleep: bool,
          now: datetime, stale_min: int = MORNING_CLAIM_STALE_MIN) -> bool:
    """Занять день под отправку: False — вердикт уже отправлен или ход в полёте.

    Пересчёт со сном (with_sleep=True поверх отправленного without) заявку получает —
    это второе, осознанное сообщение дня. (Claim the day before the coach turn.)
    """
    st = state(user_id, db=db)
    if _fresh_claim(st, day=day, now=now, stale_min=stale_min):
        return False
    if st.get("date") == day.isoformat() and st.get("sent_at"):
        if not with_sleep or st.get("with_sleep"):
            return False                  # повтора без новых данных не бывает
    _save(user_id, {"date": day.isoformat(), "with_sleep": bool(with_sleep),
                    "claimed_at": now.isoformat(), "sent_at": None,
                    "prev_sent_at": st.get("sent_at") if st.get("date") == day.isoformat()
                    else None}, db=db)
    return True


def mark_sent(user_id: int, *, db: Session, day: date, with_sleep: bool,
              now: datetime) -> None:
    """Отметить вердикт доставленным (verdict delivered)."""
    _save(user_id, {"date": day.isoformat(), "with_sleep": bool(with_sleep),
                    "sent_at": now.isoformat(), "claimed_at": None}, db=db)


def release(user_id: int, *, db: Session, day: date) -> None:
    """Снять заявку, если вердикт так и не ушёл (ход упал, инициатива off).

    Отправленную пометку не трогаем: её мог поставить предыдущий (успешный) путь дня.
    (Release the claim; a delivered verdict record stays.)
    """
    st = state(user_id, db=db)
    if st.get("date") != day.isoformat() or st.get("sent_at"):
        return
    prev = st.get("prev_sent_at")
    if prev:
        # Пересчёт со сном не доехал — возвращаем состояние «вердикт без сна отправлен»
        _save(user_id, {"date": day.isoformat(), "with_sleep": False, "sent_at": prev,
                        "claimed_at": None}, db=db)
    else:
        _save(user_id, {}, db=db)
