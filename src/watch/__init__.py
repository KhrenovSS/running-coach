# Пакет мульти-брендовой абстракции часов (Multi-brand watch client abstraction)
from src.watch.base import BaseWatchClient
from src.watch.factory import register, get_watch_client, list_brands
from src.watch.coros import CorosWatchClient

# Регистрируем Coros при импорте пакета (Register Coros on package import)
register("coros", CorosWatchClient)

__all__ = ["BaseWatchClient", "register", "get_watch_client", "list_brands", "CorosWatchClient"]