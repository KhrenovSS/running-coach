# Numeric-consistency checker (#247): проза LLM не должна противоречить карточке.
#
# v1 (29.08.2026) — обнаружение: расхождения логируются и помечаются в meta_json
# assistant-строки. v2 (11.09.2026, решение владельца): страховка — предложение прозы с чужим
# числом вырезается (`trim_mismatched_prose`), в конец добавляется «Числа — в карточке ниже».
# Основание: за 29.08–11.09 на проде 0 расхождений из 83 ответов — ложных срабатываний тоже 0.
# Закрывает остаточный риск из ARCHITECTURE.md «проза может исказить число» кодом, не промптом.
# (v1 detect-only; v2 trims the offending sentence — numbers are rendered by code.)

from __future__ import annotations

import re

from src.analysis.hr_zones import zone_ceiling_hr
from src.coach.contracts import Prescription
from src.coach.llm.config import NUMERIC_TRIM_FALLBACK_TEXT, NUMERIC_TRIM_NOTE

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


def _expected_values(p: Prescription, max_hr: int | None,
                     lthr: int | None = None) -> dict[str, list[float]]:
    """Эталонные числа карточки: target/volume/predicted + потолок пульса зоны."""
    km = [v for v in (p.volume.get("distance_km"),
                      (p.predicted or {}).get("distance_km")) if v]
    minutes = [v for v in (p.volume.get("duration_min"),) if v]
    pace = [v for v in (p.target.get("pace_min_km"),
                        (p.predicted or {}).get("pace_min_km")) if v]
    hr = [v for v in ((p.predicted or {}).get("expected_hr"),) if v]
    zone = p.target.get("max_zone")
    if zone is not None and max_hr is not None:
        ceiling = zone_ceiling_hr(zone, max_hr, lthr)
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


def _mismatches(found: list[tuple[str, float]], expected: list[float], tol: float,
                unit: str) -> list[tuple[str, str]]:
    """(токен прозы, описание) для чисел вне допуска. found — (сырой токен, значение)."""
    if not expected:
        # Эталона нет (например rest) — любое число этого рода подозрительно,
        # но без эталона честного сравнения нет: пропускаем (не спамим ложным)
        return []
    return [(tok, f"{v:g} {unit} ≠ карточке ({'/'.join(f'{e:g}' for e in expected)})")
            for tok, v in found
            if not any(abs(v - e) <= tol for e in expected)]


_PCT_RE = re.compile(r"(\d+)\s*%")


def prose_numbers(message: str) -> list[str]:
    """Числа тренировок/недели в прозе (км/мин/темп/пульс/%) — для ходов, где все числа
    отдаёт детерминированная карточка (недельный отчёт, C8.1): нашли → лог + meta,
    текст не режем (#247). (Training numbers found in prose that should carry none.)"""
    found: list[str] = []
    for rx in (_KM_RE, _MIN_RE, _PACE_RE, _HR_RE, _PCT_RE):
        found += [m.group(0) for m in rx.finditer(message)]
    return found


def mismatch_pairs(message: str, p: Prescription | None,
                   max_hr: int | None = None, lthr: int | None = None) -> list[tuple[str, str]]:
    """(токен прозы, описание расхождения) для чисел, противоречащих карточке.

    Structure-строки типа «10×400/400» не парсим — они попадают в карточку
    дословно из p.target['structure'] и в прозе легальны.
    (Raw prose token + human description per mismatching number.)
    """
    if p is None or not message:
        return []
    exp = _expected_values(p, max_hr, lthr)
    out: list[tuple[str, str]] = []
    out += _mismatches([(m.group(0), float(m.group(1).replace(",", ".")))
                        for m in _KM_RE.finditer(message)],
                       exp["km"], _KM_TOL, "км")
    out += _mismatches([(m.group(0), float(m.group(1))) for m in _MIN_RE.finditer(message)],
                       exp["min"], _MIN_TOL, "мин")
    out += _mismatches([(m.group(0), int(m.group(1)) + int(m.group(2)) / 60.0)
                        for m in _PACE_RE.finditer(message)],
                       exp["pace"], _PACE_TOL, "мин/км")
    out += _mismatches([(m.group(0), float(m.group(1))) for m in _HR_RE.finditer(message)],
                       exp["hr"], _HR_TOL, "уд/мин")
    out += _mismatches([(m.group(0), float(m.group(1))) for m in _ZONE_RE.finditer(message)],
                       exp["zone"], 0.0, "зона")
    return out


