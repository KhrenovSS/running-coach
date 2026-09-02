# Prescriber — единая точка сборки назначения (single assembly point) — DEV_PLAN §4
#
# finalize(): предложение (LLM или fallback) → evaluate_safety → clamp → Prescription
# (+ опциональная запись в recommendations). Другого пути к Prescription нет.
# (proposal → safety → clamp → prescription; there is no other path.)

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from src.analysis.hr_zones import zone_ceiling_hr
from src.services.repositories import latest_lthr, latest_ltsp
from src.coach.contracts import (
    AthleteState,
    PaceClampContext,
    Prescription,
    WorkoutProposal,
)
from src.coach.fallback import fallback_proposal
from src.coach.rules.p1_safety import evaluate_safety
from src.coach.safety import clamp
from src.config import settings
from src.config.constants import BASELINE_WINDOW_DAYS
from src.models import Recommendation, User
from src.utils.logger import get_logger

logger = get_logger("coach.prescriber")


def user_max_hr(user: User | None) -> int:
    """max_hr пользователя с дефолтом настроек (user max HR with settings default)."""
    return user.max_hr if user and user.max_hr else settings.default_max_hr


def predict_volume(p: Prescription, state: AthleteState, *, db: Session) -> dict:
    """Справочные ориентиры по км-точкам прошлых пробежек (data-driven estimate).

    Пожелание владельца 26.08.2026: карточка представляет все параметры —
    ведущие как цель, производные ориентировочно. HR-режим: цель — пульс+время,
    ориентир — темп и дистанция. Pace-режим: цель — темп+время (дистанция
    детерминирована в clamp), ориентир — ожидаемый пульс. Эмпирические медианы,
    не экстраполяция. Нет данных → {}.
    """
    from src.services.workout_insights import expected_hr_at_pace, expected_pace_at_hr

    if p.workout_type == "rest":
        return {}
    target_pace = p.target.get("pace_min_km")
    if target_pace is not None:
        estimate = expected_hr_at_pace(state.user_id, target_pace, db=db)
        if estimate is None:
            return {}
        return {"expected_hr": estimate["hr_bpm"],
                "pace_min_km": target_pace,
                "based_on": {"n_points": estimate["n_points"],
                             "window_days": BASELINE_WINDOW_DAYS}}
    zone, duration = p.target.get("max_zone"), p.volume.get("duration_min")
    if zone is None or duration is None:
        return {}
    user = db.query(User).filter(User.id == state.user_id).first()
    ceiling = zone_ceiling_hr(zone, user_max_hr(user),
                              latest_lthr(state.user_id, db=db))
    if ceiling is None:
        return {}
    estimate = expected_pace_at_hr(state.user_id, ceiling, db=db)
    if estimate is None:
        return {}
    pace = estimate["pace_min_km"]
    return {"pace_min_km": pace,
            "distance_km": round(duration / pace, 1),
            "hr_ceiling": ceiling,
            "based_on": {"n_points": estimate["n_points"],
                         "window_days": BASELINE_WINDOW_DAYS}}


def _pace_clamp_context(proposal: WorkoutProposal, verdict, state: AthleteState,
                        *, db: Session) -> PaceClampContext:
    """Прекомпьют оценок для safety-ветки темпа (clamp остаётся без БД).

    Потолок зоны считается по УЖЕ урезанной safety зоне — clamp сверяет
    расчётный пульс с тем, что реально будет разрешено. (Precompute for clamp.)
    """
    from src.services.workout_insights import expected_hr_at_pace, expected_pace_at_hr

    user = db.query(User).filter(User.id == state.user_id).first()
    zone = min(proposal.target_zone, verdict.max_zone)
    ceiling = zone_ceiling_hr(zone, user_max_hr(user),
                              latest_lthr(state.user_id, db=db))  # Z5 → None
    est_hr = expected_hr_at_pace(state.user_id, proposal.target_pace_min_km, db=db)
    est_pace = (expected_pace_at_hr(state.user_id, ceiling, db=db)
                if ceiling is not None else None)
    return PaceClampContext(
        expected_hr=est_hr["hr_bpm"] if est_hr else None,
        safe_pace_min_km=est_pace["pace_min_km"] if est_pace else None,
        zone_ceiling_bpm=ceiling,
    )


