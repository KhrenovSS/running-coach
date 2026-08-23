# JSON-сериализация результатов tool'ов (JSON serialization for tool results)

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Any


def jsonable(obj: Any) -> Any:
    """Рекурсивно привести объект к JSON-сериализуемому виду (make JSON-serializable)."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return jsonable(asdict(obj))
    if isinstance(obj, dict):
        return {k: jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return obj
