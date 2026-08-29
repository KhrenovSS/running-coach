# Контекст LLM-хода: обогащение today-блока и дедуп назначений (turn context) —
# вынесено из orchestrator.py (BACKLOG #266, лимит ~400 строк/файл).
# (Extracted from orchestrator.py: today-block enrichment + prescription dedup.)

from __future__ import annotations

from sqlalchemy.orm import Session

from src.coach.contracts import Prescription
from src.coach.knowledge.loader import review_guides_queries
from src.coach.knowledge.loader import search as guide_search
from src.coach.llm.config import (
    COACH_ENRICH_RECENT_LIMIT,
    COACH_ENRICH_WEEKS,
    COACH_PLANNED_DAYS,
    COACH_RECENT_REVIEWS_LIMIT,
)
from src.coach.tools.registry import run_tool
from src.models import Recommendation, User
from src.utils.timeutils import WEEKDAYS_RU, local_dt, user_now


def build_extras(user_id: int, *, db: Session,
                 weeks: int = COACH_ENRICH_WEEKS,
                 limit: int = COACH_ENRICH_RECENT_LIMIT,
                 session_id: int | None = None,
                 insights_limit: int = COACH_RECENT_REVIEWS_LIMIT,
                 guides_query: str | None = None) -> dict:
    """Обогащение today-блока: меньше tool round-trip'ов в API-режиме; в режиме
    моста tool-цикл неактивен — это его основной источник фактов (enrichment).

    session_id — добавить детали конкретной тренировки (для разбора, C8).
    D7: итоги последних разборов (carry_forward → утренний вердикт) и
    действующее назначение — каналы влияния разбора на будущее.
    """
    from src.services.repositories_insights import InsightRepository

    # Все даты блока — по локальному «сегодня» пользователя (#262/#267)
    user = db.query(User).filter(User.id == user_id).first()
    today_local = user_now(user).date()
    extras = {
        "recent_workouts (get_recent_workouts)": run_tool(
            "get_recent_workouts", {"limit": limit}, user_id=user_id, db=db),
        "weekly_summary (get_weekly_summary)": run_tool(
            "get_weekly_summary", {"weeks": weeks}, user_id=user_id, db=db),
    }
    reviews = InsightRepository.recent(user_id, db=db, days=7, limit=insights_limit)
    if reviews:
        # days_ago — по локальной паре дат пользователя, как в _session_brief
        # (user-local dates on both sides, consistent with _session_brief)
        extras["recent_reviews (workout_insights)"] = [{
            "days_ago": ((today_local - local_dt(r.created_at, user).date()).days
                         if r.created_at else None),
            "session_id": r.session_id,
            "effort_match": r.effort_match,
            "flags": (r.assessment_json or {}).get("flags"),
            "carry_forward": r.carry_forward,
        } for r in reviews]
    recs = db.query(Recommendation).filter(
        Recommendation.user_id == user_id,
        Recommendation.for_date >= today_local,
    ).order_by(Recommendation.id.asc()).all()
    if recs:
        # Действующие назначения по дням: наутро модель видит, что уже назначала
        # (митигация конфликта «карточка разбора vs утренний вердикт», D7).
        # Последняя строка на каждую дату (id.asc → перезапись поздней), список —
        # чтобы пятничное и воскресное назначения не затеняли друг друга.
        # days_ahead — сдвиг от локального «сегодня» пользователя, симметрично
        # days_ago тренировок. (Latest row per date; days_ahead mirrors days_ago.)
        latest_by_date = {r.for_date: r for r in recs}
        extras["planned_workouts (recommendations)"] = [{
            "for_date": r.for_date.isoformat(),
            "weekday": WEEKDAYS_RU[r.for_date.weekday()],
            "days_ahead": (r.for_date - today_local).days,
            "type": r.workout_type,
            "status": r.status,
            "source": r.source, "clamped": r.clamped,
            "target": r.target_json, "volume": r.volume_json,
        } for r in sorted(latest_by_date.values(),
                          key=lambda r: r.for_date)[:COACH_PLANNED_DAYS]]
    if session_id is not None:
        detail = run_tool(
            "get_workout_detail", {"session_id": session_id}, user_id=user_id, db=db)
        extras["workout_detail (get_workout_detail)"] = detail
        # D4: детерминированные физио-метрики (drift/GAP/baseline/heat) — в контекст
        # разбора; lazy-пересчёт покрывает старые тренировки (computed metrics).
        from src.services.workout_insights import get_or_compute
        computed = get_or_compute(user_id, session_id, db=db)
        if computed is not None:
            extras["workout_computed (workout_insights)"] = computed
        # E3 (#242): в мосте search_guides простаивает — чанки методики инлайном
        # (bridge mode: inline the methodology chunks the tool would have fetched)
        if guides_query is None:
            queries = review_guides_queries(detail, computed)
        else:
            queries = [guides_query]
    else:
        queries = [guides_query] if guides_query else []
    chunks: list = []
    seen: set[tuple[str, str]] = set()
    for q in queries:
        # по одному лучшему чанку на запрос — боль не вытесняется типом тренировки
        for c in guide_search(q, top_k=1):
            if (c.guide, c.heading) not in seen:
                seen.add((c.guide, c.heading))
                chunks.append(c)
    if chunks:
        extras["method_guides (search_guides)"] = [
            {"guide": c.guide, "heading": c.heading, "text": c.text}
            for c in chunks[:2]]
    return extras


def unchanged_today(p: Prescription, user_id: int, *, db: Session) -> bool:
    """Совпадает ли назначение с последним на ТУ ЖЕ дату из recommendations.

    Сравниваем дату (p.when), тип, зону и объём: совпало → в чате карточку
    не дублируем. Назначения на разные дни не матчатся — воскресный план
    не глушится сегодняшним и наоборот (инцидент 29.08).
    (Match against the latest recommendation for the same target date.)
    """
    rec = db.query(Recommendation).filter(
        Recommendation.user_id == user_id,
        Recommendation.for_date == p.when,
    ).order_by(Recommendation.id.desc()).first()
    if rec is None:
        return False
    target, volume = rec.target_json or {}, rec.volume_json or {}

    def _close(a, b) -> bool:  # None-безопасное сравнение чисел (tolerant compare)
        if a is None or b is None:
            return a == b
        return abs(float(a) - float(b)) < 0.05

    return (rec.workout_type == p.workout_type
            and target.get("max_zone") == p.target.get("max_zone")
            and target.get("structure") == p.target.get("structure")
            and _close(target.get("pace_min_km"), p.target.get("pace_min_km"))
            and _close(volume.get("duration_min"), p.volume.get("duration_min"))
            and _close(volume.get("distance_km"), p.volume.get("distance_km")))
