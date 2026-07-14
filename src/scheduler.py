# Фоновый планировщик автосинхронизации (Background auto-sync scheduler — per-user intervals)
import time
import threading
from src.utils.logger import get_logger
from src.services.sync import SYNC_TICK_INTERVAL, auto_sync_health, auto_sync_activities

logger = get_logger("app")


class AutoSyncScheduler:
    _instance = None
    _lock = threading.Lock()
    _started = threading.Event()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def start(self):
        with self._lock:
            if self._started.is_set():
                return
            self._started.set()
        thread = threading.Thread(target=self._loop, daemon=True, name="auto-sync-scheduler")
        thread.start()
        logger.info("Автосинхронизация: фоновый поток запущен (per-user intervals)")

    def _loop(self):
        logger.info("Автосинхронизация: запуск планировщика (tick=%dс, per-user intervals)", SYNC_TICK_INTERVAL)
        time.sleep(30)
        while True:
            try:
                auto_sync_health()
            except Exception:
                logger.exception("Автосинхронизация: ошибка health sync")
            try:
                auto_sync_activities()
            except Exception:
                logger.exception("Автосинхронизация: ошибка activity sync")
            time.sleep(SYNC_TICK_INTERVAL)
