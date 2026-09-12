# Загрузчик guides (Guides loader) — DEV_PLAN §5
#
# Формат guide: front-matter между --- и --- (плоские `key: value`,
# `tags:` через запятую, блок `key_rules:` с отступом) + markdown-проза,
# порезанная на чанки по заголовкам `## `. Без PyYAML — парсер намеренно
# минимальный, формат зафиксирован. (Minimal front-matter parser, no PyYAML.)
#
# Поиск — keyword-скоринг по заголовку/тегам/тексту. Эмбеддингов нет сознательно:
# при ~10 guides и 1M контекста RAG — техдолг (DEV_PLAN §2).

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

GUIDES_DIR = Path(__file__).parent / "guides"
CHUNK_MAX_WORDS = 400


@dataclass(frozen=True)
class GuideChunk:
    guide: str          # имя файла (file name)
    heading: str
    text: str
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Guide:
    name: str
    meta: dict = field(default_factory=dict)
    key_rules: dict = field(default_factory=dict)
    chunks: tuple[GuideChunk, ...] = ()
    # правила только для фазы returning (возврат после паузы) — в дайджест при стабильном
    # стаже не попадают (12.09.2026; см. training_status.py)
    key_rules_returning: dict = field(default_factory=dict)


def _parse_front_matter(lines: list[str]) -> tuple[dict, dict, dict]:
    """Плоский front-matter + блоки key_rules / key_rules_returning
    (flat front-matter + rule blocks; the returning block is phase-gated in the digest)."""
    meta: dict = {}
    blocks: dict[str, dict] = {"key_rules": {}, "key_rules_returning": {}}
    current: str | None = None
    for line in lines:
        if not line.strip():
            continue
        head = line.rstrip()[:-1] if line.rstrip().endswith(":") else None
        if head in blocks and not line.startswith(" "):
            current = head
            continue
        if current and line.startswith("  "):
            k, _, v = line.strip().partition(":")
            blocks[current][k.strip()] = v.strip()
            continue
        current = None
        k, _, v = line.partition(":")
        v = v.strip()
        meta[k.strip()] = tuple(t.strip() for t in v.split(",")) if k.strip() == "tags" else v
    return meta, blocks["key_rules"], blocks["key_rules_returning"]


def _split_chunks(name: str, body: str, tags: tuple[str, ...]) -> tuple[GuideChunk, ...]:
    chunks: list[GuideChunk] = []
    heading, buf = "", []
    for line in body.splitlines():
        if line.startswith("## "):
            if buf and "".join(buf).strip():
                chunks.append(GuideChunk(name, heading, "\n".join(buf).strip(), tags))
            heading, buf = line[3:].strip(), []
        else:
            buf.append(line)
    if buf and "".join(buf).strip():
        chunks.append(GuideChunk(name, heading, "\n".join(buf).strip(), tags))
    # Ограничение размера чанка (chunk size cap)
    capped = []
    for c in chunks:
        words = c.text.split()
        text = " ".join(words[:CHUNK_MAX_WORDS]) if len(words) > CHUNK_MAX_WORDS else c.text
        capped.append(GuideChunk(c.guide, c.heading, text, c.tags))
    return tuple(capped)


