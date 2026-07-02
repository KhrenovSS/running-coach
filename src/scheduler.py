# Фоновый планировщик автосинхронизации (Background auto-sync scheduler — brand-agnostic)
import time
import random
import threading
from src.logger import get_logger
from src.services.sync_service import health_sync_interval, activity_sync_interval, auto_sync_health, auto_sync_activities

logger = get_logger("app")


class AutoSyncScheduler:
    _instance = None
    _lock = threading.Lock()
    _started = False

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def start(self):
        if self._started:
            return
        self._started = True
        thread = threading.Thread(target=self._loop, daemon=True, name="auto-sync-scheduler")
        thread.start()
        logger.info("Автосинхронизация: фоновый поток запущен (brand-agnostic)")

    def _loop(self):
        logger.info("Автосинхронизация: запуск планировщика (health=%dс, activities=%dс)",
                     health_sync_interval, activity_sync_interval)
        time.sleep(30)
        last_health = 0.0
        last_activity = 0.0
        while True:
            now = time.time()
            try:
                if now - last_health >= health_sync_interval * random.uniform(0.8, 1.2):
                    logger.info("Автосинхронизация: health sync")
                    auto_sync_health()
                    last_health = time.time()
            except Exception:
                logger.exception("Автосинхронизация: ошибка health sync")
            try:
                if now - last_activity >= activity_sync_interval * random.uniform(0.8, 1.2):
                    logger.info("Автосинхронизация: activity sync")
                    auto_sync_activities()
                    last_activity = time.time()
            except Exception:
                logger.exception("Автосинхронизация: ошибка activity sync")
            time.sleep(300)
