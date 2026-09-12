# Полевой тест ПАНО (Field LTHR test, M3.2) — решение владельца 12.09.2026.
#
# Coros отдаёт LTHR по своей модели; полевой 30-минутный тест (Friel: ПАНО ≈ средний пульс последних
# 20 минут ровного максимального усилия) — валидация и новый якорь зон. Коуч сам ставит тест первым
# качественным днём, когда статус stable, интенсив открыт и свежего полевого ПАНО нет
# (`is_due` → `week_targets["lthr_test_due"]` → `place_test` в weekly_plan). Результат по треку считает
# `analysis/lthr_test.py`, подтверждение — кнопкой в Telegram (`handlers/lthr.py`), запись — сюда:
# `UserModel.params_json["lthr_field"]` (без миграции), читает `services/repositories.latest_lthr`
# (единственный якорь зон для всех потребителей). Смена якоря → пересчёт тренировок за окно.
# (Field LTHR: deterministic protocol, code-computed number, one-button confirmation, no migration.)

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from src.coach.config import (
    LTHR_FIELD_MAX_AGE_DAYS,
    LTHR_REANALYZE_DAYS,
    LTHR_SANITY_MIN,
    LTHR_TEST_COOLDOWN_MIN,
    LTHR_TEST_WARMUP_MIN,
    LTHR_TEST_WORK_MIN,
    HARD_TYPES,
)
from src.coach.contracts import WorkoutProposal, WorkoutSegment
from src.coach.training_status import PHASE_STABLE
from src.models import TrainingSession, UserModel
from src.services.audit import AuditService
from src.services.repositories import field_lthr
from src.utils.logger import get_logger

logger = get_logger(__name__)

TEST_MARKER = "lthr_test"          # ключ в Recommendation.target_json — «этот день — тест ПАНО»
TEST_EFFORT = "ровно, максимум, который удержишь все 30 мин; без финишного рывка"
TEST_RATIONALE = "Полевой тест ПАНО (гайд 31): 30 мин ровно, ПАНО = средний пульс последних 20 мин"
TEST_TITLE = "🧪 Тест ПАНО"


# ---------- хранение (storage, params_json) ----------

def state(user_id: int, *, db: Session) -> dict:
    """Сохранённая запись полевого ПАНО ({} — нет). (Persisted field-LTHR record.)"""
    um = db.query(UserModel).filter(UserModel.user_id == user_id).first()
    if um is None or not um.params_json:
        return {}
    return dict(um.params_json.get("lthr_field") or {})


def set_field_lthr(user_id: int, value: int, *, db: Session, method: str, now: datetime,
                   session_id: int | None = None, pace_s_km: float | None = None,
                   quality: str | None = None, source: str = "telegram") -> dict:
    """Записать подтверждённый полевой ПАНО (commit + аудит). Валидация значения — у вызывающего.
    (Persist the confirmed value; audit; caller validates the number.)"""
    um = db.query(UserModel).filter(UserModel.user_id == user_id).first()
    if um is None:
        um = UserModel(user_id=user_id, params_json={})
        db.add(um)
    params = dict(um.params_json or {})
    old = (params.get("lthr_field") or {}).get("value")
    rec = {"value": int(value), "measured_at": now.date().isoformat(), "method": method,
           "session_id": session_id, "pace_s_km": pace_s_km, "quality": quality,
           "updated_at": now.isoformat()}
    params["lthr_field"] = rec
    um.params_json = params
    db.commit()
    AuditService(db).log_settings_changed(
        user_id=user_id, changes={"lthr_field": {"old": old, "new": int(value)}},
        source=source, method=method, session_id=session_id)
    logger.info("lthr_field: user=%s ПАНО %s → %d (%s)", user_id, old, value, method)
    return rec


def valid_value(value: int, max_hr: int | None) -> bool:
    """Санити полевого ПАНО: выше LTHR_SANITY_MIN и ниже max_hr (если известен)."""
    if value <= LTHR_SANITY_MIN:
        return False
    return max_hr is None or value < max_hr


def is_due(user_id: int, *, db: Session, phase: str) -> bool:
    """Нужен ли тест: статус stable и нет свежего полевого ПАНО (моложе LTHR_FIELD_MAX_AGE_DAYS)."""
    if phase != PHASE_STABLE:
        return False
    return field_lthr(user_id, db=db, max_age_days=LTHR_FIELD_MAX_AGE_DAYS) is None


# ---------- назначение (plan placement) ----------

