#!/usr/bin/env python3
# Исследование наклона базовой линии HR↔GAP-темп (BACKLOG #259). READ-ONLY: только SELECT.
# (Research: HR↔pace baseline slope estimators. Read-only — nothing is written.)
#
# Сравнивает оценщики наклона b (bpm за мин/км) на км-точках steady-тренировок окна:
#   pooled    — OLS по всем км-точкам (текущий прод, занижен: шум x + межсессионные условия);
#   means     — OLS по сессионным средним;
#   within    — fixed effects: демин по сессии, OLS на остатках (снимает условия дня);
#   within_t  — within + HR минус heat.expected_hr_shift_bpm сессии (температурная поправка);
#   deming_*  — ортогональная регрессия с δ = var_err_y / var_err_x (pooled и within_t).
# Для каждого: σ сессионных остатков, доля сессий с |z| ≥ BASELINE_Z_FLAG, bootstrap-CI по сессиям.
#
# Запуск: docker compose exec app python bin/research_hr_baseline_slope.py [--user ID] [--boot 200]

import argparse
import math
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analysis.hr_baseline import km_points  # noqa: E402
from src.coach.util import effective_training_type  # noqa: E402
from src.config.constants import (  # noqa: E402
    BASELINE_TYPES, BASELINE_WINDOW_DAYS, BASELINE_Z_FLAG,
)
from src.models import SessionLocal, TrainingSession, UserModel, WorkoutInsight  # noqa: E402

DELTAS = (100.0, 400.0, 1600.0)
MIN_SESSION_POINTS = 3


def _mean(v):
    return sum(v) / len(v)


def _ols(xs, ys):
    """OLS slope/intercept; None при вырождении."""
    n = len(xs)
    if n < 3:
        return None
    mx, my = _mean(xs), _mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return b, my - b * mx


def _deming(xs, ys, delta):
    """Deming: δ = var(err_y)/var(err_x). Возвращает наклон или None."""
    n = len(xs)
    if n < 3:
        return None
    mx, my = _mean(xs), _mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs) / n
    syy = sum((y - my) ** 2 for y in ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / n
    if sxy == 0:
        return None
    return (syy - delta * sxx + math.sqrt((syy - delta * sxx) ** 2 + 4 * delta * sxy ** 2)) / (2 * sxy)


def _demeaned(sessions):
    """Within-session остатки (x−x̄_s, y−ȳ_s) по сессиям с ≥ MIN_SESSION_POINTS точек."""
    xs, ys = [], []
    for pts in sessions:
        if len(pts) < MIN_SESSION_POINTS:
            continue
        mx = _mean([p for p, _ in pts])
        my = _mean([h for _, h in pts])
        xs.extend(p - mx for p, _ in pts)
        ys.extend(h - my for _, h in pts)
    return xs, ys


def _estimators(sessions, sessions_t):
    """sessions — [(pace, hr)] по сессиям; sessions_t — то же с HR минус temp shift."""
    out = {}
    flat_x = [p for pts in sessions for p, _ in pts]
    flat_y = [h for pts in sessions for _, h in pts]
    r = _ols(flat_x, flat_y)
    out["pooled"] = r[0] if r else None
    mx = [_mean([p for p, _ in pts]) for pts in sessions]
    my = [_mean([h for _, h in pts]) for pts in sessions]
    r = _ols(mx, my)
    out["means"] = r[0] if r else None
    wx, wy = _demeaned(sessions)
    r = _ols(wx, wy)
    out["within"] = r[0] if r else None
    wxt, wyt = _demeaned(sessions_t)
    r = _ols(wxt, wyt)
    out["within_t"] = r[0] if r else None
    for d in DELTAS:
        out[f"deming_pooled_{int(d)}"] = _deming(flat_x, flat_y, d)
        out[f"deming_within_t_{int(d)}"] = _deming(wxt, wyt, d)
    return out


Z_GRID = (1.5, 2.0, 2.5)


def _session_residuals(sessions_t, b):
    """Сессионные остатки при наклоне b и интерсепте через среднюю точку (temp-corrected)."""
    mx = [_mean([p for p, _ in pts]) for pts in sessions_t]
    my = [_mean([h for _, h in pts]) for pts in sessions_t]
    a = _mean(my) - b * _mean(mx)
    return a, [y - (a + b * x) for x, y in zip(mx, my)]


def _session_sigma(sessions_t, b, z_flag=BASELINE_Z_FLAG):
    """σ сессионных остатков; доля сессий с |z| ≥ z_flag."""
    if b is None:
        return None, None
    _, res = _session_residuals(sessions_t, b)
    sigma = (sum(r ** 2 for r in res) / len(res)) ** 0.5
    share = sum(1 for r in res if sigma > 0 and abs(r / sigma) >= z_flag) / len(res)
    return sigma, share


def _bootstrap(sessions, sessions_t, keys, reps, seed=42):
    rng = random.Random(seed)
    n = len(sessions)
    acc = {k: [] for k in keys}
    for _ in range(reps):
        idx = [rng.randrange(n) for _ in range(n)]
        est = _estimators([sessions[i] for i in idx], [sessions_t[i] for i in idx])
        for k in keys:
            if est.get(k) is not None:
                acc[k].append(est[k])
    ci = {}
    for k, vals in acc.items():
        if len(vals) < 10:
            ci[k] = None
            continue
        vals.sort()
        ci[k] = (vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1])
    return ci


