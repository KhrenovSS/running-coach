# Глобальное состояние для веб-роутов (Global state for web routes)
import os
import threading
import time
from datetime import timedelta
from pathlib import Path

PENDING_DIR = Path(os.getenv("PENDING_DIR", "uploads/pending"))
PENDING_DIR.mkdir(parents=True, exist_ok=True)

_pending = {}  # temp_id -> dict with 'path', 'filename', 'data'
_pending_lock = threading.Lock()
_sync_tasks = {}  # task_id -> dict with progress info
_sync_tasks_lock = threading.Lock()
_AUTO_SYNC_LOCK = threading.Lock()

_PENDING_TTL = timedelta(hours=1)

def _cleanup_stale_pending():
    now = time.time()
    with _pending_lock:
        stale = [tid for tid, entry in list(_pending.items())
                 if now - entry.get('_created', now) > _PENDING_TTL.total_seconds()]
        for tid in stale:
            entry = _pending.pop(tid, None)
            if entry:
                Path(entry['path']).unlink(missing_ok=True)

TRAINING_TYPES_RU = {
    'easy': 'Лёгкая пробежка',
    'interval': 'Интервальная',
    'long': 'Длинная',
    'recovery': 'Восстановительная',
    'tempo': 'Темповая',
}