def test_proposal(days_ahead: int) -> WorkoutProposal:
    """Детерминированный протокол теста: разминка Z2 → 30 мин ровно Z4 → заминка Z1.
    Тип race: максимальное усилие, HARD_TYPES, 72 ч восстановления, каркас недели (_KEEP_TYPES)."""
    segs = [
        WorkoutSegment(role="warmup", amount_kind="min", amount_value=LTHR_TEST_WARMUP_MIN, target_zone=2),
        WorkoutSegment(role="work", amount_kind="min", amount_value=LTHR_TEST_WORK_MIN, target_zone=4,
                       effort=TEST_EFFORT),
        WorkoutSegment(role="cooldown", amount_kind="min", amount_value=LTHR_TEST_COOLDOWN_MIN, target_zone=1),
    ]
    return WorkoutProposal(
        workout_type="race", target_zone=4,
        duration_min=LTHR_TEST_WARMUP_MIN + LTHR_TEST_WORK_MIN + LTHR_TEST_COOLDOWN_MIN,
        segments=segs, rationale=[TEST_RATIONALE], for_days_ahead=days_ahead)


def place_test(items: list[WorkoutProposal], *, quality_from_day: int | None = None,
               ) -> tuple[list[WorkoutProposal], int | None]:
    """Поставить тест в план: первый качественный элемент (HARD_TYPES) → тест того же дня; нет
    качественных — заменить первый лёгкий день с for_days_ahead ≥ quality_from_day (не длительную).
    Возврат — (items, день теста | None). Чистая функция, входной список не мутирует.
    (Replace the first hard day, else the first eligible easy day; never the long run.)"""
    out = list(items)
    for i, it in enumerate(out):
        if it.workout_type in HARD_TYPES:
            out[i] = test_proposal(it.for_days_ahead)
            return out, it.for_days_ahead
    for i, it in enumerate(out):
        if it.workout_type in ("easy", "recovery") and not it.segments \
                and (quality_from_day is None or it.for_days_ahead >= quality_from_day):
            out[i] = test_proposal(it.for_days_ahead)
            return out, it.for_days_ahead
    return out, None


def mark_test(prescription, proposal: WorkoutProposal):
    """Пометить назначение теста в target (dict) — Prescription создаётся только в clamp, поэтому
    маркер ставим в уже собранный объект, до save_prescription. Тест, урезанный safety до
    нерабочего типа (не race), маркер не получает. (Mark the row; a downgraded test is not a test.)"""
    if proposal.rationale and proposal.rationale[0] == TEST_RATIONALE \
            and prescription.proposal.workout_type == "race":
        prescription.target[TEST_MARKER] = True
    return prescription


def is_test_proposal(proposal: WorkoutProposal | None) -> bool:
    return bool(proposal and proposal.rationale and proposal.rationale[0] == TEST_RATIONALE)


# ---------- пересчёт после смены якоря (re-analysis) ----------

def reanalyze_recent(db: Session, user_id: int, *, days: int = LTHR_REANALYZE_DAYS) -> int:
    """Пересчитать тренировки за окно по новому якорю (изолированные ошибки, как hr_max #237)."""
    from src.services.reanalyze import reanalyze_training
    since = datetime.now(timezone.utc) - timedelta(days=days)
    ids = [s.id for s in db.query(TrainingSession).filter(
        TrainingSession.user_id == user_id, TrainingSession.begin_ts >= since).all()]
    done = 0
    for sid in ids:
        try:
            if reanalyze_training(db, sid, user_id, check_max_hr=False) is not None:
                done += 1
        except Exception:
            logger.warning("lthr_field: пересчёт тренировки %s после смены ПАНО упал — изолировано",
                           sid, exc_info=True)
            db.rollback()
    logger.info("lthr_field: user=%s пересчитано %d/%d тренировок за %d дн", user_id, done, len(ids), days)
    return done


def zone_ceilings_text(max_hr: int, lthr: int) -> str:
    """Строка с потолками Z1–Z4 от нового ПАНО для ответа в чате."""
    from src.analysis.hr_zones import zone_ceiling_hr
    parts = [f"Z{z} до {zone_ceiling_hr(z, max_hr, lthr)}" for z in (1, 2, 3, 4)]
    return " · ".join(parts)


__all__ = ["state", "set_field_lthr", "valid_value", "is_due", "test_proposal", "place_test",
           "mark_test", "is_test_proposal", "reanalyze_recent", "zone_ceilings_text",
           "TEST_MARKER", "TEST_TITLE"]
