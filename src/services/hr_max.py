# Адаптивный максимальный пульс (Adaptive max HR)
#
# Повышение: пик тренировки (сглаженный медианой) выше профильного User.max_hr →
#   1–2 превышения за месяц — предупреждение в Telegram с кнопкой «обновить сейчас»,
#   ≥ MAX_HR_CONFIRM_COUNT превышений — принудительное обновление + уведомление.
# Снижение: за MAX_HR_LOWER_WINDOW_DAYS в интенсивных тренировках пульс не поднимался
#   близко к профильному максимуму → предложение снизить (только по кнопке, никогда авто).
#
# Владение сессией: принимает db + user_id (не объект User — анти-detached, уроки #236),
# коммитит сам; notify строго ПОСЛЕ commit — telegram_notify читает свою SessionLocal.
# (Session ownership: takes db + user_id, commits itself; notify strictly after commit.)

from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.config import settings as app_settings
from src.config.constants import (
    MAX_HR_CAP, MAX_HR_CONFIRM_COUNT, MAX_HR_CONFIRM_WINDOW_DAYS,
    MAX_HR_LOWER_WINDOW_DAYS, MAX_HR_LOWER_MIN_INTENSE, MAX_HR_LOWER_MARGIN_BPM,
    MAX_HR_SUGGEST_COOLDOWN_DAYS,
)
from src.domain.models import User
from src.domain.models.audit import AuditEvent
from src.domain.models.training import TrainingSession
from src.services.audit import AuditService
from src.services.telegram_notify import telegram_notify
from src.utils.logger import get_logger

logger = get_logger("app")

# Тип аудит-события предложения снизить — кулдаун считается по нему
# (Audit event type for the lowering suggestion — cooldown is derived from it)
MAX_HR_SUGGEST_EVENT = "settings.max_hr_suggest"

MAX_HR_UPDATED_TEXT = (
    "❤️ *Максимальный пульс обновлён: {old} → {new}*\n\n"
    "За последний месяц пульс в {n} разных дней устойчиво достигал {new}+ — "
    "значение в профиле обновлено автоматически. Проверить можно в настройках."
)

MAX_HR_WARNING_TEXT = (
    "⚠️ *Пульс выше максимума в профиле*\n\n"
    "На тренировке зафиксирован устойчивый пульс {peak} (в профиле {profile}). "
    "Пока не меняю — если за месяц это повторится {count}+ раз, обновлю автоматически."
)

MAX_HR_LOWER_TEXT = (
    "💡 *Возможно, ваш максимальный пульс снизился*\n\n"
    "За {days} дней в {n} скоростных тренировках пульс не поднимался выше {observed} "
    "(в профиле {profile}). Автоматически не меняю — только по кнопке."
)


def _confirm_buttons(value: int, keep_label: str = "Игнорировать") -> dict:
    """Inline-кнопки подтверждения смены max_hr (Inline confirm keyboard for max HR change)"""
    return {"inline_keyboard": [
        [{"text": f"Обновить до {value}", "callback_data": f"maxhr:set:{value}"}],
        [{"text": keep_label, "callback_data": "maxhr:ignore"}],
    ]}


def _effective_peak_col():
    """Эффективный пик сессии: сглаженный, для legacy-строк — сырой max
    (Effective session peak: smoothed, falling back to raw max for legacy rows)."""
    return func.coalesce(TrainingSession.hr_peak_smoothed, TrainingSession.max_heart_rate)


def evaluate_max_hr_raise(db: Session, user_id: int, batch_peak: int | None,
                          source: str = "ingest") -> tuple[int, int] | None:
    """
    Проверка после ингеста батча тренировок: пик батча выше профильного max_hr?
    ≥ MAX_HR_CONFIRM_COUNT превышений в РАЗНЫЕ дни за месяц → принудительное обновление
    (возврат (old, new)), иначе — предупреждение с кнопкой; вызывать один раз на батч.
    Никогда не роняет вызывающий код: исключение гасится (rollback + warning) — сбой
    адаптивного max_hr не должен ломать контракт синка «-1 = ошибка» или ронять upload.
    (Post-ingest check: force-update on exceedances across distinct days, warn otherwise;
    never raises — a feature failure must not masquerade as a sync/upload failure.)
    """
    try:
        return _evaluate_max_hr_raise(db, user_id, batch_peak, source)
    except Exception:
        logger.warning("hr_max: evaluate_max_hr_raise упал для user=%s — изолировано (isolated failure)",
                       user_id, exc_info=True)
        db.rollback()
        return None