def finalize(proposal: WorkoutProposal | None, state: AthleteState, *,
             db: Session | None = None, persist: bool = False,
             source: str = "fallback", now: datetime | None = None) -> Prescription:
    """Собрать назначение: safety вычисляется здесь же, clamp безусловный.

    proposal=None → детерминированное табличное предложение (fallback).
    (Assemble prescription; safety is computed here, clamp is unconditional.)
    """
    verdict = evaluate_safety(state, now=now)
    if proposal is None:
        proposal = fallback_proposal(state)
        source = "fallback"
    pace_ctx = None
    if db is not None and proposal.target_pace_min_km is not None:
        pace_ctx = _pace_clamp_context(proposal, verdict, state, db=db)
    prescription, clamped = clamp(proposal, verdict, state, now=now, source=source,
                                  pace_ctx=pace_ctx)
    if clamped:
        logger.info("Prescription clamped for user=%s: %s -> %s (%s)",
                    state.user_id, proposal.workout_type,
                    prescription.workout_type, ",".join(verdict.triggered))
    if db is not None:
        prescription.predicted = predict_volume(prescription, state, db=db)
    if db is not None and proposal.segments:
        # Числа сегментам проставляются ПОСЛЕ clamp — по итоговым зоне/типу (симметрично
        # predict_volume). enrich сам вернёт [], если структуру нельзя показать безопасно.
        from src.coach.segments import enrich_and_clamp_segments
        user = db.query(User).filter(User.id == state.user_id).first()
        seg_dicts = enrich_and_clamp_segments(
            proposal.segments,
            workout_type=prescription.workout_type,
            proposal_type=proposal.workout_type,
            max_zone=prescription.target.get("max_zone", 1),
            max_hr=user_max_hr(user),
            lthr=latest_lthr(state.user_id, db=db),
            ltsp_s_km=latest_ltsp(state.user_id, db=db),
            user_id=state.user_id, db=db)
        from src.coach.render_segments import is_monotone
        # Ровная пробежка (разминка/бег/заминка, один ровный блок) — без сущностей:
        # целиком «пульс до N · время» (решение владельца 02.09.2026). Ускорения и блоки
        # с разным пульсом сохраняются. (Monotone structure is not persisted.)
        if seg_dicts and not is_monotone(seg_dicts):
            prescription.target["segments"] = seg_dicts
    if persist and db is not None:
        save_prescription(prescription, state, db=db)
    return prescription


def save_prescription(p: Prescription, state: AthleteState, *, db: Session,
                      status: str = "proposed") -> Recommendation:
    """Записать назначение в recommendations (persist prescription).

    proposal_json — предложение ДО урезания, safety_json — вердикт: метрика
    дрейфа LLM (DEV_PLAN §1.6). status: proposed (день) | planned (вс-план) |
    adjusted (замена планового дня); confirmed ставится UPDATE'ом в planning;
    superseded — UPDATE при перепланировании (planning.supersede_future_rows).
    """
    from src.coach.tools.serialize import jsonable

    rec = Recommendation(
        user_id=state.user_id,
        for_date=p.when,
        workout_type=p.workout_type,
        target_json=p.target,
        volume_json=p.volume,
        rationale_json=[{"rule": r.rule, "decision": r.decision, "reason": r.reason}
                        for r in p.rationale],
        predicted_json=p.predicted,
        confidence=p.confidence,
        status=status,
        proposal_json=jsonable(p.proposal) if p.proposal else None,
        safety_json=jsonable(p.safety),
        clamped=p.clamped,
        source=p.source,
    )
    db.add(rec)
    db.commit()
    return rec
