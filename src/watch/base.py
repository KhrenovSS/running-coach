# Базовый абстрактный класс для клиентов часов (Abstract base class for watch clients)
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional


class BaseWatchClient(ABC):
    """Базовый интерфейс для интеграции с API различных брендов часов (Base interface for watch brand API integration)"""

    @abstractmethod
    async def authenticate(self) -> bool:
        ...

    @abstractmethod
    async def list_activities(self, since: Optional[datetime] = None) -> list[dict]:
        ...

    @abstractmethod
    async def download_activity(self, activity_id: str, sport_type: int) -> Optional[bytes]:
        ...

    @abstractmethod
    async def get_daily_metrics(self, start_day: str, end_day: str) -> list[dict]:
        ...

    @abstractmethod
    async def get_dashboard(self) -> dict:
        ...

    @abstractmethod
    async def get_analytics(self) -> list[dict]:
        ...