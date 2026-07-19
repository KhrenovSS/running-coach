import threading
import time

_awaiting_weight: dict[int, bool] = {}
_awaiting_weight_lock = threading.Lock()

# Pending deletion confirmation: chat_id -> timestamp when /delete_me was called
# Confirmation must happen within 5 minutes
_pending_deletion: dict[int, float] = {}
_pending_deletion_lock = threading.Lock()
DELETE_CONFIRM_TIMEOUT_SEC = 5 * 60


def clear_awaiting_weight(chat_id: int | None = None):
    with _awaiting_weight_lock:
        if chat_id is not None:
            _awaiting_weight.pop(chat_id, None)
        else:
            _awaiting_weight.clear()


def set_pending_deletion(chat_id: int):
    with _pending_deletion_lock:
        _pending_deletion[chat_id] = time.time()


def check_pending_deletion(chat_id: int) -> bool:
    """Return True if confirmation is valid (within timeout), False otherwise."""
    with _pending_deletion_lock:
        ts = _pending_deletion.pop(chat_id, None)
        if ts is None:
            return False
        return (time.time() - ts) < DELETE_CONFIRM_TIMEOUT_SEC
