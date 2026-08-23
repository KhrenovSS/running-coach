# Tool знаний: search_guides (knowledge tool) — DEV_PLAN §5

from __future__ import annotations

from src.coach.knowledge.loader import search
from src.coach.tools.context import ToolContext


def search_guides(ctx: ToolContext, args: dict) -> dict:
    """Поиск по методическим руководствам (search the coaching guides)."""
    query = str(args.get("query", ""))[:200]
    top_k = int(args.get("top_k", 3))
    chunks = search(query, top_k=top_k)
    return {"chunks": [
        {"guide": c.guide, "heading": c.heading, "text": c.text, "tags": list(c.tags)}
        for c in chunks
    ]}
