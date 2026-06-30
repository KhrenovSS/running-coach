"""
API пакет — публичный API для middleware и зависимостей
API package — public API for middleware and dependencies
"""

from src.api.middleware import register_middleware
from src.api.deps import get_db

__all__ = ["register_middleware", "get_db"]
