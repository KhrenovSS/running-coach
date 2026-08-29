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
    COACH_RECENT_REVIEWS_LIMIT,
)
from src.coach.tools.registry import run_tool
from src.models import Recommendation, User
from src.utils.timeutils import local_dt, user_now


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
    from datetime import date as _date

    from src.services.repositories_insights import InsightRepository
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
        user = db.query(User).filter(User.id == user_id).first()
        today = user_now(user).date()
        extras["recent_reviews (workout_insights)"] = [{
            "days_ago": ((today - local_dt(r.created_at, user).date()).days
                         if r.created_at else None),
            "session_id": r.session_id,
            "effort_match": r.effort_match,
            "flags": (r.assessment_json or {}).get("flags"),
            "carry_forward": r.carry_forward,
        } for r in reviews]
    rec = db.query(Recommendation).filter(
        Recommendation.user_id == user_id,
        Recommendation.for_date >= _date.today(),
    ).order_by(Recommendation.id.desc()).first()
    if rec is not None:
        # Действующее назначение: наутро модель видит, что уже назначала
        # (митигация конфликта «карточка разбора vs утренний вердикт», D7).
        # target/volume — чтобы в чате модель видела зону/объём и не назначала
        # заново без причины (proposal=null → карточка не дублируется).
        extras["planned_workout (recommendations)"] = {
            "for_date": rec.for_date.isoformat(), "type": rec.workout_type,
            "source": rec.source, "clamped": rec.clamped,
            "target": rec.target_json, "volume": rec.volume_json,
        }
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
    """Совпадает ли назначение с последним сегодняшним из recommendations.

    Сравниваем тип, зону и объём: совпало → в чате карточку не дублируем.
    (Does the prescription match today's latest recommendation?)
    """
    from datetime import date as _date

    rec = db.query(Recommendation).filter(
        Recommendation.user_id == user_id,
        Recommendation.for_date >= _date.today(),
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
