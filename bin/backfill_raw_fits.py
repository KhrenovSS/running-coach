#!/usr/bin/env python3
# Backfill исходных FIT-файлов из API бренда (BACKLOG #229, Этап 4 ремедиации).
# (One-off backfill of raw FIT files from the brand API.)
#
# Для сессий с external_activity_id (заполняется bin/backfill_external_ids.py) и без
# raw_file_path: скачивает FIT из API и сохраняет в uploads/raw/<user_id>/<sha256>.fit.
# ⚠️ История в API Coros конечна — чем раньше запустить, тем больше сырья сохраним.
#
# БЕЗОПАСНОСТЬ: по умолчанию --dry-run (только отчёт). Скачивание+запись — с --apply.
# Скрипт только ДОБАВЛЯЕТ файлы и заполняет NULL-колонки; ничего не удаляет. Идемпотентен.
# Требует запуска ПОСЛЕ backfill_external_ids.py --apply (матчинг по внешнему ID).
#
# Запуск:
#   docker compose exec app python bin/backfill_raw_fits.py            # dry-run
#   docker compose exec app python bin/backfill_raw_fits.py --apply

import argparse
import asyncio
import sys
from pathlib import Path

# sys.path[0] = bin/ при прямом запуске — добавляем корень проекта (add project root)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config.constants import WATCH_API_PAGE_THROTTLE_SEC
from src.models import SessionLocal, TrainingSession, WatchCredential
from src.services.raw_files import save_raw_file, sha256_hex
from src.services.sync.utils import _make_client
from src.utils.logger import get_logger

logger = get_logger("backfill.raw_fits")

# Coros sport_type для бега — download_activity требует его (running sport type for download)
SPORT_TYPE_RUNNING = 100


async def _backfill_cred(db, cred, apply: bool) -> dict:
    stats = {'saved': 0, 'skipped': 0, 'failed': 0, 'candidates': 0}
    sessions = db.query(TrainingSession).filter(
        TrainingSession.user_id == cred.user_id,
        TrainingSession.source_brand == cred.brand,
        TrainingSession.external_activity_id.isnot(None),
        TrainingSession.raw_file_path.is_(None),
    ).all()
    stats['candidates'] = len(sessions)
    if not sessions:
        return stats
    if not apply:
        return stats

    client = await _make_client(cred)
    if not client:
        logger.error("Auth failed for brand=%s user=%s — пропуск", cred.brand, cred.user_id)
        stats['failed'] = len(sessions)
        return stats
    try:
        for s in sessions:
            try:
                fit_bytes = await client.download_activity(s.external_activity_id, SPORT_TYPE_RUNNING)
            except Exception:
                logger.warning("Download failed for session=%d act=%s", s.id, s.external_activity_id,
                               exc_info=True)
                stats['failed'] += 1
                continue
            if not fit_bytes:
                logger.warning("Пусто из API: session=%d act=%s (история могла истечь)", s.id, s.external_activity_id)
                stats['failed'] += 1
                continue
            path = save_raw_file(cred.user_id, fit_bytes, 'fit')
            if path is None:
                stats['failed'] += 1
                continue
            s.raw_file_path = path
            if s.file_sha256 is None:
                s.file_sha256 = sha256_hex(fit_bytes)
            db.commit()
            stats['saved'] += 1
            logger.info("RAW saved: session=%d → %s", s.id, path)
            # Троттлинг: неофициальный API (throttle for the unofficial API)
            await asyncio.sleep(WATCH_API_PAGE_THROTTLE_SEC)
        return stats
    finally:
        try:
            await client.close()
        except Exception:
            logger.warning("client.close() failed", exc_info=True)


def main():
    parser = argparse.ArgumentParser(description="Backfill raw FIT files from brand API")
    parser.add_argument('--apply', action='store_true',
                        help='скачать и записать (без флага — dry-run, только счётчики)')
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
            print(f"  brand={cred.brand} user={cred.user_id}: candidates={stats['candidates']} "
                  f"saved={stats['saved']} failed={stats['failed']}")
        if not args.apply:
            print("Dry-run: ничего не скачано. Перезапусти с --apply "
                  "(сначала bin/backfill_external_ids.py --apply).")
    finally:
        db.close()


if __name__ == '__main__':
    main()
