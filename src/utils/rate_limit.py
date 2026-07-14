import time
import threading
from collections import defaultdict
from fastapi import Request, HTTPException
from src.utils.logger import get_logger

logger = get_logger("rate_limit")

_buckets: dict = defaultdict(list)
_lock = threading.Lock()


def rate_limit(max_requests: int = 10, window_seconds: int = 60):
    def _rate_limit(request: Request):
        ip = request.client.host if request.client else "unknown"
        now = time.time()
        key = f"{ip}:{request.url.path}"
        with _lock:
            timestamps = _buckets[key]
            timestamps = [t for t in timestamps if now - t < window_seconds]
            timestamps.append(now)
            _buckets[key] = timestamps
            count = len(timestamps)
        if count > max_requests:
            logger.warning(
                "Rate limit exceeded: %s (%d requests in %ds)",
                key, count, window_seconds,
            )
            raise HTTPException(status_code=429, detail="Too many requests")
    return _rate_limit