def check_prose(message: str, p: Prescription | None,
                max_hr: int | None = None, lthr: int | None = None) -> list[str]:
    """Числа тренировки в прозе, противоречащие карточке (пусто = всё сходится)."""
    return [desc for _, desc in mismatch_pairs(message, p, max_hr, lthr)]


# --- v2 (11.09.2026): обрезание предложения с чужим числом ---
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")


def trim_mismatched_prose(message: str, tokens: list[str]) -> tuple[str, list[str]]:
    """Убрать из прозы предложения, содержащие токены расхождений; вернуть (текст, удалённые).

    Абзацы сохраняются; предложения делятся по .!?… + пробел. Пустой результат → нейтральная
    фраза NUMERIC_TRIM_FALLBACK_TEXT. Если что-то вырезано — в конец один раз NUMERIC_TRIM_NOTE
    («числа — в карточке»). Без токенов текст возвращается как есть.
    (Drop sentences carrying mismatching tokens; keep paragraphs; add the card note once.)
    """
    if not message or not tokens:
        return message, []
    removed: list[str] = []
    paragraphs_out: list[str] = []
    for para in message.split("\n"):
        if not para.strip():
            paragraphs_out.append(para)
            continue
        kept = []
        for sent in _SENTENCE_SPLIT_RE.split(para):
            if any(tok in sent for tok in tokens):
                removed.append(sent.strip())
            else:
                kept.append(sent)
        paragraphs_out.append(" ".join(kept).strip())
    if not removed:
        return message, []
    text = "\n".join(paragraphs_out).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if not text:
        text = NUMERIC_TRIM_FALLBACK_TEXT
    return f"{text}\n\n{NUMERIC_TRIM_NOTE}", removed


# --- #316 (07.09.2026): проза плана недели vs карта — типы и число беговых дней ---
_WORD_NUM = {"одн": 1, "дв": 2, "тр": 3, "четыр": 4, "пят": 5, "шест": 6, "сем": 7}
_RUNS_RE = re.compile(
    r"\b(\d+|одн\w*|дв\w*|тр(?:и|ёх|ех)\w*|четыр\w*|пят\w*|шест\w*|сем\w*)\s+"
    r"(?:(спокойн\w*|лёгк\w*|легк\w*)\s+|беговы\w*\s+)?"
    r"(пробеж\w*|трениров\w*|дн[яей]+\b(?!\s+отдых))", re.IGNORECASE)


def _to_int(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    low = token.lower()
    for stem, n in _WORD_NUM.items():
        if low.startswith(stem):
            return n
    return None


def check_plan_prose(message: str, prescriptions: list[Prescription],
                     plan_scope: str = "week") -> list[str]:
    """Расхождения прозы плана недели с картой (пусто = сходится) — детект, текст не режем.

    Проверяем только полную неделю (plan_scope="week": при остатке недели проза может говорить
    о неделе целиком): число беговых дней в прозе («пять спокойных дней», «4 пробежки») против
    числа тренировочных карточек; упоминание темповой/интервалов/длительной без такой карточки
    (06.09: «частота та же» при 4 → 5, «пять спокойных дней вокруг одной длительной» при 4 + 1).
    (Plan prose vs card: run-day counts and named workout types; detect-only.)
    """
    if not message or not prescriptions or plan_scope != "week":
        return []
    types = [p.workout_type for p in prescriptions if p.workout_type and p.workout_type != "rest"]
    n_easy = sum(1 for t in types if t in ("easy", "recovery"))
    out: list[str] = []
    for m in _RUNS_RE.finditer(message):
        n = _to_int(m.group(1))
        # «пять спокойных дней» — про лёгкие; «пять пробежек» — про все беговые
        expected = n_easy if m.group(2) else len(types)
        if n is not None and n != expected:
            out.append(f"«{m.group(0)}» ≠ карточке ({expected} "
                       f"{'лёгких' if m.group(2) else 'беговых'} дней)")
    low = message.lower()
    if "темпов" in low and "tempo" not in types:
        out.append("темповая в прозе, в карте её нет")
    if "интервал" in low and "interval" not in types:
        out.append("интервалы в прозе, в карте их нет")
    if "длительн" in low and "long" not in types:
        out.append("длительная в прозе, в карте её нет")
    return out
