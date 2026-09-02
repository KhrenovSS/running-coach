# Скилл боли — ранний датчик (Pain skill — early sensor) — DEV_PLAN §7
# Колено: «дискомфорт первые 400–800 м, к 5 км уходит» — паттерн, который надо
# отличать от боли, которая усиливается. Источники: training_feedback + wellness_reports.

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from src.coach.config import (PAIN_CAUTION_LEVEL, PAIN_FRESH_DAYS,
                              PAIN_PERSIST_DAYS, PAIN_STOP_LEVEL)
from src.coach.contracts import SkillResult
from src.coach.skills.base import unknown_result
from src.models import TrainingFeedback, WellnessReport


def recent_pain_by_day(user_id: int, days: int, *, db: Session) -> dict:
    """Максимальная боль по дням из feedback+wellness (max daily pain, both sources)."""
    since_dt = datetime.now(timezone.utc) - timedelta(days=days)
    by_day: dict = {}
    fb_rows = db.query(TrainingFeedback.created_at, TrainingFeedback.pain_level).filter(
        TrainingFeedback.user_id == user_id,
        TrainingFeedback.created_at >= since_dt,
        TrainingFeedback.pain_level.isnot(None),
    ).all()
    for created_at, level in fb_rows:
        d = created_at.date()
        by_day[d] = max(by_day.get(d, 0), level)
    wr_rows = db.query(WellnessReport.report_date, WellnessReport.pain_level).filter(
        WellnessReport.user_id == user_id,
        WellnessReport.report_date >= since_dt.date(),
        WellnessReport.pain_level.isnot(None),
    ).all()
    for report_date, level in wr_rows:
        by_day[report_date] = max(by_day.get(report_date, 0), level)
    return by_day


def consecutive_pain_days(user_id: int, *, db: Session) -> int:
    """Дней подряд с болью > 0, начиная с последнего дня с данными (consecutive pain days)."""
    by_day = recent_pain_by_day(user_id, days=14, db=db)
    if not by_day:
        return 0
    day = max(by_day)
    streak = 0
    while by_day.get(day, 0) > 0:
        streak += 1
        day -= timedelta(days=1)
    return streak


def evaluate(user_id: int, *, db: Session) -> SkillResult:
    """Боль за последние 14 дней: текущий уровень + длительность серии.

    (Pain over the last 14 days: latest level plus streak length.)
    """
    by_day = recent_pain_by_day(user_id, days=14, db=db)
    if not by_day:
        return unknown_result("pain", "no pain reports")

    latest_day = max(by_day)
    latest = by_day[latest_day]
    streak = consecutive_pain_days(user_id, db=db)

    # Свежесть (фикс 02.09.2026): отметка старше PAIN_FRESH_DAYS не блокирует
    # тренировки (один тап «мешало» держал «Отдых» до 14 дней — вечерний
    # вопрос-сброс гейтится initiative). value=None → правила 8–9 молчат;
    # факт остаётся в message/evidence — LLM спросит, как колено.
    # (Stale pain must not lock training; keep it as LLM context only.)
    age_days = (datetime.now(timezone.utc).date() - latest_day).days
    if age_days > PAIN_FRESH_DAYS:
        return SkillResult(
            key="pain",
            status="ok",
            value=None,
            confidence=0.5,
            message=(f"последняя отметка боли {latest}/10 — {age_days} дн. назад "
                     f"(устарела, не ограничивает; спроси про колено)"),
            evidence=f"days_reported={len(by_day)}; latest={latest_day.isoformat()}; stale=True",
            unit="0-10",
            as_of=latest_day,
        )

    if latest >= PAIN_STOP_LEVEL:
        status = "danger"
    elif latest >= PAIN_CAUTION_LEVEL or streak >= PAIN_PERSIST_DAYS:
        status = "warning"
    else:
        status = "ok"
    return SkillResult(
        key="pain",
        status=status,
        value=latest,
        confidence=0.9,  # прямой самоотчёт пользователя (direct self-report)
        message=f"pain={latest}/10; days_in_row={streak}",
        evidence=f"days_reported={len(by_day)}; latest={latest_day.isoformat()}",
        unit="0-10",
        as_of=latest_day,
    )
