# Гвард целостности документации (Docs integrity guard — рефакторинг документации 02.09.2026)
#
# Документы не читаются программно, поэтому их дрейф невидим. Этот тест ловит три вещи:
#   1) ссылка на *.md (в бэктиках или markdown-ссылке) указывает на несуществующий файл;
#   2) файл в docs/ не упомянут в индексе — таблице «Документация» в CLAUDE.md (сирота);
#   3) отменённая дорожная карта («8 этапов» rules-first) снова всплыла вне архива
#      (бывший ручной grep-набор DEV_PLAN §11.3; сам rules-first дизайн удалён 02.09.2026, история git).
# (Docs are prose only; this guard catches dangling paths, orphan docs and resurrected
#  superseded roadmap wording outside docs/archive.)

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
DOCS = ROOT / "docs"
ARCHIVE = DOCS / "archive"
INDEX_FILE = ROOT / "CLAUDE.md"

# Живые документы, которые сканируем на ссылки (scanned for links)
SCANNED = [ROOT / "CLAUDE.md", ROOT / "AGENTS.md", ROOT / "README.md", ROOT / "BACKLOG.md"]
SCANNED += [p for p in DOCS.rglob("*.md") if ARCHIVE not in p.parents]

# Пути, которые допустимо не резолвить: ссылки на сырьё дистилляции книг (вне репозитория/gitignore)
# (allowed unresolved: pointers into books/_distilled raw notes)
ALLOW_UNRESOLVED_PREFIXES = ("fitzgerald/", "daniels/", "books/")

# Формулировки отменённого rules-first плана — допустимы только в архиве и CHANGELOG
# (superseded-roadmap wording allowed only in archive / CHANGELOG)
FORBIDDEN_PHRASES = ("8 этапов", "LLM — только интерфейс", "Следующий шаг — Этап 1")

_MD_REF = re.compile(r"`([^`\s]+?\.md)(?::\d+)?`|\]\(([^)\s#]+?\.md)(?:#[^)]*)?\)")


def _resolve(token: str, from_file: Path) -> bool:
    candidates = (ROOT / token, from_file.parent / token, DOCS / token)
    return any(c.is_file() for c in candidates)


def test_md_references_resolve():
    dangling = []
    for f in SCANNED:
        for m in _MD_REF.finditer(f.read_text(encoding="utf-8")):
            token = m.group(1) or m.group(2)
            if token.startswith(ALLOW_UNRESOLVED_PREFIXES) or "*" in token:
                continue  # glob-паттерны вроде `*.md` — не ссылки (globs are not references)
            if not _resolve(token, f):
                dangling.append(f"{f.relative_to(ROOT)} → {token}")
    assert not dangling, "Битые ссылки на документы (dangling doc references):\n" + "\n".join(dangling)


def test_every_doc_is_indexed_in_claude_md():
    index = INDEX_FILE.read_text(encoding="utf-8")
    orphans = []
    for p in DOCS.rglob("*.md"):
        if ARCHIVE in p.parents:
            continue  # архив индексируется одной строкой (archive/README.md)
        if str(p.relative_to(ROOT)) not in index:
            orphans.append(str(p.relative_to(ROOT)))
    assert "docs/archive/README.md" in index
    assert not orphans, (
        "Документы без строки в таблице «Документация» CLAUDE.md (orphan docs): "
        f"{orphans}. Добавь строку в индекс или перенеси файл в docs/archive/."
    )


def test_superseded_roadmap_wording_only_in_archive():
    hits = []
    for p in ROOT.rglob("*.md"):
        rel = p.relative_to(ROOT)
        parts = rel.parts
        if parts[0] in (".venv", "books", ".pytest_cache", "node_modules") or ARCHIVE in p.parents:
            continue
        if rel.name == "CHANGELOG.md" or "knowledge" in parts:
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        for phrase in FORBIDDEN_PHRASES:
            if phrase in text:
                hits.append(f"{rel}: «{phrase}»")
    assert not hits, "Отменённая дорожная карта вне архива (superseded roadmap wording):\n" + "\n".join(hits)
