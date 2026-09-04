# Карточка недельного отчёта (weekly report card) — C8.1, 03.09.2026
#
# Все числа — из week_report.compute_week_report (код), ни одно не берётся из прозы LLM.
# Строки без данных пропускаются (честная деградация). ✓/⚠ — по порогам coach/config.
# Решение владельца 03.09.2026: карточка только про тренировки (без HRV/RHR/сна);
# сравнение — прошлая неделя + среднее за N недель + ряд недель.
# (Deterministic weekly card; lines without data are omitted.)

from __future__ import annotations

from datetime import date

from src.coach.config import (
    DISTRIBUTION_80_20,
    EFFICIENCY_GAIN_BPM,
    EFFICIENCY_LOSS_BPM,
    HARD_SHARE_OVERLOAD,
    LOAD_RATIO_LOW,
    LONG_RUN_MAX_PCT_WEEK,
    WEEK_REPORT_ACWR_HIGH,
)

_MINUS = "−"   # типографский минус вместо дефиса в «−3 уд/мин» (typographic minus)


def _plural_runs(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "пробежка"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "пробежки"
    return "пробежек"


def _fmt_hours(minutes: float | int) -> str:
    h, m = divmod(int(round(minutes)), 60)
    return f"{h} ч {m:02d} мин" if h else f"{m} мин"


def _signed(value: float, digits: int = 0) -> str:
    text = f"{value:+.{digits}f}"
    return text.replace("-", _MINUS)


def _header(r: dict) -> str:
    ws, we = date.fromisoformat(r["week_start"]), date.fromisoformat(r["week_end"])
    head = f"*Итоги недели {ws:%d.%m}–{we:%d.%m}*"
    t = r.get("targets") or {}
    if t.get("mesocycle_week") and t.get("mesocycle_length"):
        phase = "разгрузка" if t.get("phase") == "deload" else "рост"
        head += f" · неделя {t['mesocycle_week']}/{t['mesocycle_length']} мезоцикла ({phase})"
    if r.get("week_in_progress"):
        head += " · неделя ещё идёт"
    return head


def _volume_line(this: dict, targets: dict) -> str:
    line = (f"Объём: {this['km']:.1f} км · {this['runs']} {_plural_runs(this['runs'])}"
            f" · {_fmt_hours(this['minutes'])}")
    if targets.get("target_km"):
        line += f" · цель ~{targets['target_km']:.0f} км"
        if targets.get("pct_of_target") is not None:
            line += f" ({targets['pct_of_target']:.0%})"
    return line


def _compare_line(this: dict, prev: dict | None, avg: dict | None) -> str | None:
    parts = []
    if prev and prev["runs"] > 0:
        parts.append(f"К прошлой: {_signed(this['km'] - prev['km'], 1)} км ({prev['km']:.1f})")
    if avg and avg.get("weeks"):
        parts.append(f"среднее за {avg['weeks']} нед: {avg['km']:.1f} км")
    return " · ".join(parts) if parts else None


def _easy_line(this: dict, prev: dict | None) -> str | None:
    easy = this.get("easy_time_share")
    if easy is None:
        return None
    target = DISTRIBUTION_80_20["easy_share_target"]
    line = f"Лёгкое время (Z1–2): {easy:.0%} · цель ≥{target:.0%}"
    if prev and prev.get("easy_time_share") is not None:
        line += f" · прошлая {prev['easy_time_share']:.0%}"
    if this.get("hard_time_share", 0) > HARD_SHARE_OVERLOAD:
        line += " ⚠"
    elif easy >= target:
        line += " ✓"
    return line


def _quality_line(this: dict, targets: dict) -> str | None:
    if this["runs"] == 0:
        return None
    q = f"Качество: {this['quality_runs']}"
    if targets.get("hard_days_max") is not None:
        q += f" из {targets['hard_days_max']}"
    parts = [q]
    if this.get("long_run_share") is not None:
        lr = (f"длительная {this['long_run_km']:.1f} км = {this['long_run_share']:.0%} недели")
        if this["long_run_share"] > LONG_RUN_MAX_PCT_WEEK:
            lr += f" ⚠ (потолок {LONG_RUN_MAX_PCT_WEEK:.0%})"
        parts.append(lr)
    return " · ".join(parts)


def _load_line(this: dict, prev: dict | None, acwr: float | None) -> str | None:
    parts = []
    if this.get("load_points") is not None:
        parts.append(f"Нагрузка: {this['load_points']} баллов")
        if prev and prev.get("load_points") is not None:
            parts.append(f"прошлая {prev['load_points']}")
    if acwr is not None:
        if acwr > WEEK_REPORT_ACWR_HIGH:
            label = "высокая ⚠"
        elif acwr < LOAD_RATIO_LOW:
            label = "низкая"
        else:
            label = "норма"
        parts.append(f"острая/хроническая {acwr:.2f} ({label})")
    return " · ".join(parts) if parts else None


def _efficiency_line(this: dict) -> str | None:
    delta, n = this.get("efficiency_delta_bpm"), this.get("efficiency_n") or 0
    if delta is None:
        return None
    runs_word = "пробежке" if n == 1 else "пробежкам"
    shift = ("на уровне базы" if round(delta) == 0
             else f"{_signed(delta)} уд/мин к базе")          # без «−0 уд/мин»
    line = f"Экономичность: пульс на своём темпе {shift} (по {n} {runs_word})"
    if delta <= EFFICIENCY_GAIN_BPM:
        line += " ✓"
    elif delta >= EFFICIENCY_LOSS_BPM:
        line += " ⚠"
    return line


def _adherence_line(adh: dict | None) -> str | None:
    if not adh or not adh.get("planned"):
        return None
    return (f"План недели: выполнено {adh.get('done', 0)} · пропущено {adh.get('missed', 0)}"
            f" · скорректировано {adh.get('adjusted', 0)}")


def _series_line(series: list[dict]) -> str | None:
    if len(series) < 2:
        return None
    return f"{len(series)} недель: " + " · ".join(f"{w['km']:.0f}" for w in series) + " км"


def render_week_report(r: dict) -> str:
    """Карточка «Итоги недели» — детерминированно из week_report (weekly card)."""
    this, prev = r["this"], r.get("prev")
    targets = r.get("targets") or {}
    lines = [_header(r)]
    if this["runs"] == 0:
        lines.append("Пробежек на этой неделе не было" if not r.get("week_in_progress")
                     else "Пробежек пока не было")
    else:
        for line in (_volume_line(this, targets),
                     _compare_line(this, prev, r.get("avg_prev")),
                     _easy_line(this, prev),
                     _quality_line(this, targets),
                     _load_line(this, prev, r.get("acwr")),
                     _efficiency_line(this),
                     _adherence_line(r.get("adherence"))):
            if line:
                lines.append(line)
    series = _series_line(r.get("series") or [])
    if series:
        lines.append(series)
    return "\n".join(lines)
