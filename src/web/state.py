# Глобальное состояние для веб-роутов (Global state for web routes)
import os
import threading
from pathlib import Path

PENDING_DIR = Path(os.getenv("PENDING_DIR", "/tmp/running_coach_uploads"))
PENDING_DIR.mkdir(parents=True, exist_ok=True)

_pending = {}  # temp_id -> dict with 'path', 'filename', 'data'
_sync_tasks = {}  # task_id -> dict with progress info
_sync_tasks_lock = threading.Lock()
_AUTO_SYNC_LOCK = threading.Lock()

TRAINING_TYPES_RU = {
    'interval': 'Интервальная',
    'long': 'Длинная',
    'recovery': 'Восстановительная',
    'tempo': 'Темповая',
}
