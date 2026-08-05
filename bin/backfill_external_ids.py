#!/usr/bin/env python3
# Backfill внешних ID активностей (BACKLOG #228, Этап 3 ремедиации).
# (One-off backfill of external activity ids from the brand API.)
#
# Для каждого активного WatchCredential: качает полный список активностей из API
# и матчит к существующим TrainingSession БЕЗ external_activity_id:
#   |start_time − begin_ts| ≤ DEDUP_TIME_WINDOW_SEC; при неоднозначности — ближайший
#   + проверка дистанции ±5% (если обе стороны её знают). Неоднозначные — пропускаются.
#
# БЕЗОПАСНОСТЬ: по умолчанию --dry-run (только отчёт). Запись — ТОЛЬКО с --apply.
# Перед --apply на проде: bin/backup_db.sh. Обратимо:
#   UPDATE training_sessions SET external_activity_id=NULL, source_brand=NULL WHERE source_brand='<brand>';
#
# Запуск:
#   docker compose exec app python bin/backfill_external_ids.py            # dry-run
#   docker compose exec app python bin/backfill_external_ids.py --apply

import argparse
import asyncio
import sys
from pathlib import Path

# sys.path[0] = bin/ при прямом запуске — добавляем корень проекта (add project root)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config.constants import DEDUP_TIME_WINDOW_SEC
from src.models import SessionLocal, TrainingSession, WatchCredential
from src.services.sync.utils import _make_client, ensure_aware_utc
from src.utils.logger import get_logger

logger = get_logger("backfill.external_ids")


def _match_activity(act: dict, candidates: list) -> tuple:
    """Найти сессию для активности: (session|None, 'matched'|'ambiguous'|'unmatched').
    (Find the session for an API activity.)"""
    st = act.get('start_time')
    if st is None:
        return None, 'unmatched'
    near = [s for s in candidates
            if abs((ensure_aware_utc(s.begin_ts) - st).total_seconds()) <= DEDUP_TIME_WINDOW_SEC]
    if not near:
        return None, 'unmatched'
    if len(near) > 1:
        near.sort(key=lambda s: abs((ensure_aware_utc(s.begin_ts) - st).total_seconds()))
        # Неоднозначность: подтверждаем ближайшего дистанцией ±5% (confirm nearest by distance ±5%)
        best = near[0]
        act_km = (act.get('distance_m') or 0) / 1000
        if act_km and best.total_distance_km and abs(best.total_distance_km - act_km) / act_km > 0.05:
            return None, 'ambiguous'
        return best, 'matched'
    s = near[0]
    act_km = (act.get('distance_m') or 0) / 1000
    if act_km and s.total_distance_km and abs(s.total_distance_km - act_km) / act_km > 0.05:
        return None, 'ambiguous'  # время совпало, дистанция нет — руками (time ok, distance off — manual)
    return s, 'matched'


async def _backfill_cred(db, cred, apply: bool) -> dict:
    stats = {'matched': 0, 'ambiguous': 0, 'unmatched': 0, 'already': 0}
    client = await _make_client(cred)
    if not client:
        logger.error("Auth failed for brand=%s user=%s — пропуск", cred.brand, cred.user_id)
        return stats
    try:
        activities = await client.list_activities(since=None)  # вся доступная история (full history)
        logger.info("brand=%s user=%s: API вернул %d активностей", cred.brand, cred.user_id, len(activities))

        existing_ext = {r[0] for r in db.query(TrainingSession.external_activity_id).filter(
            TrainingSession.user_id == cred.user_id,
            TrainingSession.external_activity_id.isnot(None),
        ).all()}
        candidates = db.query(TrainingSession).filter(
            TrainingSession.user_id == cred.user_id,
            TrainingSession.external_activity_id.is_(None),
        ).all()
        claimed = set()  # id сессий, уже сматченных в этом прогоне (sessions claimed this run)

        for act in activities:
            if act.get('id') in existing_ext:
                stats['already'] += 1
                continue
            session, verdict = _match_activity(act, [s for s in candidates if s.id not in claimed])
            stats[verdict] += 1
            if session is None:
                if verdict == 'ambiguous':
                    logger.warning("AMBIGUOUS: act=%s %s %.1fкм — руками", act.get('id'),
                                   act.get('start_time'), (act.get('distance_m') or 0) / 1000)
                continue
            claimed.add(session.id)
            logger.info("MATCH: session=%d begin=%s ← act=%s", session.id, session.begin_ts, act.get('id'))
            if apply:
                session.external_activity_id = act.get('id')
                session.source_brand = cred.brand
        if apply:
            db.commit()
        return stats
    finally:
        try:
            await client.close()
        except Exception:
            logger.warning("client.close() failed", exc_info=True)


def main():
    parser = argparse.ArgumentParser(description="Backfill external activity ids")
    parser.add_argument('--apply', action='store_true',
                        help='записать изменения (без флага — dry-run, только отчёт)')
    parser.add_argument('--user', type=int, default=None, help='ограничить одним user_id')
    args = parser.parse_args()

    db = SessionLocal()
    try:
        q = db.query(WatchCredential).filter(
            WatchCredential.is_active == True,  # noqa: E712
            WatchCredential.encrypted_password.isnot(None),
        )
        if args.user:
            q = q.filter(WatchCredential.user_id == args.user)
        creds = q.all()
        if not creds:
            print("Нет активных WatchCredential — нечего бэкфиллить")
            return

        mode = "APPLY" if args.apply else "DRY-RUN"
        print(f"[{mode}] Кредов к обработке: {len(creds)}")
        for cred in creds:
            stats = asyncio.run(_backfill_cred(db, cred, apply=args.apply))
            print(f"  brand={cred.brand} user={cred.user_id}: "
                  f"matched={stats['matched']} already={stats['already']} "
                  f"ambiguous={stats['ambiguous']} unmatched={stats['unmatched']}")
        if not args.apply:
            print("Dry-run: ничего не записано. Перезапусти с --apply (после bin/backup_db.sh).")
    finally:
        db.close()


if __name__ == '__main__':
    main()
