# Numeric-consistency checker (#247): проза LLM не должна противоречить карточке.
#
# v1 — только обнаружение (решение 29.08.2026): расхождения логируются и
# помечаются в meta_json assistant-строки; текст пользователю НЕ меняется
# (обрезание прозы — отдельное решение после наблюдений). Закрывает остаточный
# риск из ARCHITECTURE.md «проза может исказить число».
# (Detect-only v1: prose numbers are checked against the clamped card.)

from __future__ import annotations

import re

from src.analysis.hr_zones import zone_ceiling_hr
from src.coach.contracts import Prescription

# Число + единица: км, минуты, темп M:SS/км, зона Z1-5, пульс
_KM_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*км\b", re.IGNORECASE)
_MIN_RE = re.compile(r"(\d+)\s*мин\b", re.IGNORECASE)
_PACE_RE = re.compile(r"(\d)[:.](\d{2})\s*/\s*км", re.IGNORECASE)
_ZONE_RE = re.compile(r"\bZ([1-5])\b", re.IGNORECASE)
_HR_RE = re.compile(r"(\d{2,3})\s*(?:уд/мин|уд\.|bpm)", re.IGNORECASE)

_KM_TOL = 1.0        # км: ±1 (проза округляет «около шести»)
_MIN_TOL = 5.0       # минуты: ±5
_PACE_TOL = 0.25     # темп: ±15 сек/км
_HR_TOL = 5.0        # пульс: ±5 уд/мин


def _expected_values(p: Prescription, max_hr: int | None) -> dict[str, list[float]]:
    """Эталонные числа карточки: target/volume/predicted + потолок пульса зоны."""
    km = [v for v in (p.volume.get("distance_km"),
                      (p.predicted or {}).get("distance_km")) if v]
    minutes = [v for v in (p.volume.get("duration_min"),) if v]
    pace = [v for v in (p.target.get("pace_min_km"),
                        (p.predicted or {}).get("pace_min_km")) if v]
    hr = [v for v in ((p.predicted or {}).get("expected_hr"),) if v]
    zone = p.target.get("max_zone")
    if zone is not None and max_hr is not None:
        ceiling = zone_ceiling_hr(zone, max_hr)
        if ceiling is not None:
            hr.append(float(ceiling))
    # Пульсовые числа сегментов (детерминированы кодом): в карточке легальны,
    # проза может на них ссылаться — добавляем в эталон, чтобы не ловить ложное.
    for seg in (p.target.get("segments") or []):
        if seg.get("hr_ceiling") is not None:
            hr.append(float(seg["hr_ceiling"]))
        rec = seg.get("recovery") or {}
        if rec.get("until_hr") is not None:
            hr.append(float(rec["until_hr"]))
    return {"km": km, "min": minutes, "pace": pace, "hr": hr,
            "zone": [float(zone)] if zone is not None else []}


def _mismatches(found: list[float], expected: list[float], tol: float,
                unit: str) -> list[str]:
    if not expected:
        # Эталона нет (например rest) — любое число этого рода подозрительно,
        # но без эталона честного сравнения нет: пропускаем (не спамим ложным)
        return []
    return [f"{v:g} {unit} ≠ карточке ({'/'.join(f'{e:g}' for e in expected)})"
            for v in found
            if not any(abs(v - e) <= tol for e in expected)]


def check_prose(message: str, p: Prescription | None,
                max_hr: int | None = None) -> list[str]:
    """Числа тренировки в прозе, противоречащие карточке (пусто = всё сходится).

    Structure-строки типа «10×400/400» не парсим — они попадают в карточку
    дословно из p.target['structure'] и в прозе легальны.
    """
    if p is None or not message:
        return []
    exp = _expected_values(p, max_hr)
    out: list[str] = []
    out += _mismatches([float(m.replace(",", "."))
                        for m in _KM_RE.findall(message)],
                       exp["km"], _KM_TOL, "км")
    out += _mismatches([float(m) for m in _MIN_RE.findall(message)],
                       exp["min"], _MIN_TOL, "мин")
    out += _mismatches([int(a) + int(b) / 60.0
                        for a, b in _PACE_RE.findall(message)],
                       exp["pace"], _PACE_TOL, "мин/км")
    out += _mismatches([float(m) for m in _HR_RE.findall(message)],
                       exp["hr"], _HR_TOL, "уд/мин")
    out += _mismatches([float(m) for m in _ZONE_RE.findall(message)],
                       exp["zone"], 0.0, "зона")
    return out