@lru_cache(maxsize=1)
def load_guides() -> tuple[Guide, ...]:
    """Загрузить все guides (кэш на процесс — стабильные байты для промпта)."""
    guides = []
    for path in sorted(GUIDES_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        meta: dict = {}
        key_rules: dict = {}
        returning: dict = {}
        body = text
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                meta, key_rules, returning = _parse_front_matter(parts[1].splitlines())
                body = parts[2]
        tags = meta.get("tags", ())
        guides.append(Guide(name=path.name, meta=meta, key_rules=key_rules,
                            chunks=_split_chunks(path.name, body, tags),
                            key_rules_returning=returning))
    return tuple(guides)


def key_rules_digest(phase: str = "stable") -> str:
    """Компактный дайджест key_rules всех guides — для кэшируемого блока промпта.

    phase — статус подопечного (training_status.py): «возвратные» правила (key_rules_returning:
    ходьба→бег, % от пика после паузы) попадают в дайджест только при phase == "returning" —
    стабильно бегающему их видеть незачем (решение владельца 12.09.2026). Байты стабильны
    внутри одной фазы (кэш system[0] — две версии). (Phase-gated rule digest.)
    """
    lines = []
    for g in load_guides():
        for k, v in g.key_rules.items():
            lines.append(f"{g.name}: {k} = {v}")
        if phase == "returning":
            for k, v in g.key_rules_returning.items():
                lines.append(f"{g.name}: {k} = {v}")
    return "\n".join(lines)


_TYPE_GUIDE_TERMS = {
    "easy": "лёгкий бег база разговорный",
    "recovery": "восстановительный лёгкий база",
    "long": "длительный база объём",
    "tempo": "темповая интенсивность прогрессия",
    "interval": "интервалы интенсивность прогрессия",
    "race": "соревнование гонка раскладка",   # гайд 48 (Швец): день гонки и раскладка
}

# Запросы про погоду — при флаге жары/холода в разборе (weather guide queries, гайд 49 Швеца)
_HEAT_GUIDE_TERMS = "жара погода условия"
_COLD_GUIDE_TERMS = "мороз ветер снег гололёд покрытие погода"

# Запросы для плана недели (weekly-plan guide queries): обычный — мезоцикл/прогрессия;
# при возврате после паузы — ходьба→бег (гайд 47) + план возврата в % от пика (гайд 61).
_PLAN_GUIDE_TERMS = ["план недели мезоцикл фазы объём прогрессия"]
_PLAN_RETURN_GUIDE_TERMS = ["ходьба чередование бег новичок регулярность",
                            "возврат после перерыва объём пик"]


def review_guides_queries(detail: dict, computed: dict | None) -> list[str]:
    """Запросы к базе знаний из фактов тренировки (guides queries from facts) — E3.

    Боль — отдельным запросом: гайд про колено не должен вытесняться типом.
    """
    queries = []
    if detail.get("pain_level") or "pain" in ((computed or {}).get("flags") or []):
        queries.append("боль колено дискомфорт")
    type_terms = _TYPE_GUIDE_TERMS.get(detail.get("type") or "")
    if type_terms:
        queries.append(type_terms)
    # Погода — третьим запросом: вытесняется болью/типом при лимите чанков (weather last)
    heat = (computed or {}).get("heat") or {}
    if heat.get("heat_flag"):
        queries.append(_HEAT_GUIDE_TERMS)
    elif heat.get("cold_flag"):
        queries.append(_COLD_GUIDE_TERMS)
    return queries


def plan_guides_queries(targets: dict | None) -> list[str]:
    """Запросы к базе знаний для плана недели (guide queries for the weekly plan).

    detraining_return (пауза ≥ DETRAINING_RETURN_MIN_DAYS_OFF) → вход через ходьбу→бег
    (гайд 47) и план возврата в % от пика (гайд 61) вместо общей прогрессии мезоцикла.
    """
    if (targets or {}).get("detraining_return"):
        return list(_PLAN_RETURN_GUIDE_TERMS)
    if (targets or {}).get("lthr_test_due"):
        # M3.2: неделя с полевым тестом ПАНО — протокол теста рядом с общей прогрессией
        return list(_PLAN_GUIDE_TERMS) + ["полевой тест ПАНО порог 30 минут"]
    return list(_PLAN_GUIDE_TERMS)


def search(query: str, top_k: int = 3) -> list[GuideChunk]:
    """Keyword-поиск по чанкам: заголовок ×3, теги ×2, текст ×1 (keyword search)."""
    terms = [t for t in query.lower().split() if len(t) > 2]
    if not terms:
        return []
    scored = []
    for g in load_guides():
        for c in g.chunks:
            heading_l, text_l = c.heading.lower(), c.text.lower()
            tags_l = " ".join(c.tags).lower()
            score = sum(3 * (t in heading_l) + 2 * (t in tags_l) + (t in text_l)
                        for t in terms)
            if score > 0:
                scored.append((score, c))
    scored.sort(key=lambda x: (-x[0], x[1].guide, x[1].heading))
    return [c for _, c in scored[:top_k]]
