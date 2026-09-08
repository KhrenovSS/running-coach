#!/usr/bin/env python3
# Пересчёт набора/спуска высоты истории по гистерезису (#253, 08.09.2026).
# (Backfill elevation gain/loss with the hysteresis algorithm.)
#
# Перезаписывает TrainingSession.elevation_gain/elevation_loss и ключи elevation_gain/elevation_loss
# в segments_json из trackpoints_json тем же calc_elevation, что и живой пайплайн. Сессии без
# трекпоинтов не трогаются. Обратимо: повторный расчёт с --hysteresis 0 вернёт наивную сумму.
#
# Запуск (в контейнере app; сначала bin/backup_db.sh):
#   docker compose exec app python bin/backfill_elevation.py --dry-run   # таблица старое/новое/часы
#   docker compose exec app python bin/backfill_elevation.py             # запись

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analysis.utils import calc_elevation  # noqa: E402
from src.config.constants import ELEV_HYSTERESIS_M  # noqa: E402
from src.models import SessionLocal, TrainingSession  # noqa: E402


def _segment_bounds(tps: list[dict], segments: list[dict]) -> list[tuple[int, int]]:
    """Границы сегментов по накопленной длительности (segments carry duration_min)."""
    bounds, start, cumul = [], 0, 0.0
    times = [tp.get("time") for tp in tps]
    if not times or times[0] is None:
        return []
    from datetime import datetime
    t0 = datetime.fromisoformat(times[0]) if isinstance(times[0], str) else times[0]
    for seg in segments:
        cumul += float(seg.get("duration_min") or 0)
        end = start
        while end < len(tps):
            t = times[end]
            t = datetime.fromisoformat(t) if isinstance(t, str) else t
            if (t - t0).total_seconds() / 60 > cumul:
                break
            end += 1
        bounds.append((start, max(end, start + 1)))
        start = end
    return bounds


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--hysteresis", type=float, default=ELEV_HYSTERESIS_M)
    ap.add_argument("--user", type=int)
    args = ap.parse_args()
    db = SessionLocal()
    changed, ratios = 0, []
    try:
        q = db.query(TrainingSession).filter(TrainingSession.trackpoints_json.isnot(None))
        if args.user:
            q = q.filter(TrainingSession.user_id == args.user)
        rows = q.order_by(TrainingSession.begin_ts).all()
        print(f"{'id':>4} {'date':10} {'gain_old':>8} {'gain_new':>8} {'watch':>6} | {'loss_old':>8} {'loss_new':>8} {'watch':>6}")
        for s in rows:
            tps = s.trackpoints_json or []
            alts = [tp.get("alt") for tp in tps]
            if not any(a is not None for a in alts):
                continue
            gain, loss = calc_elevation(alts, hysteresis_m=args.hysteresis)
            ds = s.device_summary if isinstance(s.device_summary, dict) else {}
            wa, wd = ds.get("total_ascent_m"), ds.get("total_descent_m")
            print(f"{s.id:>4} {s.begin_ts.date()} {s.elevation_gain or 0:>8} {gain:>8} {wa if wa is not None else '-':>6} | "
                  f"{s.elevation_loss or 0:>8} {loss:>8} {wd if wd is not None else '-':>6}")
            if wa:
                ratios.append(gain / wa)
            segments = s.segments_json if isinstance(s.segments_json, list) else []
            new_segments = None
            if segments and all("duration_min" in seg for seg in segments):
                bounds = _segment_bounds(tps, segments)
                if len(bounds) == len(segments):
                    new_segments = []
                    for seg, (a, b) in zip(segments, bounds):
                        g, l = calc_elevation(alts[a:b], hysteresis_m=args.hysteresis)
                        new_segments.append({**seg, "elevation_gain": g, "elevation_loss": l})
            if not args.dry_run:
                s.elevation_gain, s.elevation_loss = gain, loss
                if new_segments is not None:
                    s.segments_json = new_segments
                changed += 1
        if ratios:
            print(f"median new/watch = {statistics.median(ratios):.2f} (n={len(ratios)})")
        if args.dry_run:
            print("dry-run: ничего не записано")
        else:
            db.commit()
            print(f"updated {changed} sessions")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
