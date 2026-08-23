# Контекст выполнения tool'а (Tool execution context) — DEV_PLAN §5
#
# `db` приходит ТОЛЬКО отсюда, из композиционного корня (telegram-хендлер/джоба):
# ни один handler не открывает SessionLocal сам (§8 CLAUDE.md, тест-гвард).
# (db comes only from the composition root; handlers never open sessions.)

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session


@dataclass
class ToolContext:
    """Request-scoped контекст: пользователь + сессия БД (request-scoped context)."""
    user_id: int
    db: Session
