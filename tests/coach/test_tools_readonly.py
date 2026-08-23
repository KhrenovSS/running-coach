# Source-гвард: tools НЕ пишут в БД (Tools are read-only) — DEV_PLAN §1.4
# LLM не может изменить состояние БД — единственная фраза модели угроз.
import re
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[2] / "src" / "coach" / "tools"

_WRITE = re.compile(r"\bdb\.(add|add_all|commit|delete|merge|execute|flush)\s*\(")


def test_tools_never_write_to_db():
    violations = []
    for path in TOOLS_DIR.rglob("*.py"):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _WRITE.search(line) and not line.lstrip().startswith("#"):
                violations.append(f"{path.name}:{i}: {line.strip()}")
    assert not violations, (
        "Запись в БД из tools — нарушение read-only инварианта (DEV_PLAN §1.4):\n"
        + "\n".join(violations)
    )
