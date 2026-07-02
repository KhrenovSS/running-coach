# Фабрика клиентов часов (Watch client factory / registry)
from typing import Optional
from src.watch.base import BaseWatchClient

_registry: dict[str, type[BaseWatchClient]] = {}


def register(brand: str, client_cls: type[BaseWatchClient]) -> None:
    """Зарегистрировать класс клиента для бренда (Register a client class for a brand)"""
    _registry[brand.lower()] = client_cls


def get_watch_client(brand: str, **kwargs) -> Optional[BaseWatchClient]:
    """Создать экземпляр клиента для бренда (Create a client instance for a brand)"""
    cls = _registry.get(brand.lower())
    if cls is None:
        return None
    return cls(**kwargs)


def list_brands() -> list[str]:
    """Список зарегистрированных брендов (List registered brands)"""
    return list(_registry.keys())