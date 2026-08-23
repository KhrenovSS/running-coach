# Source-гвард: Prescription конструируется ТОЛЬКО в safety.clamp() (DEV_PLAN §1.2)
# По образцу tests/test_session_ownership.py — грепает src/ и валит CI при нарушении.
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"

# Единственные файлы, где допустим вызов Prescription(...):
# contracts.py — определение класса; safety.py — единственный конструктор (clamp).
ALLOWED = {
    SRC / "coach" / "contracts.py",
    SRC / "coach" / "safety.py",
}

_CALL = re.compile(r"\bPrescription\s*\(")


def test_prescription_constructed_only_in_safety():
    violations = []
    for path in SRC.rglob("*.py"):
        if path in ALLOWED:
            continue
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if _CALL.search(line) and not line.lstrip().startswith("#"):
                violations.append(f"{path.relative_to(SRC.parent)}:{i}: {line.strip()}")
    assert not violations, (
        "Prescription(...) вне safety.clamp() — нарушение границы безопасности "
        "(DEV_PLAN §1.2):\n" + "\n".join(violations)
    )