def _load(db, user_id):
    cutoff = datetime.now(timezone.utc) - timedelta(days=BASELINE_WINDOW_DAYS)
    rows = db.query(WorkoutInsight, TrainingSession).join(
        TrainingSession, WorkoutInsight.session_id == TrainingSession.id,
    ).filter(WorkoutInsight.user_id == user_id, TrainingSession.begin_ts >= cutoff).all()
    sessions, sessions_t, meta = [], [], []
    for insight, s in rows:
        if effective_training_type(s) not in BASELINE_TYPES:
            continue
        cj = insight.computed_json or {}
        gap = cj.get("gap") or {}
        if not gap.get("available"):
            continue
        pts = km_points(gap.get("per_km") or [])
        if not pts:
            continue
        shift = (cj.get("heat") or {}).get("expected_hr_shift_bpm") or 0
        sessions.append(pts)
        sessions_t.append([(p, h - shift) for p, h in pts])
        meta.append((s.begin_ts.date().isoformat(), effective_training_type(s), len(pts),
                     round(_mean([p for p, _ in pts]), 2), round(_mean([h for _, h in pts])), shift))
    return sessions, sessions_t, meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", type=int)
    ap.add_argument("--boot", type=int, default=200)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    db = SessionLocal()
    try:
        q = db.query(UserModel.user_id)
        if args.user:
            q = q.filter(UserModel.user_id == args.user)
        user_ids = sorted({uid for (uid,) in q})
        for uid in user_ids:
            um = db.query(UserModel).filter(UserModel.user_id == uid).first()
            stored = (um.params_json or {}).get("hr_pace_baseline") if um else None
            sessions, sessions_t, meta = _load(db, uid)
            print(f"\n=== user {uid}: sessions={len(sessions)} points={sum(len(s) for s in sessions)} "
                  f"stored={stored}")
            if len(sessions) < 3:
                print("  мало сессий — пропуск")
                continue
            if args.verbose:
                for m in sorted(meta):
                    print("  ", m)
            mx = [m[3] for m in meta]
            print(f"  session mean pace range: {min(mx):.2f}–{max(mx):.2f} min/km; "
                  f"temp shifts: {sorted({m[5] for m in meta})}")
            est = _estimators(sessions, sessions_t)
            keys = list(est)
            ci = _bootstrap(sessions, sessions_t, keys, args.boot)
            print(f"  {'estimator':24} {'b':>7} {'CI95 low':>9} {'CI95 high':>9} {'sigma':>6} {'flag%':>6}")
            for k in keys:
                b = est[k]
                sigma, share = _session_sigma(sessions_t, b)
                c = ci.get(k)
                bs = f"{b:7.2f}" if b is not None else "   None"
                cs = f"{c[0]:9.2f} {c[1]:9.2f}" if c else f"{'—':>9} {'—':>9}"
                ss = f"{sigma:6.2f} {share * 100:5.0f}%" if sigma is not None else ""
                print(f"  {k:24} {bs} {cs} {ss}")
            b = est["pooled"]
            if b is not None:
                a, res = _session_residuals(sessions_t, b)
                sigma, _ = _session_sigma(sessions_t, b)
                print(f"  pooled, temp-corrected intercept a={a:.1f} (stored a={stored and stored.get('a')}); "
                      f"session sigma={sigma:.2f}; km-RMSE stored={stored and stored.get('rmse_bpm')}")
                for z in Z_GRID:
                    _, share = _session_sigma(sessions_t, b, z)
                    print(f"    |z| >= {z}: {share * 100:.0f}% sessions  (|delta| >= {z * sigma:.1f} bpm)")
                if args.verbose:
                    print("   residuals by date:", [(m[0], round(r, 1)) for m, r in zip(meta, res)])
    finally:
        db.close()


if __name__ == "__main__":
    main()