def _evaluate_max_hr_raise(db: Session, user_id: int, batch_peak: int | None,
                           source: str) -> tuple[int, int] | None:
    if not batch_peak:
        return None
    if batch_peak > MAX_HR_CAP:
        logger.warning("hr_max: user=%s пик %d выше %d — артефакт датчика, игнорируем (sensor artifact)",
                       user_id, batch_peak, MAX_HR_CAP)
        return None

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return None
    profile = user.max_hr or app_settings.default_max_hr
    if batch_peak <= profile:
        return None

    peak_col = _effective_peak_col()
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_HR_CONFIRM_WINDOW_DAYS)
    rows = (db.query(TrainingSession.begin_ts, peak_col)
            .filter(TrainingSession.user_id == user_id,
                    TrainingSession.begin_ts >= cutoff,
                    peak_col > profile,
                    peak_col <= MAX_HR_CAP)
            .all())
    # Считаем превышения по РАЗНЫМ дням: bulk-загрузка истории одним днём не должна
    # форсить обновление без стадии предупреждения (db-safety review 06.08.2026).
    # (Count exceedances across DISTINCT days: a same-day bulk upload must not
    #  skip the warning stage.)
    day_peaks: dict = {}
    for begin_ts, peak in rows:
        day = begin_ts.date()
        day_peaks[day] = max(day_peaks.get(day, 0), peak)

    if len(day_peaks) >= MAX_HR_CONFIRM_COUNT:
        # Значение, до которого пульс реально доходил минимум в N разных дней —
        # N-й по величине дневной пик; устойчиво к одному оставшемуся выбросу.
        # (Value actually reached on ≥N distinct days — the N-th largest daily peak.)
        new_value = sorted(day_peaks.values(), reverse=True)[MAX_HR_CONFIRM_COUNT - 1]
        old_value = profile
        user.max_hr = new_value
        db.commit()
        AuditService(db).log_settings_changed(
            user_id=user_id,
            changes={"max_hr": {"old": old_value, "new": new_value}},
            source="auto_max_hr", trigger=source, exceed_days=len(day_peaks),
        )
        telegram_notify(
            user_id=user_id,
            text=MAX_HR_UPDATED_TEXT.format(old=old_value, new=new_value, n=len(day_peaks)),
        )
        logger.info("hr_max: user=%s max_hr %d → %d (дней с превышением за %dд: %d, source=%s)",
                    user_id, old_value, new_value, MAX_HR_CONFIRM_WINDOW_DAYS,
                    len(day_peaks), source)
        return (old_value, new_value)

    # Первое/второе превышение — только предупредить (First/second exceedance — warn only)
    telegram_notify(
        user_id=user_id,
        text=MAX_HR_WARNING_TEXT.format(peak=batch_peak, profile=profile,
                                        count=MAX_HR_CONFIRM_COUNT),
        reply_markup=_confirm_buttons(batch_peak),
    )
    logger.info("hr_max: user=%s предупреждение — пик %d > профиль %d (дней с превышением за %dд: %d)",
                user_id, batch_peak, profile, MAX_HR_CONFIRM_WINDOW_DAYS, len(day_peaks))
    return None


def evaluate_max_hr_lowering(db: Session, user_id: int) -> int | None:
    """
    Еженедельная проверка: в интенсивных тренировках за окно пульс давно не приближался
    к профильному max_hr → предложить снизить (кнопка; кулдаун по аудит-событию).
    Возвращает предложенное значение или None. Не роняет вызывающий код (см. raise).
    (Weekly check: suggest lowering when intense workouts stay well below profile max HR;
    never raises.)
    """
    try:
        return _evaluate_max_hr_lowering(db, user_id)
    except Exception:
        logger.warning("hr_max: evaluate_max_hr_lowering упал для user=%s — изолировано (isolated failure)",
                       user_id, exc_info=True)
        db.rollback()
        return None


def _evaluate_max_hr_lowering(db: Session, user_id: int) -> int | None:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return None
    profile = user.max_hr or app_settings.default_max_hr

    # Кулдаун: недавнее предложение уже было (Cooldown: a recent suggestion exists)
    cooldown_cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_HR_SUGGEST_COOLDOWN_DAYS)
    recent = (db.query(AuditEvent.id)
              .filter(AuditEvent.user_id == user_id,
                      AuditEvent.event_type == MAX_HR_SUGGEST_EVENT,
                      AuditEvent.created_at >= cooldown_cutoff)
              .first())
    if recent:
        return None

    # Интенсивные тренировки за окно, с учётом ручного override типа
    # (Intense workouts in the window, honoring the manual type override)
    effective_type = func.coalesce(TrainingSession.training_type_override,
                                   TrainingSession.training_type)
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_HR_LOWER_WINDOW_DAYS)
    peak_col = _effective_peak_col()
    peaks = [row[0] for row in (
        db.query(peak_col)
        .filter(TrainingSession.user_id == user_id,
                TrainingSession.begin_ts >= cutoff,
                effective_type.in_(("interval", "tempo")),
                peak_col.isnot(None))
        .all()
    )]
    if len(peaks) < MAX_HR_LOWER_MIN_INTENSE:
        return None

    observed = max(peaks)
    if observed < 100 or observed > profile - MAX_HR_LOWER_MARGIN_BPM:
        return None

    AuditService(db).log_event(
        event_type=MAX_HR_SUGGEST_EVENT,
        message=f"Suggested lowering max_hr {profile} → {observed}",
        severity="info", user_id=user_id,
        metadata={"profile": profile, "observed": observed, "intense_count": len(peaks)},
    )
    telegram_notify(
        user_id=user_id,
        text=MAX_HR_LOWER_TEXT.format(days=MAX_HR_LOWER_WINDOW_DAYS, n=len(peaks),
                                      observed=observed, profile=profile),
        reply_markup=_confirm_buttons(observed, keep_label=f"Оставить {profile}"),
    )
    logger.info("hr_max: user=%s предложено снизить max_hr %d → %d (%d интенсивных за %dд)",
                user_id, profile, observed, len(peaks), MAX_HR_LOWER_WINDOW_DAYS)
    return observed
